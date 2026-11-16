"""Independent BFS source audit for V3; does not open withheld label payloads."""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import unicodedata

from prepare_news_cohorts import COUNTS, _read_archive, select_rows


SCHEMA = "hepta.cell-action-news.v3"
ARCHIVE_SHA256 = "1f5f08691f0ce576cb0b5cfdbcb8c55e0ec14dda8f3e07933da72c500338845a"
SALT = "hepta-cell-action-v3-20261024"
PINNED_PRIORS = {
    "v1": {"count": 512,
           "sources": {"sha256": "d3d8c203c2fd88966fa937d0e0b5cf2826399f558a26dc1e256e47ab479a0482", "bytes": 315623},
           "receipt": {"sha256": "57742ed6e70c5c33053e4092bc3f58d46f791e84ffedb2efe79fd187e2e707ea", "bytes": 4055},
           "seal_sha256": "68c5b247fa399901fea32076e11ed0a4a5149cbd52ba3690ff1bdc09adf66549"},
    "v2": {"count": 480,
           "sources": {"sha256": "e0e03839ba6cf957288023b04895eaceae5ac89a9b1ae161ff7518c22f9dd482", "bytes": 296017},
           "receipt": {"sha256": "41955087b6ac5cb3fb48ff15d4cb17014eb4a5965c1ba9c6324ce9a0dacc263f", "bytes": 4660}},
}
TRAIN_ROLES = {"old_train", "old_probe", "current_train", "current_probe"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def normalize(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _identity(path):
    if path.is_symlink():
        raise ValueError("source evidence must not be a symlink")
    payload = path.read_bytes()
    return payload, {"bytes": len(payload), "sha256": sha(payload)}


def _prior(directory, name):
    root, pin = Path(directory), PINNED_PRIORS[name]
    payload, identity = _identity(root / "sources.json")
    if identity != pin["sources"]:
        raise ValueError(name + " source identity differs from published evidence")
    receipt_path = root / "data_receipt.json"
    if receipt_path.is_symlink():
        raise ValueError("source evidence must not be a symlink")
    if receipt_path.exists():
        receipt_bytes, receipt_identity = _identity(receipt_path)
        saved = json.loads(receipt_bytes)
        if (receipt_identity != pin["receipt"] or saved["files"]["sources.json"] != pin["sources"]
                or saved["source_archive_sha256"] != ARCHIVE_SHA256):
            raise ValueError(name + " original receipt identity differs")
        provenance = {"mode": "original_receipt", "original_receipt_present": True}
        if name == "v1":
            provenance["seal_sha256"] = None
    elif name == "v1":
        seal_bytes, _ = _identity(root / "pre_evaluation_seal.json")
        saved = json.loads(seal_bytes)
        if (sha(seal_bytes) != pin["seal_sha256"]
                or saved["files"]["inputs/sources.json"] != pin["sources"]
                or saved["files"]["inputs/data_receipt.json"] != pin["receipt"]
                or saved.get("final_labels_opened") is not False):
            raise ValueError("v1 seal does not bind both historical identities")
        provenance = {"mode": "published_pre_evaluation_seal", "seal_sha256": pin["seal_sha256"],
                      "original_receipt_present": False}
    else:
        raise ValueError("v2 original receipt is required")
    source = json.loads(payload)["rows"]
    if (len(source) != pin["count"] or [row["index"] for row in source] != list(range(pin["count"]))
            or len({row["component_id"] for row in source}) != pin["count"]
            or len({row["raw_source_id"] for row in source}) != pin["count"]
            or any(row["source_id"] != "uci-news:" + row["raw_source_id"] for row in source)):
        raise ValueError(name + " source census is incomplete or duplicated")
    provenance.update(sources=pin["sources"], original_receipt=pin["receipt"])
    return source, provenance


def audit_inputs(data, archive, previous_v1, previous_v2, protocol):
    root = Path(data)
    plan_bytes, _ = _identity(Path(protocol))
    receipt_bytes, receipt_identity = _identity(root / "data_receipt.json")
    plan, receipt = json.loads(plan_bytes), json.loads(receipt_bytes)
    expected_prior = {name: {"sources_sha256": value["sources"]["sha256"],
                            "data_receipt_sha256": value["receipt"]["sha256"]} for name, value in PINNED_PRIORS.items()}
    prior, provenance = {}, {}
    for name, directory in (("v1", previous_v1), ("v2", previous_v2)):
        previous, provenance[name] = _prior(directory, name)
        prior[name] = {row["raw_source_id"]: row for row in previous}
    if (set(prior["v1"]) & set(prior["v2"])
            or {row["component_id"] for row in prior["v1"].values()} & {row["component_id"] for row in prior["v2"].values()}):
        raise ValueError("prior experiment censuses overlap")
    role_plan = plan["source_role_plan"]
    expected_roles = {row["role"]: {"month": row["month"], "rows": row["rows"],
                        "labels_per_class": row["rows"] // 4, "access": row["access"]} for row in role_plan}
    if (len(expected_roles) != len(role_plan) or receipt["roles"] != expected_roles
            or plan["source_counts"] != {row["role"]: row["rows"] for row in role_plan}
            or any(type(row["rows"]) is not int or not 4 <= row["rows"] <= 512 or row["rows"] % 4 for row in role_plan)
            or any(row["access"] not in {"train", "validation", "final"} for row in role_plan)
            or {r["role"] for r in role_plan if r["access"] == "train"} != TRAIN_ROLES
            or not any(r["role"] == "old_validation" and r["access"] == "validation" for r in role_plan)
            or not any(r["role"] == "old_test" and r["access"] == "final" for r in role_plan)
            or not any(r["role"].startswith("future_") and r["access"] == "final" for r in role_plan)):
        raise ValueError("protocol source roles, count or label boundary differs")
    if (receipt["schema"] != SCHEMA or receipt["protocol_sha256"] != sha(plan_bytes)
            or receipt["salt"] != SALT or plan["source_split_salt"] != SALT
            or receipt["prior_experiments"] != expected_prior or plan["prior_experiments"] != expected_prior
            or receipt["previous_source_provenance"] != provenance
            or receipt["source_archive_sha256"] != ARCHIVE_SHA256 or plan["source_archive_sha256"] != ARCHIVE_SHA256):
        raise ValueError("pinned protocol or previous source identity differs")
    expected_files = {"predictors.json", "sources.json", "train_labels.json", "validation_labels.json", "final_labels.json"}
    if set(receipt["files"]) != expected_files:
        raise ValueError("data payload inventory differs")
    objects = {}
    for name in expected_files - {"validation_labels.json", "final_labels.json"}:
        payload, identity = _identity(root / name)
        if identity != receipt["files"][name]:
            raise ValueError("preparation artifact identity differs: " + name)
        objects[name] = json.loads(payload)
        if objects[name]["schema"] != SCHEMA:
            raise ValueError("data payload schema differs")
    sources, predictors = objects["sources.json"]["rows"], objects["predictors.json"]["rows"]
    if (len(sources) != sum(plan["source_counts"].values()) or len(sources) != len(predictors)
            or [row["index"] for row in sources] != list(range(len(sources)))
            or len({row["raw_source_id"] for row in sources}) != len(sources)
            or len({row["component_id"] for row in sources}) != len(sources)):
        raise ValueError("selected source census differs")
    raw = _read_archive(archive)
    if len({row["source_id"] for row in raw}) != len(raw):
        raise ValueError("raw source identifiers are duplicated")
    legacy = {row["source_id"] for cohort in select_rows(raw, COUNTS).values() for row in cohort}
    stories, titles = defaultdict(list), defaultdict(list)
    for i, row in enumerate(raw):
        stories[row["source_group_id"]].append(i)
        titles[normalize(row["text"])].append(i)
    seen, selected = bytearray(len(raw)), {row["raw_source_id"]: row for row in sources}
    count, verified, prior_verified = 0, 0, Counter()
    reasons, support, exclusion_ids = Counter(), Counter(), defaultdict(list)
    candidates, actual_labels = defaultdict(list), {}
    wanted_months = {row["month"] for row in role_plan}
    for start in range(len(raw)):
        if seen[start]:
            continue
        pending, members = [start], []
        seen[start] = 1
        while pending:
            index = pending.pop()
            members.append(index)
            row = raw[index]
            for neighbour in stories.pop(row["source_group_id"], []) + titles.pop(normalize(row["text"]), []):
                if not seen[neighbour]:
                    seen[neighbour] = 1
                    pending.append(neighbour)
        count += 1
        ids = sorted(raw[i]["source_id"] for i in members)
        component = "news-group:" + sha(ids)
        touched = {name: [mapping[source] for source in ids if source in mapping] for name, mapping in prior.items()}
        for name, previous in touched.items():
            for saved in previous:
                if (saved["component_id"] != component or saved["component_member_count"] != len(ids)
                        or saved["component_members_sha256"] != sha(ids)):
                    raise ValueError("prior component differs from independently reconstructed graph")
                prior_verified[name] += 1
        months = {datetime.fromtimestamp(raw[i]["timestamp_ms"] / 1000, timezone.utc).strftime("%Y-%m") for i in members}
        labels = {raw[i]["label"] for i in members}
        causes = (["cross_month"] if len(months) != 1 else []) + (["label_conflict"] if len(labels) != 1 else [])
        if legacy.intersection(ids):
            causes.append("legacy_cohort_component")
        causes.extend(name + "_experiment_component" for name, previous in touched.items() if previous)
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
        candidates[(month, label)].append((sha([SALT, component]), rep["source_id"], component))
        if not picked:
            continue
        source, index = picked[0], picked[0]["index"]
        expected_predictor = {"source_id": "uci-news:" + rep["source_id"], "source_version": "sha256:" + rep["source_row_sha256"], "text": rep["text"]}
        expected_source = {"index": index, "source_id": expected_predictor["source_id"], "raw_source_id": rep["source_id"],
            "component_id": component, "month": month, "role": source["role"], "timestamp_ms": rep["timestamp_ms"],
            "source_row_sha256": rep["source_row_sha256"], "normalized_title_sha256": sha(normalize(rep["text"]).encode()),
            "publisher_sha256": sha(normalize(rep["publisher"]).encode()), "component_member_count": len(ids),
            "component_members_sha256": sha(ids)}
        if (predictors[index] != expected_predictor or source != expected_source
                or receipt["roles"][source["role"]]["month"] != month):
            raise ValueError("source representative or predictor identity differs")
        actual_labels[index] = label
        verified += 1
    audit = receipt["audit"]
    if (verified != len(sources) or dict(prior_verified) != {name: pin["count"] for name, pin in PINNED_PRIORS.items()}
            or count != audit["raw_components"] or len(raw) != audit["raw_rows"]
            or dict(reasons) != audit["excluded_components_by_reason"] or dict(support) != audit["eligible_components_by_month_class"]
            or {reason: sha(sorted(ids)) for reason, ids in exclusion_ids.items()} != audit["exclusion_component_ids_sha256"]):
        raise ValueError("independent graph or exclusion census differs")
    offsets, expected_label_roles = Counter(), defaultdict(dict)
    expected_order = []
    for spec in role_plan:
        role, month, amount = spec["role"], spec["month"], spec["rows"]
        chosen = []
        for label in range(4):
            key = (month, label)
            begin, end = offsets[key], offsets[key] + amount // 4
            chosen.extend(sorted(candidates[key])[begin:end])
            offsets[key] = end
        expected_ids = [source for _, source, component in sorted(chosen, key=lambda value: sha([SALT, role, value[2]]))]
        role_sources = [source for source in sources if source["role"] == role]
        if (expected_ids != [row["raw_source_id"] for row in role_sources]
                or Counter(actual_labels[row["index"]] for row in role_sources) != {c: amount // 4 for c in range(4)}):
            raise ValueError("ordered sampling or class balance differs")
        expected_order.extend(expected_ids)
        indices = [row["index"] for row in role_sources]
        expected_label_roles[spec["access"]][role] = {"indices": indices,
            "labels": [actual_labels[i] for i in indices], "source_ids": [sources[i]["source_id"] for i in indices]}
    if expected_order != [row["raw_source_id"] for row in sources]:
        raise ValueError("global role order differs from the protocol")
    for access in ("train", "validation", "final"):
        expected = {"schema": SCHEMA, "classes": 4, "roles": expected_label_roles[access]}
        payload = canonical(expected) + b"\n"
        if receipt["files"][access + "_labels.json"] != {"sha256": sha(payload), "bytes": len(payload)}:
            raise ValueError(access + " label payload identity differs from independent source reconstruction")
        if access == "train" and objects["train_labels.json"] != expected:
            raise ValueError("training label payload differs")
    return {"schema": "hepta.cell-action-independent-input-audit.v3",
        "algorithm": "independent adjacency-list BFS, no V3 preparation grouping or sampling imported",
        "raw_rows": len(raw), "components": count, "verified_selected_components": verified,
        "verified_previous_components": dict(prior_verified), "selected_v1_overlap": 0, "selected_v2_overlap": 0,
        "selected_legacy_overlap": 0, "ordered_sampling_and_training_labels_reproduced": True,
        "validation_labels_file_opened": False, "final_labels_file_opened": False,
        "withheld_payload_hashes_reconstructed_from_raw_source_labels": True,
        "withheld_payload_bytes_verification_deferred": True,
        "excluded_components_by_reason": dict(reasons), "eligible_components_by_month_class": dict(support),
        "previous_source_provenance": provenance, "protocol_sha256": sha(plan_bytes),
        "data_receipt_sha256": receipt_identity["sha256"], "auditor_sha256": sha(Path(__file__).read_bytes())}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "archive", "previous_v1", "previous_v2", "protocol", "output"):
        parser.add_argument("--" + name.replace("_", "-"), required=True)
    args = vars(parser.parse_args())
    output = args.pop("output")
    result = audit_inputs(**args)
    Path(output).write_bytes(canonical(result) + b"\n")
    print(json.dumps(result, indent=2))
