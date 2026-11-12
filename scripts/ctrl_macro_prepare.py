"""Freeze a fresh, unsealed CTRL case inventory from public metadata only."""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

STUDY = "ctrl-prospective-20261112-736c"
FAMILIES = ("text_sufficient", "text_image_complementary", "preparation_required")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def rank(*parts):
    return sha(":".join((STUDY, *parts)).encode())


def load(path):
    return json.loads(path.read_bytes())


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--material-root", required=True, type=Path)
    parser.add_argument("--old-plan", required=True, type=Path)
    parser.add_argument("--new-code", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--fit-per-field", type=int, default=12)
    parser.add_argument("--calibration-per-field", type=int, default=9)
    parser.add_argument("--evaluation-per-field", type=int, default=8)
    args = parser.parse_args()
    root = args.material_root
    catalog_path = root / "pilot-catalog.json"
    registry_path = root / "source-registry.json"
    registry = {s["source_id"]: s for s in load(registry_path)["sources"]}
    cases = load(catalog_path)["cases"]
    # Filter roles before public packet I/O. Do not read reference bodies.
    eligible = [
        c
        for c in cases
        if c["role"] in {"train", "development"} and c["task_family"] in FAMILIES
    ]
    grouped = defaultdict(list)
    for case in eligible:
        if registry[case["source_id"]]["allowed_split"] != case["role"]:
            raise ValueError("Catalog role differs from source registry")
        grouped[(case["role"], case["source_id"])].append(case)
    inventory = []
    for (role, source), group in sorted(grouped.items()):
        episodes = sorted(
            {c["episode_group"] for c in group}, key=lambda x: rank("episode", x)
        )
        episode = episodes[0]
        selected = sorted(
            [c for c in group if c["episode_group"] == episode],
            key=lambda c: FAMILIES.index(c["task_family"]),
        )
        if {c["task_family"] for c in selected} != set(FAMILIES) or len(
            selected
        ) != len(FAMILIES):
            raise ValueError("Canonical image lacks complete eligible family set")
        fields = set()
        packet_pins = []
        for case in selected:
            packet_path = root / case["packet"]["path"]
            if packet_path.is_symlink() or not packet_path.is_file():
                raise ValueError("Packet must be regular")
            raw = packet_path.read_bytes()
            if (
                sha(raw) != case["packet"]["sha256"]
                or len(raw) != case["packet"]["bytes"]
            ):
                raise ValueError("Packet differs from catalog")
            packet = json.loads(raw)
            if packet["initial_delivery"] != {"text": None, "image": None}:
                raise ValueError("Committed output is not a complete macro opportunity")
            prompt = packet["prompt"].lower()
            field = (
                "total"
                if "total amount" in prompt
                else "date"
                if "date" in prompt
                else None
            )
            if field is None:
                raise ValueError("Unknown public requested field")
            fields.add(field)
            packet_pins.append(
                {"path": str(packet_path), "bytes": len(raw), "sha256": sha(raw)}
            )
        if len(fields) != 1:
            raise ValueError("Requested field differs among canonical image families")
        inventory.append(
            {
                "role": role,
                "source_id": source,
                "episode_group": episode,
                "field": next(iter(fields)),
                "cases": selected,
                "source_registry_evidence_sha256": registry[source][
                    "source_evidence_sha256"
                ],
                "public_packet_pins": packet_pins,
            }
        )
    chosen = {"train": [], "calibration": [], "evaluation": []}
    available = {}
    for field in ("date", "total"):
        train = sorted(
            [v for v in inventory if v["role"] == "train" and v["field"] == field],
            key=lambda v: rank("source", v["source_id"]),
        )
        development = sorted(
            [
                v
                for v in inventory
                if v["role"] == "development" and v["field"] == field
            ],
            key=lambda v: rank("source", v["source_id"]),
        )
        available[field] = {
            "train_sources": len(train),
            "development_sources": len(development),
        }
        nf, nc, ne = (
            args.fit_per_field,
            args.calibration_per_field,
            args.evaluation_per_field,
        )
        if len(train) < nf + nc or len(development) < ne:
            raise ValueError(
                f"Insufficient unsealed field sources: {field}: {available[field]}"
            )
        chosen["train"].extend(train[:nf])
        chosen["calibration"].extend(train[nf : nf + nc])
        chosen["evaluation"].extend(development[:ne])
    all_sources = [s["source_id"] for split in chosen.values() for s in split]
    if len(all_sources) != len(set(all_sources)):
        raise ValueError("Source partition overlap")
    old = load(args.old_plan)
    plan = {**old, "config": dict(old["config"]), "profile": dict(old["profile"])}
    config = plan["config"]
    old_code = Path(config["repository_root"])
    config["repository_root"] = str(args.new_code)
    config["scripts_root"] = str(args.new_code / "scripts")
    config["runtime_roots"] = [
        str(args.new_code) if Path(p) == old_code else p
        for p in config["runtime_roots"]
    ]
    plan[
        "source_pins"
    ] = []  # Exact implementation pinning belongs to the driver's freeze.
    plan["source_splits"] = {
        k: [s["source_id"] for s in chosen[k]] for k in ("train", "calibration")
    }
    plan["source_splits"]["future"] = []
    ledger_path = root / "public-source-exposure-20261107-v3.json"
    ledger = load(ledger_path)
    excluded = set()
    for key in (
        "quarantined_source_groups",
        "quarantined_confirmation_source_groups",
        "excluded_pilot_new_source_groups",
    ):
        value = ledger.get(key, [])
        if isinstance(value, list):
            excluded.update(s for s in value if isinstance(s, str))
    plan["excluded_sources"] = sorted(excluded)
    if set(all_sources) & excluded:
        raise ValueError("Selected source is quarantined")
    plan["profile"].update(
        study_id=STUDY,
        original_operation_id=STUDY,
        fit_id="fresh-control-collection",
        fit_run_id=STUDY,
        arm="fresh_matched_macro_collection",
        retry_of=None,
    )
    pairs, evaluation = [], []
    for split in ("train", "calibration"):
        for item in chosen[split]:
            for case in item["cases"]:
                index = len(pairs)
                pairs.append(
                    {
                        "pair_id": f"p{index:04d}",
                        "split": split,
                        "case": case,
                        "read_condition": "original",
                        "seed": 104729 + index,
                    }
                )
    for item in chosen["evaluation"]:
        for case in item["cases"]:
            if case["task_family"] != "preparation_required":
                continue
            evaluation.append(
                {
                    "source_id": item["source_id"],
                    "case_id": case["id"],
                    "case": case,
                    "read_condition": "original",
                    "seed": 130363 + len(evaluation),
                }
            )
    plan["pairs"] = pairs
    image_hashes = {}
    for split, items in chosen.items():
        for item in items:
            source_metadata_path = (
                root / "private/sources" / (item["source_id"] + ".json")
            )
            source_metadata_raw = source_metadata_path.read_bytes()
            if sha(source_metadata_raw) != item["source_registry_evidence_sha256"]:
                raise ValueError("Source role metadata differs from registry")
            source_metadata = json.loads(source_metadata_raw)
            if source_metadata["experiment_role"] != item["role"]:
                raise ValueError("Source metadata role differs")
            canonical = [
                s["canonical"]
                for s in source_metadata["canonical_sources"]
                if s["episode_group"] == item["episode_group"]
            ]
            if len(canonical) != 1:
                raise ValueError("Unique canonical image metadata required")
            image = root / "private/images" / (item["episode_group"] + ".bin")
            if image.is_symlink() or not image.is_file():
                raise ValueError("Registered source image unavailable")
            image_sha = sha(image.read_bytes())
            if canonical[0] != {
                "path": str(image.relative_to(root)),
                "bytes": image.stat().st_size,
                "sha256": image_sha,
            }:
                raise ValueError("Canonical source image differs from role metadata")
            if (
                image_sha in image_hashes
                and image_hashes[image_sha] != item["source_id"]
            ):
                raise ValueError("Physical source image aliases cross source groups")
            image_hashes[image_sha] = item["source_id"]
            item["source_sha256"] = image_sha
            item["source_image_pin"] = {
                "path": str(image),
                "bytes": image.stat().st_size,
                "sha256": image_sha,
            }
    source_hashes = {
        v["source_id"]: v["source_sha256"] for items in chosen.values() for v in items
    }
    for record in pairs:
        record["case"]["source_sha256"] = source_hashes[record["case"]["source_id"]]
    for record in evaluation:
        record["case"]["source_sha256"] = source_hashes[record["source_id"]]
    result = {
        "schema": "ctrl.fresh-experiment-input.v1",
        "collection_plan": plan,
        "evaluation_cases": evaluation,
        "read_seconds_bound": 10.0,
        "finalizer_seconds_reserve": 5.0,
    }
    report = {
        "schema": "ctrl.material-preparation.v1",
        "study_id": STUDY,
        "actor_launched": False,
        "private_references_opened": False,
        "future_or_sealed_packet_opened": False,
        "source_alias_full_image_check": "PASSED_SELECTED_FULL_IMAGE_BYTES",
        "source_pins_frozen": False,
        "available_by_public_field": available,
        "selected_sources": {k: len(v) for k, v in chosen.items()},
        "planned_collection_pairs": len(pairs),
        "planned_collection_branches": 2 * len(pairs),
        "evaluation_contexts": len(evaluation),
        "eligible_families": FAMILIES,
        "selection": "SHA256(study:source:source_id), canonical image SHA256(study:episode:episode_group); public prompt field",
        "input_metadata_pins": [
            {"path": str(p), "sha256": sha(p.read_bytes()), "bytes": p.stat().st_size}
            for p in (catalog_path, registry_path, ledger_path, args.old_plan)
        ],
        "limits": [
            "Registered development sources are already exposed research material, not fresh confirmation.",
            "Calibration sources are disjoint for fresh control data; common content weights may have historical exposure.",
            "Original V4 is not replayed; its unknown state is unchanged.",
            "Exact code/evaluator/isolation pins remain pending; source image hashes are computed from canonical episode .bin files per register.py.",
        ],
    }
    args.output.mkdir(parents=True, exist_ok=False)
    write(args.output / "INPUT_PREPARED.json", result)
    write(
        args.output / "SOURCE_INVENTORY.json",
        [dict(item, split=split) for split, items in chosen.items() for item in items],
    )
    write(args.output / "PREPARATION_REPORT.json", report)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
