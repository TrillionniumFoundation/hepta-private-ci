#!/usr/bin/env python3
"""Emit V2 evidence only after the complete exact-candidate gate inventory exists."""
from __future__ import annotations

import argparse
from pathlib import Path

from cognitive_read_evidence import emit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--kind", choices=("source-head", "merge-candidate"), required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    passed = emit(root, (root / args.evidence_dir).resolve(), args.expected_sha,
                  args.kind, (root / args.output).resolve())
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
