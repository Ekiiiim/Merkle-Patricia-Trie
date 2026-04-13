#!/usr/bin/env python3
"""HTTP API for the interactive MPT web demo. Run: uvicorn api_server:app --reload"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal, Optional
import threading

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mpt import MerklePatriciaTrie, trie_to_dot, verify_inclusion, verify_inclusion_trace
from mpt.persistent import PersistentMPT

app = FastAPI(title="MPT demo API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TrieOp(BaseModel):
    op: Literal["insert", "delete"]
    key: str = Field(..., description="UTF-8 key bytes for the trie")
    value: str | None = Field(
        None, description="UTF-8 value for insert; ignored for delete"
    )


class ReplayRequest(BaseModel):
    operations: list[TrieOp] = Field(default_factory=list)


class VerifyDemoRequest(BaseModel):
    operations: list[TrieOp] = Field(default_factory=list)
    prove_key: str = Field(..., description="UTF-8 key to prove after replay")


class DbLoadRequest(BaseModel):
    db_name: str = Field(..., description="Database file name under ./db (e.g. test_mpt.db)")


_DB_DIR = _ROOT / "db"
_DB_DIR.mkdir(exist_ok=True)

# Simple single-user demo state (process-local).
_state_lock = threading.Lock()
_active_db_name: Optional[str] = None
_active_ops: list[TrieOp] = []
_active_steps: list[dict] = []


def _list_db_names() -> list[str]:
    return sorted(p.name for p in _DB_DIR.glob("*.db") if p.is_file())


def _db_path_for(name: str) -> Path:
    # Restrict to files under ./db to avoid path traversal.
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid db_name")
    p = (_DB_DIR / name).resolve()
    if p.parent != _DB_DIR.resolve():
        raise HTTPException(status_code=400, detail="Invalid db_name")
    return p


def _ops_is_prefix(prefix: list[TrieOp], full: list[TrieOp]) -> bool:
    if len(prefix) > len(full):
        return False
    for a, b in zip(prefix, full):
        if a.op != b.op or a.key != b.key or (a.value or None) != (b.value or None):
            return False
    return True


def _apply_ops(ops: list[TrieOp]) -> MerklePatriciaTrie:
    t = MerklePatriciaTrie()
    for o in ops:
        if o.op == "insert":
            if o.value is None:
                raise HTTPException(status_code=400, detail="insert requires value")
            t.insert(o.key.encode("utf-8"), o.value.encode("utf-8"))
        else:
            if not t.delete(o.key.encode("utf-8")):
                raise HTTPException(
                    status_code=400,
                    detail=f"delete: key not found ({o.key!r})",
                )
    return t


@app.post("/api/replay")
def replay(body: ReplayRequest) -> dict:
    """
    If no DB is loaded: replay operations from an empty in-memory trie.
    If a DB is loaded: apply operations incrementally to the loaded SQLite DB, and
    return (cached) Graphviz steps for this DB session.
    """
    with _state_lock:
        db_name = _active_db_name
        if db_name is None:
            # Stateless, in-memory replay (original behavior).
            t = MerklePatriciaTrie()
            steps: list[dict] = [
                {
                    "label": "0 - empty trie",
                    "state_root_hex": t.state_root().hex(),
                    "dot": trie_to_dot(t.snapshot(), title="0 - empty trie"),
                }
            ]
            for idx, o in enumerate(body.operations):
                if o.op == "insert":
                    if o.value is None:
                        raise HTTPException(status_code=400, detail="insert requires value")
                    t.insert(o.key.encode("utf-8"), o.value.encode("utf-8"))
                    label = f"{idx + 1} - insert({o.key} -> {o.value})"
                else:
                    if not t.delete(o.key.encode("utf-8")):
                        raise HTTPException(
                            status_code=400,
                            detail=f"delete: key not found ({o.key!r})",
                        )
                    label = f"{idx + 1} - delete({o.key})"
                snap = t.snapshot()
                steps.append(
                    {
                        "label": label,
                        "state_root_hex": t.state_root().hex(),
                        "dot": trie_to_dot(snap, title=label),
                    }
                )
            return {
                "steps": steps,
                "final_state_root_hex": t.state_root().hex(),
                "active_db": None,
            }

        # DB mode (stateful): enforce that client ops extend the server ops.
        if not _ops_is_prefix(_active_ops, body.operations):
            raise HTTPException(
                status_code=400,
                detail=(
                    "DB mode expects the submitted operations to extend the current history. "
                    "Use Reset (or unload/reload DB) before sending a different history."
                ),
            )
        delta = body.operations[len(_active_ops) :]

    # Apply delta outside the lock (DB work can be slow).
    db_path = _db_path_for(db_name)
    with PersistentMPT(str(db_path), create_if_missing=False) as pmpt:
        for o in delta:
            if o.op == "insert":
                if o.value is None:
                    raise HTTPException(status_code=400, detail="insert requires value")
                pmpt.insert(o.key.encode("utf-8"), o.value.encode("utf-8"))
                label = f"{len(_active_steps)} - insert({o.key} -> {o.value})"
            else:
                if not pmpt.delete(o.key.encode("utf-8")):
                    raise HTTPException(
                        status_code=400,
                        detail=f"delete: key not found ({o.key!r})",
                    )
                label = f"{len(_active_steps)} - delete({o.key})"
            pmpt.commit()
            snap = pmpt.trie.snapshot()
            step = {
                "label": label,
                "state_root_hex": pmpt.state_root().hex(),
                "dot": trie_to_dot(snap, title=label),
            }
            with _state_lock:
                _active_steps.append(step)
        with _state_lock:
            _active_ops[:] = list(body.operations)
            steps_out = list(_active_steps)
    return {
        "steps": steps_out,
        "final_state_root_hex": steps_out[-1]["state_root_hex"] if steps_out else pmpt.state_root().hex(),
        "active_db": db_name,
    }


@app.post("/api/verify-demo")
def verify_demo(body: VerifyDemoRequest) -> dict:
    """
    If no DB loaded: after replaying ``operations`` from empty, build an inclusion proof.
    If DB loaded: ensure operations extend current history, apply delta to DB, then prove
    against the current DB head.
    """
    with _state_lock:
        db_name = _active_db_name
        ops_prefix = list(_active_ops)
        steps_len = len(_active_steps)
    if db_name is None:
        t = _apply_ops(body.operations)
        key_b = body.prove_key.encode("utf-8")
        val = t.lookup(key_b)
        if val is None:
            raise HTTPException(
                status_code=400,
                detail=f"Key not in trie after replay ({body.prove_key!r})",
            )
        proved = t.prove(key_b)
        if proved is None:
            raise HTTPException(status_code=500, detail="prove() returned None")
        _got_val, proof = proved
        root = t.state_root()
        verified, trace_steps = verify_inclusion_trace(root, key_b, val, proof)
        if verified != verify_inclusion(root, key_b, val, proof):
            raise RuntimeError("verify_inclusion_trace disagrees with verify_inclusion")
        return {
            "state_root_hex": root.hex(),
            "prove_key": body.prove_key,
            "value_hex": val.hex(),
            "proof_nodes_hex": [p.hex() for p in proof],
            "verify_steps": trace_steps,
            "verified": verified,
            "root_rlp_hex": proof[0].hex(),
            "root_keccak_hex": root.hex(),
            "active_db": None,
        }

    if not _ops_is_prefix(ops_prefix, body.operations):
        raise HTTPException(
            status_code=400,
            detail=(
                "DB mode expects the submitted operations to extend the current history. "
                "Use Reset (or unload/reload DB) before sending a different history."
            ),
        )
    delta = body.operations[len(ops_prefix) :]
    db_path = _db_path_for(db_name)
    with PersistentMPT(str(db_path), create_if_missing=False) as pmpt:
        for o in delta:
            if o.op == "insert":
                if o.value is None:
                    raise HTTPException(status_code=400, detail="insert requires value")
                pmpt.insert(o.key.encode("utf-8"), o.value.encode("utf-8"))
                label = f"{steps_len} - insert({o.key} -> {o.value})"
            else:
                if not pmpt.delete(o.key.encode("utf-8")):
                    raise HTTPException(
                        status_code=400,
                        detail=f"delete: key not found ({o.key!r})",
                    )
                label = f"{steps_len} - delete({o.key})"
            pmpt.commit()
            snap = pmpt.trie.snapshot()
            step = {
                "label": label,
                "state_root_hex": pmpt.state_root().hex(),
                "dot": trie_to_dot(snap, title=label),
            }
            with _state_lock:
                _active_steps.append(step)
                steps_len += 1
        with _state_lock:
            _active_ops[:] = list(body.operations)

        key_b = body.prove_key.encode("utf-8")
        val = pmpt.lookup(key_b)
        if val is None:
            raise HTTPException(
                status_code=400,
                detail=f"Key not in trie ({body.prove_key!r})",
            )
        proved = pmpt.prove(key_b)
        if proved is None:
            raise HTTPException(status_code=500, detail="prove() returned None")
        _got_val, proof = proved
        root = pmpt.state_root()
        verified, trace_steps = verify_inclusion_trace(root, key_b, val, proof)
        if verified != verify_inclusion(root, key_b, val, proof):
            raise RuntimeError("verify_inclusion_trace disagrees with verify_inclusion")
        return {
            "state_root_hex": root.hex(),
            "prove_key": body.prove_key,
            "value_hex": val.hex(),
            "proof_nodes_hex": [p.hex() for p in proof],
            "verify_steps": trace_steps,
            "verified": verified,
            "root_rlp_hex": proof[0].hex(),
            "root_keccak_hex": root.hex(),
            "active_db": db_name,
        }


@app.get("/api/db/list")
def db_list() -> dict:
    """
    List DB files, current session, and (when a DB is active) the operations + Graphviz
    steps kept in memory so the SPA can rehydrate after a full page reload.
    """
    with _state_lock:
        active = _active_db_name
        ops = list(_active_ops)
        steps = list(_active_steps)

    out: dict[str, object] = {"dbs": _list_db_names(), "active_db": active}

    if active is None:
        return out

    # Rare: active DB but steps lost — rebuild step 0 from the DB file.
    if not steps:
        p = _db_path_for(active)
        with PersistentMPT(str(p), create_if_missing=False) as pmpt:
            snap = pmpt.trie.snapshot()
            step0 = {
                "label": f"0 - loaded DB ({active})",
                "state_root_hex": pmpt.state_root().hex(),
                "dot": trie_to_dot(snap, title=f"0 - loaded DB ({active})"),
            }
        with _state_lock:
            _active_ops.clear()
            _active_steps.clear()
            _active_steps.append(step0)
        ops = []
        steps = [step0]

    out["operations"] = [o.model_dump() for o in ops]
    out["steps"] = steps
    return out


@app.post("/api/db/load")
def db_load(body: DbLoadRequest) -> dict:
    """Load an existing DB under ./db; subsequent operations are committed to it."""
    p = _db_path_for(body.db_name)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"DB not found: {body.db_name}")

    with PersistentMPT(str(p), create_if_missing=False) as pmpt:
        # Initialize step 0 from current DB head.
        snap = pmpt.trie.snapshot()
        sr_hex = pmpt.state_root().hex()
        step0 = {
            "label": f"0 - loaded DB ({body.db_name})",
            "state_root_hex": sr_hex,
            "dot": trie_to_dot(snap, title=f"0 - loaded DB ({body.db_name})"),
        }

    with _state_lock:
        global _active_db_name, _active_ops, _active_steps
        _active_db_name = body.db_name
        _active_ops = []
        _active_steps = [step0]
    return {"active_db": body.db_name, "steps": [step0]}


@app.post("/api/db/unload")
def db_unload() -> dict:
    """Return to stateless in-memory replay mode."""
    with _state_lock:
        global _active_db_name, _active_ops, _active_steps
        _active_db_name = None
        _active_ops = []
        _active_steps = []
    return {"active_db": None}


@app.get("/api/db/unload")
def db_unload_get() -> dict:
    """Compatibility: allow GET to unload DB (same as POST)."""
    return db_unload()


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


_WEB_DIST = _ROOT / "web" / "dist"
if _WEB_DIST.is_dir():
    app.mount(
        "/",
        StaticFiles(directory=str(_WEB_DIST), html=True),
        name="frontend",
    )
