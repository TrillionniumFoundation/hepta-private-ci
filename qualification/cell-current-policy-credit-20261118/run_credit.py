"""Freeze and fit the preregistered A-only current-policy credit mechanism."""

import argparse
import json
from pathlib import Path
import re
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("freeze", "train-all_observed", "train-verified_credit", "audit"))
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--old-code-root", required=True, type=Path)
    parser.add_argument("--parent-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--code-commit")
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    old = args.old_code_root.resolve(strict=True)
    sys.path.insert(0, str(old / "scripts"))
    sys.path.insert(0, str(here))
    import current_credit as credit
    from cell_experiments import data
    from cell_experiments.coding_sft import file_hash, write_new
    artifact, output = args.artifact_root.resolve(strict=True), args.output.resolve()
    output.relative_to(artifact)
    parent = data._parse(args.parent_manifest.read_bytes())
    records = [data._parse(line) for line in (here / "prepared/records.jsonl").read_bytes().splitlines()]
    names = ("current_credit.py", "run_credit.py", "owner.py", "test_current_credit.py", "build_corpus.py",
             "README.md", "prepared/records.jsonl", "prepared/CORPUS.json")
    files = {name: file_hash(here / name) for name in names}
    if args.stage == "freeze":
        credit.require(bool(re.fullmatch(r"[0-9a-f]{40}", args.code_commit or "")),
                       "published candidate source required")
        credit.require(credit.matched.verify_manifest(parent, artifact, old) == credit.PARENT,
                       "exact previous real student required")
        credit.require(data.digest(records) == credit.CORPUS and len(records) == 6,
                       "published A-only corpus changed")
        output.mkdir(parents=True, exist_ok=False)
        write_new(output / "TRAIN_RECORDS.json", records)
        write_new(output / "PARENT_MODEL.json", parent)
        result = {"schema": "hepta.current-policy-credit-freeze.v1",
            "code_commit": args.code_commit, "created_at_ns": time.time_ns(),
            "candidate_files": files, "old_code_inventory": parent["source_inventory"],
            "old_code_commit": "992f2b3de51902448abf5743f94179bf40e11b6d",
            "parent_model_digest": credit.PARENT, "parent_parameter_sha256": credit.PARENT_PARAMETERS,
            "train_records_digest": data.digest(records), "training_settings": credit.SETTINGS,
            "payloads": {name: file_hash(output / name) for name in ("TRAIN_RECORDS.json", "PARENT_MODEL.json")},
            "modes": list(credit.MODES), "NoUpdate": credit.PARENT,
            "evaluation": {"modes": ["NoUpdate", *credit.MODES], "calls_per_task": 2,
                "max_new_tokens": 384, "context_tokens": 4096, "temperature": 0,
                "A_tasks": 6, "B_exposed_development_tasks": 6,
                "future_B2": "independent agent freezes source, licenses and gold; unseal only after both weights freeze; zero B2 training or candidate selection",
                "decision": "A-only fewer regressions without fewer recoveries or final successes versus all_observed; no B/B2 selection; research NoUpdate retained"},
            "B_or_B2_data_loaded": False, "new_sources": 0, "independent_users": 0,
            "scientific_confirmation_qualified": False, "native_adoption": False}
        write_new(output / "FREEZE.json", result)
    else:
        freeze = data._parse((output / "FREEZE.json").read_bytes())
        credit.require(files == freeze["candidate_files"] and
                       credit.SETTINGS == freeze["training_settings"], "frozen implementation changed")
        credit.require(credit.matched.source_inventory(old) == freeze["old_code_inventory"],
                       "frozen dependency implementation changed")
        for name, expected in freeze["payloads"].items():
            credit.require(file_hash(output / name) == expected, "frozen A payload changed")
        credit.require(data.digest(parent) == freeze["parent_model_digest"] and
                       data.digest(records) == freeze["train_records_digest"], "frozen input identity changed")
        if args.stage == "audit":
            result = credit.audit(output, artifact, old, here, freeze)
        else:
            mode = args.stage.removeprefix("train-")
            result = credit.train(records, parent, artifact, old, here, freeze, mode,
                                  output / "training" / mode)
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
