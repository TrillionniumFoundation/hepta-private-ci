"""Join both public frozen-Encoder artifacts into a bounded research handoff.

This checks self-consistency, NOT publisher attestations, model accuracy, or
production authorization. Requires both original V8 local model directories.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile

from public_stem_handoff_v9 import _json, handoff
from public_stem_material_v8 import AdmissionError, CATALOG, canonical, sha, strict_json
from public_stem_pair_gate_v9 import check_pair

SCHEMA = "hepta.public-stem-material-pair-handoff.v10"


def collect(roots: dict[str, Path]) -> tuple[dict, dict[str, dict]]:
    if type(roots) is not dict or set(roots) != set(CATALOG):
        raise AdmissionError("both exact public Stem output directories are required")
    directories, entries, receipts = set(), {}, {}
    for name in sorted(CATALOG):
        root = roots[name]
        if not isinstance(root, Path) or root.is_symlink() or not root.is_dir():
            raise AdmissionError("missing or linked Stem evidence directory")
        actual = root.resolve(strict=True)
        if actual in directories:
            raise AdmissionError("candidates cannot alias the same material directory")
        directories.add(actual)
        plan = strict_json(root / "pinned-plan.json")
        if plan["candidate"] != name:
            raise AdmissionError("wrong candidate in public material plan")
        material = _json(root / "material-receipt.json")
        physical = _json(root / "physical-receipt.json")
        profile, linkage = handoff(plan, material, physical, root / "model")
        if profile["candidate"] != name or linkage["candidate"] != name:
            raise AdmissionError("research handoff candidate drift")
        entries[name] = {"profile": profile, "handoff": linkage}
        receipts[name] = physical
    paired = check_pair(receipts)
    return ({"schema": SCHEMA, "probe_input_sha256": paired["probe_input_sha256"],
             "candidate_profiles": {
                 name: {"profile_sha256": sha(canonical(entries[name]["profile"])),
                        "handoff_sha256": sha(canonical(entries[name]["handoff"]))}
                 for name in sorted(entries)},
             "two_material_directories_rehashed": True,
             "research_pair_self_consistent": True,
             "paired_physical_execution_independently_attested": False,
             "no_change_baseline_executed": False,
             "matched_training_completed": False,
             "independent_future_efficacy_verified": False,
             "ndu_promotion_authorized": False,
             "production_accepted": False, "authority": "DENY_ALL"}, entries)


def publish(output: Path, summary: dict, entries: dict[str, dict]) -> None:
    if (output.exists() or output.is_symlink() or not output.parent.is_dir()
            or output.parent.is_symlink()):
        raise AdmissionError("new output directory with safe parent required")
    with tempfile.TemporaryDirectory(prefix=".hepta-stem-v10-", dir=output.parent) as tmp:
        stage = Path(tmp)
        blobs = {"pair-summary.json": canonical(summary)}
        for name in sorted(CATALOG):
            blobs[f"{name}.profile.json"] = canonical(entries[name]["profile"])
            blobs[f"{name}.handoff.json"] = canonical(entries[name]["handoff"])
        for filename, raw in blobs.items():
            with (stage / filename).open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        os.rename(stage, output)
        parent = os.open(output.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mmbert-root", required=True, type=Path)
    parser.add_argument("--granite-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        summary, entries = collect({"mmbert-small": args.mmbert_root,
                                    "granite-97m-r2": args.granite_root})
        publish(args.output, summary, entries)
    except (AdmissionError, OSError, ValueError, TypeError, KeyError) as error:
        print("V10 pair handoff rejected: " + str(error)[:256], file=sys.stderr)
        return 2
    print("PUBLIC_STEM_V10_BOTH_MATERIALS_REHASHED_NO_EFFICACY_OR_AUTHORITY " + str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
