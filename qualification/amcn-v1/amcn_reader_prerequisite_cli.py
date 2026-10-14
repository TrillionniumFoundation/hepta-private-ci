"""AMCN read-only Reader gate advisory over externally pinned immutable receipts.

No key creation, Reader invocation, training, publication or production admission.
The caller must provide pins independently of the files being checked.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from amcn_core import canonical, require
from amcn_reader_prerequisite import reader_prerequisite


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--reader-gate", type=Path)
    parser.add_argument("--reader-gate-sha256")
    parser.add_argument("--trust-manifest", type=Path)
    parser.add_argument("--trust-manifest-sha256")
    parser.add_argument("--authorized-roster", type=Path)
    parser.add_argument("--authorized-roster-sha256")
    parser.add_argument("--expected-model-binding-sha256")
    parser.add_argument("--original-answers-sha256")
    parser.add_argument("--original-judgments-sha256")
    args = parser.parse_args(argv)

    inputs = (args.reader_gate, args.reader_gate_sha256, args.trust_manifest,
              args.trust_manifest_sha256, args.authorized_roster,
              args.authorized_roster_sha256)
    require(all(value is None for value in inputs) or all(value is not None for value in inputs),
            "all three independently pinned inputs must be supplied together")
    gate = trust = roster = None
    if all(x is not None for x in inputs):
        # The previously installed Reader reviewer owner handles exact SHA,
        # symlinks, duplicates, JSON numeric values and size ceilings.
        from scripts.memory_cell.system2_reader_controls import load_pinned_json
        gate = load_pinned_json(args.reader_gate, args.reader_gate_sha256)
        trust = load_pinned_json(args.trust_manifest, args.trust_manifest_sha256)
        roster = load_pinned_json(args.authorized_roster, args.authorized_roster_sha256)
    result = reader_prerequisite(
        gate, trust, roster,
        externally_pinned_trust_sha256=args.trust_manifest_sha256,
        externally_pinned_roster_sha256=args.authorized_roster_sha256,
        expected_model_binding_sha256=args.expected_model_binding_sha256,
        original_answers_sha256=args.original_answers_sha256,
        original_judgments_sha256=args.original_judgments_sha256,
    )
    require(not args.output.exists() and not args.output.is_symlink(),
            "never overwrite existing original admission receipt")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as out:
        out.write(canonical(result) + b"\n")
        out.flush()
        import os
        os.fsync(out.fileno())
    return result


if __name__ == "__main__":
    result = main()
    print(result["metrics"]["disposition"])
