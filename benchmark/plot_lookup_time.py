#!/usr/bin/env python3
"""
Sweep dataset size ``n``, measure mean **value lookup** time (same random keys).

**MPT:** ``MerklePatriciaTrie.lookup(key)`` — walk the trie (path length ~ key hash depth).

**Plain:** ``PlainBinaryMerkleTree.lookup_without_leaf_index(key)`` — scan the ordered
real-leaf preimage list until ``key`` matches (**no** ``leaf_index`` / hash map). This is
O(n) per query and reflects “Merkle root only + linear leaf list,” not indexed retrieval.

Requires matplotlib (``pip install -e ".[dev]"`` or ``pip install matplotlib``).

From repository root::

    python benchmark/plot_lookup_time.py
    python benchmark/plot_lookup_time.py --n-max 1024 --num-lookups 8000 --output benchmark/lookup_time.png
"""

from __future__ import annotations

import argparse
import random
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


def _mean_lookup_seconds(
    pairs: list[tuple[bytes, bytes]],
    keys: list[bytes],
    num_lookups: int,
    lookup_seed: int,
) -> tuple[float, float]:
    """Return (mean seconds per MPT lookup, mean seconds per plain lookup)."""
    trie = MerklePatriciaTrie()
    for k, v in pairs:
        trie.insert(k, v)
    mt = PlainBinaryMerkleTree(pairs)

    rng = random.Random(lookup_seed)
    n = len(keys)
    lookup_keys = [keys[rng.randrange(0, n)] for _ in range(num_lookups)]

    t0 = perf_counter()
    for k in lookup_keys:
        _ = trie.lookup(k)
    mpt_dt = perf_counter() - t0

    t0 = perf_counter()
    for k in lookup_keys:
        _ = mt.lookup_without_leaf_index(k)
    plain_dt = perf_counter() - t0

    return mpt_dt / num_lookups, plain_dt / num_lookups


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
        default=1024,
        help="largest key count (default 1024; plain scan is O(n) per lookup)",
    )
    p.add_argument(
        "--n-values",
        type=str,
        default="",
        help="comma-separated n values (overrides n-min/n-max sweep if set)",
    )
    p.add_argument("--seed", type=int, default=0, help="RNG seed for synthetic keys (default 0)")
    p.add_argument(
        "--lookup-seed",
        type=int,
        default=42,
        help="RNG seed for which keys to look up (default 42)",
    )
    p.add_argument(
        "--num-lookups",
        type=int,
        default=12_000,
        help="number of sampled lookups per n per repeat (default 12000; lower if n is large)",
    )
    p.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="repeat measurement and take mean (default 3; use 1 for fastest run)",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=_ROOT / "benchmark" / "lookup_time.png",
        help="output PNG path",
    )
    p.add_argument("--dpi", type=int, default=150, help="figure DPI (default 150)")
    args = p.parse_args()

    if args.repeats < 1:
        raise SystemExit("--repeats must be >= 1")
    if args.num_lookups < 1:
        raise SystemExit("--num-lookups must be >= 1")

    if args.n_values.strip():
        ns = sorted({int(x.strip()) for x in args.n_values.split(",") if x.strip()})
        if any(n < 1 for n in ns):
            raise SystemExit("all n values must be >= 1")
    else:
        if args.n_min < 1 or args.n_max < args.n_min:
            raise SystemExit("need 1 <= n-min <= n-max")
        ns = _default_n_values(args.n_min, args.n_max)

    mpt_us: list[float] = []
    plain_us: list[float] = []

    for n in ns:
        pairs = synthetic_key_value_pairs(n, args.seed)
        keys = [k for k, _ in pairs]
        mpt_series: list[float] = []
        plain_series: list[float] = []
        for r in range(args.repeats):
            m_s, p_s = _mean_lookup_seconds(
                pairs,
                keys,
                args.num_lookups,
                args.lookup_seed + r * 1_000_003,
            )
            mpt_series.append(m_s * 1e6)
            plain_series.append(p_s * 1e6)
        mpt_us.append(statistics.mean(mpt_series))
        plain_us.append(statistics.mean(plain_series))

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(ns, mpt_us, "o-", linewidth=2, markersize=6, label="MPT lookup")
    ax.plot(ns, plain_us, "s-", linewidth=2, markersize=6, label="Plain (linear leaf scan)")
    ax.set_xlabel("Number of keys (n)")
    ax.set_ylabel("Mean lookup time (µs)")
    ax.set_title(
        f"Value lookup latency vs dataset size ({args.num_lookups} random keys/repeat, lower is better)\n"
        "MPT: trie walk; plain: scan leaf preimage list"
    )
    ax.legend(loc="upper left")
    ax.set_xscale("log", base=2)
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=args.dpi)
    plt.close(fig)
    print(f"Wrote {args.output.resolve()}")
    print(f"  n values: {ns}  seed={args.seed}  repeats={args.repeats}  num_lookups={args.num_lookups}")


if __name__ == "__main__":
    main()
