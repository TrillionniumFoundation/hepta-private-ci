#!/usr/bin/env python3
"""Run immutable qualification and attach a non-authoritative repair sidecar.

The qualification gates remain read-only over the exact checked-out commit. A
separate detached worktree may generate a patch proposal for operator review;
that sidecar is explicitly excluded from qualification, acceptance, activation
and release claims.
"""
from __future__ import annotations

import json
from pathlib import Path

import cognitive_read_full_evidence as qualification
from cognitive_read_source_proposal import generate_source_proposal


_original_emit = qualification.emit


def emit(root: Path, evidence: Path, candidate: str, kind: str, output: Path) -> bool:
    if kind == "source-head":
        proposal = generate_source_proposal(root, evidence, candidate)
    else:
        proposal = {
            "schema": "hepta.cognitive.read.local-source-proposal.v1",
            "kind": "not-applicable-to-merge-candidate",
            "qualification": False,
            "status": "not-generated",
            "activation": False,
            "production_implementation": False,
            "independent_acceptance": False,
            "release": False,
        }

    passed = _original_emit(root, evidence, candidate, kind, output)
    receipt = json.loads(output.read_text())
    receipt["local_source_proposal"] = proposal
    receipt["claim_boundary"] = (
        receipt.get("claim_boundary", "")
        + " Any source-proposal/ entry is a mutable local repair suggestion only "
          "and is never qualification, acceptance, activation, promotion or release evidence."
    ).strip()
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return passed


def main() -> None:
    # Older candidate sources install the full-suite overrides at import time.
    # Newer repaired sources expose an explicit installer so unit-test imports
    # remain isolated. Support both without allowing the wrapper to fall back to
    # the smaller base suite after a repair proposal is applied.
    install = getattr(qualification, "install_base_overrides", None)
    if install is not None:
        install()
    qualification.base.emit = emit
    qualification.base.main()


if __name__ == "__main__":
    main()
