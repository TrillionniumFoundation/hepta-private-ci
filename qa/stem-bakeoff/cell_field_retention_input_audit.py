"""Independent BFS source audit for retention v2; never opens final_labels.json."""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path

from cell_field_audit import canonical, normalize, sha
from prepare_news_cohorts import COUNTS, _read_archive, select_rows


ROLE_ORDER = ("old_train", "old_probe", "old_test", "current_train", "current_probe", "future_may", "future_june")
PINNED_PREVIOUS_SEAL = "68c5b247fa399901fea32076e11ed0a4a5149cbd52ba3690ff1bdc09adf66549"
PINNED_PREVIOUS_SOURCES = {"sha256": "d3d8c203c2fd88966fa937d0e0b5cf2826399f558a26dc1e256e47ab479a0482", "bytes": 315623}
PINNED_PREVIOUS_RECEIPT = {"sha256": "57742ed6e70c5c33053e4092bc3f58d46f791e84ffedb2efe79fd187e2e707ea", "bytes": 4055}


def audit_inputs(data_dir, archive, previous, protocol):
    root, old_root = Path(data_dir), Path(previous)
    plan_bytes = Path(protocol).read_bytes()
    plan = json.loads(plan_bytes)
    receipt_bytes = (root / "data_receipt.json").read_bytes()
    receipt = json.loads(receipt_bytes)
    old_receipt_path = old_root / "data_receipt.json"
    if old_receipt_path.is_symlink() or (old_root / "sources.json").is_symlink():
        raise ValueError("unsafe previous-source evidence")
    old_sources = (old_root / "sources.json").read_bytes()
    if (plan["previous_sources_sha256"] != PINNED_PREVIOUS_SOURCES["sha256"]
            or plan["previous_data_receipt_sha256"] != PINNED_PREVIOUS_RECEIPT["sha256"]
            or sha(old_sources) != PINNED_PREVIOUS_SOURCES["sha256"]
            or len(old_sources) != PINNED_PREVIOUS_SOURCES["bytes"]):
        raise ValueError("previous-source bytes differ from the published experiment")
    if old_receipt_path.exists():
        old_receipt = old_receipt_path.read_bytes()
        saved = json.loads(old_receipt)
        if (sha(old_receipt) != PINNED_PREVIOUS_RECEIPT["sha256"]
                or len(old_receipt) != PINNED_PREVIOUS_RECEIPT["bytes"]
                or saved["files"]["sources.json"] != PINNED_PREVIOUS_SOURCES
                or saved["source_archive_sha256"] != plan["source_archive_sha256"]):
            raise ValueError("previous receipt differs from the published experiment")
        prior_provenance = {"mode": "original_receipt", "seal_sha256": None,
                            "original_receipt_present": True}
    else:
        seal_path = old_root / "pre_evaluation_seal.json"
        if seal_path.is_symlink():
            raise ValueError("unsafe previous-source evidence")
        old_seal = seal_path.read_bytes()
        saved = json.loads(old_seal)
        if (sha(old_seal) != PINNED_PREVIOUS_SEAL
                or saved["files"]["inputs/sources.json"] != PINNED_PREVIOUS_SOURCES
                or saved["files"]["inputs/data_receipt.json"] != PINNED_PREVIOUS_RECEIPT
                or saved.get("final_labels_opened") is not False):
            raise ValueError("previous source seal differs from the published experiment")
        prior_provenance = {"mode": "published_pre_evaluation_seal", "seal_sha256": sha(old_seal),
                            "original_receipt_present": False}
    prior_provenance.update(sources=PINNED_PREVIOUS_SOURCES, original_receipt=PINNED_PREVIOUS_RECEIPT)
    if (receipt["protocol_sha256"] != sha(plan_bytes)
            or receipt["previous_sources_sha256"] != sha(old_sources)
            or receipt["previous_data_receipt_sha256"] != PINNED_PREVIOUS_RECEIPT["sha256"]
            or receipt["previous_source_provenance"] != prior_provenance
            or receipt["salt"] != plan["source_split_salt"]):
        raise ValueError("pinned protocol or prior-exposure identity differs")
    for name, expected in receipt["files"].items():
        if name == "final_labels.json":
            continue  # Hash is verified only after the sealed evaluation phase.
        path = root / name
        if Path(name).name != name or path.is_symlink():
            raise ValueError("unsafe preparation artifact")
        payload = path.read_bytes()
        if len(payload) != expected["bytes"] or sha(payload) != expected["sha256"]:
            raise ValueError("preparation artifact identity differs: " + name)
    sources = json.loads((root / "sources.json").read_bytes())["rows"]
    predictors = json.loads((root / "predictors.json").read_bytes())["rows"]
    training = json.loads((root / "train_labels.json").read_bytes())["roles"]
    prior = {row["raw_source_id"]: row for row in json.loads(old_sources)["rows"]}
    if (len(prior) != 512 or len({row["component_id"] for row in prior.values()}) != 512
            or len(sources) != sum(plan["source_counts"].values())
            or len(sources) != len(predictors) or [s["index"] for s in sources] != list(range(len(sources)))
            or len({s["component_id"] for s in sources}) != len(sources)
            or len({s["raw_source_id"] for s in sources}) != len(sources)):
        raise ValueError("source or previous exposure census differs")
    if any(set(row) != {"source_id", "source_version", "text"} for row in predictors):
        raise ValueError("predictor contains unregistered metadata")
    if set(training) != {"old_train", "old_probe", "current_train", "current_probe"}:
        raise ValueError("unregistered training label role")
    raw = _read_archive(archive)
    legacy = {row["source_id"] for cohort in select_rows(raw, COUNTS).values() for row in cohort}
    stories, titles = defaultdict(list), defaultdict(list)
    for i, row in enumerate(raw):
        stories[row["source_group_id"]].append(i)
        titles[normalize(row["text"])].append(i)
    selected = {row["raw_source_id"]: row for row in sources}
    seen = bytearray(len(raw))
    count, verified, prior_verified = 0, 0, 0
    reasons, support, exclusion_ids = Counter(), Counter(), defaultdict(list)
    candidates, actual_labels = defaultdict(list), {}
    wanted_months = {r["month"] for r in receipt["roles"].values()}
    for start in range(len(raw)):
        if seen[start]:
            continue
        pending, members = [start], []
        seen[start] = 1
        while pending:
            index = pending.pop()
            members.append(index)
            row = raw[index]
            adjacent = stories.pop(row["source_group_id"], []) + titles.pop(normalize(row["text"]), [])
            for neighbour in adjacent:
                if not seen[neighbour]:
                    seen[neighbour] = 1
                    pending.append(neighbour)
        count += 1
        ids = sorted(raw[i]["source_id"] for i in members)
        component = "news-group:" + sha(ids)
        previous_rows = [prior[source] for source in ids if source in prior]
        for saved in previous_rows:
            if (saved["component_id"] != component or saved["component_member_count"] != len(ids)
                    or saved["component_members_sha256"] != sha(ids)):
                raise ValueError("v1 component differs from independently reconstructed graph")
            prior_verified += 1
        months = {datetime.fromtimestamp(raw[i]["timestamp_ms"] / 1000, timezone.utc).strftime("%Y-%m") for i in members}
        labels = {raw[i]["label"] for i in members}
        causes = (["cross_month"] if len(months) != 1 else []) + (["label_conflict"] if len(labels) != 1 else [])
        if legacy.intersection(ids): causes.append("legacy_cohort_component")
        if previous_rows: causes.append("v1_experiment_component")
        for reason in causes:
            reasons[reason] += 1
            exclusion_ids[reason].append(component)
        picked = [selected[source] for source in ids if source in selected]
        if picked and (causes or len(picked) != 1):
            raise ValueError("selected component leaks, conflicts or spans months")
        if causes:
            continue
        month, label = next(iter(months)), next(iter(labels))
        if month not in wanted_months:
            reasons["outside_selected_months"] += 1
            continue
        ordinary = [i for i in members if int(sha(normalize(raw[i]["publisher"]).encode())[:8], 16) % 5 != 0]
        if not ordinary:
            reasons["no_non_ood_publisher"] += 1
            continue
        rep = raw[min(ordinary, key=lambda i: (raw[i]["timestamp_ms"], raw[i]["source_id"]))]
        support[f"{month}/{label}"] += 1
        candidates[(month, label)].append((sha([receipt["salt"], component]), rep["source_id"], component))
        if not picked:
            continue
        source, index = picked[0], picked[0]["index"]
        expected_predictor = {"source_id": "uci-news:" + rep["source_id"],
                              "source_version": "sha256:" + rep["source_row_sha256"], "text": rep["text"]}
        if (predictors[index] != expected_predictor or source["raw_source_id"] != rep["source_id"]
                or source["source_id"] != expected_predictor["source_id"]
                or source["component_id"] != component or source["month"] != month
                or source["component_member_count"] != len(ids) or source["component_members_sha256"] != sha(ids)
                or source["source_row_sha256"] != rep["source_row_sha256"]
                or source["normalized_title_sha256"] != sha(normalize(rep["text"]).encode())
                or source["publisher_sha256"] != sha(normalize(rep["publisher"]).encode())
                or source["timestamp_ms"] != rep["timestamp_ms"]
                or receipt["roles"][source["role"]]["month"] != month):
            raise ValueError("source representative or predictor identity differs")
        actual_labels[index] = label
        verified += 1
    audit = receipt["audit"]
    if (verified != len(sources) or prior_verified != 512 or count != audit["raw_components"]
            or dict(reasons) != audit["excluded_components_by_reason"]
            or dict(support) != audit["eligible_components_by_month_class"]
            or {reason: sha(sorted(ids)) for reason, ids in exclusion_ids.items()} != audit["exclusion_component_ids_sha256"]):
        raise ValueError("independent graph or exclusion census differs")
    offsets = Counter()
    for role in ROLE_ORDER:
        spec = receipt["roles"][role]
        month, amount = spec["month"], spec["rows"]
        if amount != plan["source_counts"][role]:
            raise ValueError("role count differs from protocol")
        role_sources = [source for source in sources if source["role"] == role]
        chosen = []
        for label in range(4):
            key = (month, label)
            begin, end = offsets[key], offsets[key] + amount // 4
            chosen.extend(sorted(candidates[key])[begin:end])
            offsets[key] = end
        expected_ids = [source for _, source, component in sorted(
            chosen, key=lambda value: sha([receipt["salt"], role, value[2]]))]
        if (expected_ids != [source["raw_source_id"] for source in role_sources]
                or Counter(actual_labels[s["index"]] for s in role_sources) != {c: amount // 4 for c in range(4)}):
            raise ValueError("ordered deterministic sampling or class balance differs")
        if role in training:
            indices = [source["index"] for source in role_sources]
            expected = {"indices": indices, "labels": [actual_labels[i] for i in indices],
                        "source_ids": [sources[i]["source_id"] for i in indices]}
            if training[role] != expected:
                raise ValueError("training labels differ from independent source reconstruction")
    return {"schema": "hepta.cell-retention-independent-input-audit.v2",
            "algorithm": "independent adjacency-list BFS, no preparation union-find imported",
            "raw_rows": len(raw), "components": count, "verified_selected_components": verified,
            "verified_previous_components": prior_verified, "selected_v1_overlap": 0, "selected_legacy_overlap": 0,
            "excluded_components_by_reason": dict(reasons), "eligible_components_by_month_class": dict(support),
            "ordered_sampling_and_training_labels_reproduced": True,
            "final_labels_file_opened": False, "final_label_payload_hash_deferred_until_scoring": True,
            "previous_source_provenance": prior_provenance,
            "protocol_sha256": sha(plan_bytes), "data_receipt_sha256": sha(receipt_bytes),
            "auditor_sha256": sha(Path(__file__).read_bytes())}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "archive", "previous", "protocol", "output"):
        parser.add_argument("--" + name, required=True)
    args = vars(parser.parse_args())
    output = args.pop("output")
    result = audit_inputs(args.pop("data"), args.pop("archive"), args.pop("previous"), args.pop("protocol"))
    Path(output).write_bytes(canonical(result) + b"\n")
    print(json.dumps(result, indent=2))
