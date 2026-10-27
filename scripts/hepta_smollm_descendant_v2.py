#!/usr/bin/env python3
"""Execute three six-arm candidate descendants without installing them.

The actual ordinary CURRENT snapshot remains the incumbent. Candidate ordinals
2, 3 and 4 are diagnostic lineage only, never registry-admitted generations.
Every round preserves the original five arms and separately reloads the actual
incumbent. Completed diagnostics still have typed installation blockers.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hepta_smollm_three_rounds_v2 as rounds


def save(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def run(args):
    config_raw = args.native_input.read_bytes()
    config = json.loads(config_raw)
    rounds.require(
        config["schema"] == "hepta-smollm-neural-native-check-v1",
        "original cold native configuration required",
    )
    for name in ("chain", "materials", "parent"):
        rounds.require(
            Path(config[name]).is_absolute(), "absolute native material path"
        )
    readback_raw = args.ordinary_readback.read_bytes()
    readback = json.loads(readback_raw)
    rounds.require(
        readback["withdrawal_refused"] is False
        and readback["current_before"] == readback["current_after"]
        and all(
            readback["current"][key] == readback["current_before"][key]
            for key in ("head_digest", "record_count", "file_digest")
        ),
        "an actual unwithdrawn ordinary session with unchanged CURRENT is required",
    )
    args.output.mkdir(mode=0o700, parents=False, exist_ok=False)
    incumbent = Path(config["parent"])
    parent = incumbent
    campaign = dict(
        schema="hepta-controlled-six-arm-descendant-campaign-v2",
        native_input_sha256=hashlib.sha256(config_raw).hexdigest(),
        ordinary_readback_sha256=hashlib.sha256(readback_raw).hexdigest(),
        runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        actual_current=readback["current"],
        actual_current_parent=readback["parent"],
        current_snapshot_only=True,
        candidate_ordinals_are_registry_generations=False,
        completed_rounds=0,
        rounds=[],
        installed_children=0,
        product_qualification=False,
        three_installed_upgrades_proven=False,
        independent_future_quality=False,
        status="running",
    )
    report = args.output / "campaign.json"
    save(report, campaign)
    try:
        for number in range(1, 4):
            parent_raw = parent.read_bytes()
            descriptor = json.loads(parent_raw)
            rounds.require(
                descriptor["generation"] == number, "candidate lineage ordinal"
            )
            if number > 1:
                rounds.require(
                    descriptor == campaign["rounds"][-1]["candidate_parent_material"],
                    "next training parent must be the actual preceding candidate",
                )
            result = rounds.run(
                SimpleNamespace(
                    chain=Path(config["chain"]),
                    materials=Path(config["materials"]),
                    parent=incumbent,
                    parent_sha256=config["parent_sha256"],
                    ordinary_readback=args.ordinary_readback,
                    output=args.output / f"round-{number}",
                    round=number,
                    proposal_parent=parent,
                    proposal_parent_sha256=hashlib.sha256(parent_raw).hexdigest(),
                )
            )
            rounds.require(
                result["decision"] == "diagnostic-completed-installation-blocked"
                and "MissingSystemLongitudinalEvidence" in result["blockers"]
                and (number == 1 or "ParentNotCurrent" in result["blockers"])
                and result["installed_child"] is False,
                "diagnostic must retain the original installation barriers",
            )
            campaign["rounds"].append(result)
            campaign["completed_rounds"] = number
            parent = args.output / f"round-{number}" / "candidate-parent-material.json"
            save(report, campaign)
        campaign["status"] = "diagnostic-completed-installation-blocked"
        save(report, campaign)
    except BaseException as error:
        campaign.update(
            status="execution-failed",
            error_type=type(error).__name__,
            reason=str(error)[:512],
        )
        save(report, campaign)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("native-input", "ordinary-readback", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    rounds.require(
        all(value.is_absolute() for value in vars(args).values()),
        "absolute paths required",
    )
    run(args)


if __name__ == "__main__":
    main()
