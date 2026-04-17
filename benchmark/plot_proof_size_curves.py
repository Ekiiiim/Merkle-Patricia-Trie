#!/usr/bin/env python3
"""
Sweep ``n`` (number of keys), measure per-key inclusion proof sizes, plot mean (and min–max band).

Requires matplotlib (``pip install -e ".[dev]"`` or ``pip install matplotlib``).

From repository root::

    python benchmark/plot_proof_size_curves.py
    python benchmark/plot_proof_size_curves.py --n-max 2048 --output figures/proof_sizes.png
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_BENCH = Path(__file__).resolve().parent
for _p in (_ROOT, _BENCH):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from run_proof_size import collect_proof_sizes


def _default_n_values(n_min: int, n_max: int) -> list[int]:
    """Geometric-ish sweep: powers of two from n_min through n_max, plus n_max if not already included."""
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


def main() -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError as e:  # pragma: no cover
        raise SystemExit(
            "matplotlib is required. Install with: pip install -e \".[dev]\"  (or pip install matplotlib)"
        ) from e

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--n-min", type=int, default=4, help="smallest key count (default 4)")
    p.add_argument("--n-max", type=int, default=1024, help="largest key count (default 1024)")
    p.add_argument(
        "--n-values",
        type=str,
        default="",
        help="comma-separated n values (overrides n-min/n-max sweep if set)",
    )
    p.add_argument("--seed", type=int, default=0, help="RNG seed for synthetic keys (default 0)")
    p.add_argument(
        "--output",
        type=Path,
        default=_ROOT / "benchmark" / "proof_size_curves.png",
        help="output PNG path",
    )
    p.add_argument("--dpi", type=int, default=150, help="figure DPI (default 150)")
    args = p.parse_args()

    if args.n_values.strip():
        ns = sorted({int(x.strip()) for x in args.n_values.split(",") if x.strip()})
        if any(n < 1 for n in ns):
            raise SystemExit("all n values must be >= 1")
    else:
        if args.n_min < 1 or args.n_max < args.n_min:
            raise SystemExit("need 1 <= n-min <= n-max")
        ns = _default_n_values(args.n_min, args.n_max)

    mpt_mean: list[float] = []
    plain_mean: list[float] = []
    mpt_lo: list[float] = []
    mpt_hi: list[float] = []
    plain_lo: list[float] = []
    plain_hi: list[float] = []

    for n in ns:
        mpt_sizes, plain_sizes, _pr, _mr = collect_proof_sizes(n, args.seed)
        mpt_mean.append(statistics.mean(mpt_sizes))
        plain_mean.append(statistics.mean(plain_sizes))
        mpt_lo.append(float(min(mpt_sizes)))
        mpt_hi.append(float(max(mpt_sizes)))
        plain_lo.append(float(min(plain_sizes)))
        plain_hi.append(float(max(plain_sizes)))

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.fill_between(ns, mpt_lo, mpt_hi, alpha=0.2, label="MPT min–max")
    ax.fill_between(ns, plain_lo, plain_hi, alpha=0.2, label="Plain min–max")
    ax.plot(ns, mpt_mean, "o-", linewidth=2, markersize=6, label="MPT mean")
    ax.plot(ns, plain_mean, "s-", linewidth=2, markersize=6, label="Plain mean")
    ax.set_xlabel("Number of keys (n)")
    ax.set_ylabel("Proof payload size (bytes)")
    ax.set_title(
        "Inclusion proof payload vs number of keys (lower is better)\n"
        "MPT: Σ |RLP(node)| on root→leaf path; "
        "plain: leaf hash + 32 B siblings"
    )
    ax.legend(loc="upper left")
    ax.set_xscale("log", base=2)
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=args.dpi)
    plt.close(fig)
    print(f"Wrote {args.output.resolve()}")
    print(f"  n values: {ns}")


if __name__ == "__main__":
    main()
