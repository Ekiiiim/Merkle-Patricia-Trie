#!/usr/bin/env python3
"""HTTP API for the interactive MPT web demo. Run: uvicorn api_server:app --reload"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mpt import MerklePatriciaTrie, trie_to_dot, verify_inclusion, verify_inclusion_trace

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
    """Replay operations from an empty trie; return Graphviz DOT per step."""
    t = MerklePatriciaTrie()
    steps: list[dict] = [
        {
            "label": "0 — empty trie",
            "state_root_hex": t.state_root().hex(),
            "dot": trie_to_dot(t.snapshot(), title="0 — empty trie"),
        }
    ]
    for idx, o in enumerate(body.operations):
        if o.op == "insert":
            if o.value is None:
                raise HTTPException(status_code=400, detail="insert requires value")
            t.insert(o.key.encode("utf-8"), o.value.encode("utf-8"))
            label = f"{idx + 1} — insert({o.key} → {o.value})"
        else:
            if not t.delete(o.key.encode("utf-8")):
                raise HTTPException(
                    status_code=400,
                    detail=f"delete: key not found ({o.key!r})",
                )
            label = f"{idx + 1} — delete({o.key})"
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
    }


@app.post("/api/verify-demo")
def verify_demo(body: VerifyDemoRequest) -> dict:
    """
    After replaying ``operations``, build an inclusion proof for ``prove_key`` and
    return step-by-step verification (plus raw proof RLP hex blobs).
    """
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
    }


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
