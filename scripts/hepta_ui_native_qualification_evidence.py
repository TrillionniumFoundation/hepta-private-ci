#!/usr/bin/env python3
"""Bind exact ui.native evidence and emit per-subject SBOM/provenance."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hepta_ui_native_evidence as evidence
import hepta_ui_native_supply_chain as supply_chain

CURRENT_WORKFLOW = ".github/workflows/ui-native-qualification.yml"
COMPILE_NEGATIVE = "compile_negative"

evidence.WORKFLOW = CURRENT_WORKFLOW
if COMPILE_NEGATIVE not in evidence.REQUIRED:
    evidence.REQUIRED = (*evidence.REQUIRED, COMPILE_NEGATIVE)

_original_seal = evidence.seal


def seal_with_supply_chain(root: Path, args):
    receipt = _original_seal(root, args)
    platform = {"Linux": "linux", "macOS": "macos", "Windows": "windows"}.get(
        args.runner_os
    )
    if platform is None:
        raise ValueError("unsupported platform for supply-chain evidence")
    state = json.loads(
        (root / "apps/hepta-native/CANDIDATE.json").read_text(encoding="utf-8")
    )
    current = evidence.subject(root)
    output = args.out.parent / "supply-chain"
    manifest = supply_chain.generate(
        root=root,
        candidate=args.candidate,
        base=args.base,
        implementation=state["implementationSourceSha"],
        source_sha=current["sourceSha"],
        source_tree=current["sourceTreeSha"],
        kind=args.kind,
        platform=platform,
        package_receipt_path=args.packages / "package-receipt.json",
        out_dir=output,
        timestamp=receipt["timestamp"],
    )
    manifest_path = output / "supply-chain.json"
    receipt["supplyChain"] = {
        "manifestSha256": evidence.sha256(manifest_path.read_bytes()),
        "sbomSha256": manifest["sbom"]["sha256"],
        "provenanceSha256": manifest["provenance"]["sha256"],
        "productionSigningObserved": False,
        "physicalHostAcceptance": False,
        "releaseAuthorized": False,
    }
    return receipt


evidence.seal = seal_with_supply_chain

if __name__ == "__main__":
    raise SystemExit(evidence.main())
