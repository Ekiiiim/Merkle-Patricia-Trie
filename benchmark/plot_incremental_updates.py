#!/usr/bin/env python3
"""
Incremental insert benchmark: MPT vs a naive plain Merkle baseline.

**MPT curve:** wall time to insert ``n`` keys from scratch (one ``insert`` per key).

**Plain curve:** wall time to insert ``n`` keys from scratch using
``PlainBinaryMerkleTree.insert`` (incremental O(log n) updates, occasional rebuild when capacity grows).

Requires matplotlib (``pip install -e ".[dev]"`` or ``pip install matplotlib``).

From repository root::

    python benchmark/plot_incremental_updates.py
    python benchmark/plot_incremental_updates.py --n-max 512 --output benchmark/incremental_updates.png
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path
from time import perf_counter

_ROOT = Path(__file__).resolve().parents[1]
_BENCH = Path(__file__).resolve().parent
for _p in (_ROOT, _BENCH):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from plain_merkle import PlainBinaryMerkleTree
from mpt.trie import MerklePatriciaTrie
from run_proof_size import synthetic_key_value_pairs


def _default_n_values(n_min: int, n_max: int) -> list[int]:
    """Powers of two from n_min through n_max, plus n_max if not already included."""
    vals: list[int] = []
    x = n_min
    while x <= n_max:
        vals.append(x)
        if x >= n_max:
            break
        nxt = x * 2
        if nxt > n_max and x < n_max:
            vals.append(n_max)
            break
        x = nxt
    return sorted(set(vals))


def _time_mpt_n_inserts(pairs: list[tuple[bytes, bytes]]) -> float:
    t0 = perf_counter()
    trie = MerklePatriciaTrie()
    for k, v in pairs:
        trie.insert(k, v)
    return perf_counter() - t0


def _time_plain_rebuild_after_each_insert(pairs: list[tuple[bytes, bytes]]) -> float:
    """Time to insert all keys into one incrementally updated plain Merkle tree."""
    t0 = perf_counter()
    mt = PlainBinaryMerkleTree([pairs[0]])
    for k, v in pairs[1:]:
        mt.insert(k, v)
    return perf_counter() - t0


def _measure_curves(
    ns: list[int],
    pairs_all: list[tuple[bytes, bytes]],
    repeats: int,
) -> tuple[list[float], list[float]]:
    """For each n in ns, return (mean MPT seconds, mean plain seconds) over ``repeats``."""
    mpt_series: list[list[float]] = [[] for _ in ns]
    plain_series: list[list[float]] = [[] for _ in ns]

    for _ in range(repeats):
        for j, n in enumerate(ns):
            prefix = pairs_all[:n]
            mpt_series[j].append(_time_mpt_n_inserts(prefix))
            plain_series[j].append(_time_plain_rebuild_after_each_insert(prefix))

    mpt_means = [statistics.mean(xs) for xs in mpt_series]
    plain_means = [statistics.mean(xs) for xs in plain_series]
    return mpt_means, plain_means


def main() -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError as e:  # pragma: no cover
        raise SystemExit(
            "matplotlib is required. Install with: pip install -e \".[dev]\"  (or pip install matplotlib)"
        ) from e

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--n-min", type=int, default=4, help="smallest key count (default 4)")
    p.add_argument(
        "--n-max",
        type=int,
        default=256,
        help="largest key count (default 256; plain baseline is O(n) rebuilds per step)",
    )
    p.add_argument(
        "--n-values",
        type=str,
        default="",
        help="comma-separated n values (overrides n-min/n-max sweep if set)",
    )
    p.add_argument("--seed", type=int, default=0, help="RNG seed for synthetic keys (default 0)")
    p.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="repeat each measurement and take the mean (default 3; use 1 for fastest run)",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=_ROOT / "benchmark" / "incremental_updates.png",
        help="output PNG path",
    )
    p.add_argument("--dpi", type=int, default=150, help="figure DPI (default 150)")
    args = p.parse_args()

    if args.repeats < 1:
        raise SystemExit("--repeats must be >= 1")

    if args.n_values.strip():
        ns = sorted({int(x.strip()) for x in args.n_values.split(",") if x.strip()})
        if any(n < 1 for n in ns):
            raise SystemExit("all n values must be >= 1")
    else:
        if args.n_min < 1 or args.n_max < args.n_min:
            raise SystemExit("need 1 <= n-min <= n-max")
        ns = _default_n_values(args.n_min, args.n_max)

    n_cap = max(ns)
    pairs_all = synthetic_key_value_pairs(n_cap, args.seed)

    mpt_t, plain_t = _measure_curves(ns, pairs_all, args.repeats)

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(ns, mpt_t, "o-", linewidth=2, markersize=6, label="MPT")
    ax.plot(ns, plain_t, "s-", linewidth=2, markersize=6, label="Plain")
    ax.set_xlabel("Number of keys inserted")
    ax.set_ylabel("Time cost (seconds)")
    ax.set_title(
        "Incremental updates: total time to reach n keys (lower is better)\n"
        "Plain: incremental insert() updates"
    )
    ax.legend(loc="upper left")
    ax.set_xscale("log", base=2)
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=args.dpi)
    plt.close(fig)
    print(f"Wrote {args.output.resolve()}")
    print(f"  n values: {ns}  seed={args.seed}  repeats={args.repeats}")


if __name__ == "__main__":
    main()
