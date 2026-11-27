"""Fresh V6 source components exclude the entire reproducible V5 cohort.

The source graph and author archive pins remain unchanged. No model outcome or
encrypted V5 label is read. V6 labels use a separate evaluator-owned key.
"""

import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from cell_field_data_v5 import COUNTS, DATASETS, candidates, data_plan as prior_plan, select as prior_select, sha
from prepare_news_cohorts import _read_bounded, canonical


SCHEMA = "hepta.cell-field-fresh-data.v6"
SALT = "cell-field-fresh-v6-20261025"
V5_PROTOCOL_SHA256 = "654994abfb66e8872b0d6632b7d80d5058ad5af06adc2d2dea0de628395ba05e"
V5_COMPONENTS = {
    "agnews": "f9fccb58c43a2270c4544348858d67e7d560ecce79fc7ddf310b1ae236e4787c",
    "dbpedia": "ebfdfa614ce9c7101461070aaa413894102285a21f05489d18e51fba18595d5f",
}


def data_plan():
    plan = prior_plan()
    plan.update(schema=SCHEMA, salt=SALT,
        previous_cohort_exclusion={"protocol_sha256": V5_PROTOCOL_SHA256,
            "components_per_task": 2304, "sorted_component_set_sha256": V5_COMPONENTS,
            "construction": "reconstruct original V5 deterministic selection from pinned source graph; verify hashes; exclude all roles"})
    return plan


def fresh_candidates(inputs, prior_inputs):
    rows, audit = candidates(inputs, prior_inputs)
    excluded, receipts = set(), {}
    for task in DATASETS:
        original, _ = prior_select(rows[task], task)
        ids = sorted(r["component_id"] for r in original)
        if len(ids) != 2304 or sha(ids) != V5_COMPONENTS[task]:
            raise ValueError("reconstructed V5 selection differs from its precommitted component identity")
        excluded.update(ids)
        receipts[task] = {"excluded_components": len(ids), "component_set_sha256": sha(ids)}
    fresh = {}
    for task, values in rows.items():
        fresh[task] = []
        for row in values:
            if row["component_id"] in excluded:
                continue
            digest = row["component_id"].split(":", 1)[1]
            bucket = "future" if row["official_split"] == "test" else (
                "old" if int(sha([SALT, "partition", task, digest])[:8], 16) % 2 == 0 else "current")
            fresh[task].append({**row, "bucket": bucket})
    return fresh, {**audit, "v5_exclusion": receipts, "excluded_v5_components_total": len(excluded)}


def select(rows, task):
    buckets, offsets, chosen = defaultdict(list), Counter(), []
    for row in rows:
        buckets[row["bucket"], row["label"]].append(row)
    for values in buckets.values():
        values.sort(key=lambda row: sha([SALT, task, row["component_id"]]))
    for role, count in COUNTS.items():
        role_rows = []
        for label in range(4):
            key = role.split("_")[0], label
            start, end = offsets[key], offsets[key]+count//4
            if end > len(buckets[key]):
                raise ValueError(f"source-only infeasibility for {task}/{role}/{label}")
            role_rows.extend(buckets[key][start:end])
            offsets[key] = end
        chosen.extend({**row, "role": role} for row in sorted(role_rows,
            key=lambda r: sha([SALT, task, role, r["component_id"]])))
    if len({r["component_id"] for r in chosen}) != sum(COUNTS.values()):
        raise ValueError("selected V6 source component crosses roles")
    return chosen, {f"{bucket}/{label}": len(values) for (bucket, label), values in sorted(buckets.items())}


def feasibility(inputs, prior_inputs):
    rows, audit = fresh_candidates(inputs, prior_inputs)
    return {"data_plan": data_plan(), "audit": audit,
        "eligible": {task: select(rows[task], task)[1] for task in DATASETS},
        "selected_counts": {task: COUNTS for task in DATASETS},
        "model_outcomes_read": False, "prior_evaluation_labels_decrypted": False}


def prepare(inputs, prior_inputs, output, protocol, label_key):
    if not isinstance(label_key, bytes) or len(label_key) != 32:
        raise ValueError("separate evaluator-owned 256-bit V6 key required")
    protocol_bytes = _read_bounded(protocol, 1 << 20)
    if json.loads(protocol_bytes).get("data_plan") != data_plan():
        raise ValueError("pre-outcome protocol does not contain the exact V6 source plan")
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    began = time.perf_counter_ns()
    rows, audit = fresh_candidates(inputs, prior_inputs)
    manifest = {"schema": SCHEMA, "protocol_sha256": sha(protocol_bytes), "tasks": {}}
    for task in DATASETS:
        selected, support = select(rows[task], task)
        directory = root/task
        directory.mkdir()
        predictors, sources, roles = [], [], defaultdict(lambda: {"indices": [], "labels": [], "source_ids": []})
        for index, row in enumerate(selected):
            sources.append({k: v for k, v in row.items() if k not in ("label", "text")})
            sources[-1].update(index=index, source_group_id=row["component_id"], input_text_sha256=sha(row["text"].encode()))
            predictors.append({"source_id": row["source_id"], "source_version": "sha256:"+row["source_row_sha256"], "text": row["text"]})
            for key, value in (("indices", index), ("labels", row["label"]), ("source_ids", row["source_id"])):
                roles[row["role"]][key].append(value)
        payloads = {"sources.json": {"schema": SCHEMA, "rows": sources}, "predictors.json": {"schema": SCHEMA, "rows": predictors}}
        encrypted = {}
        for access in ("train", "validation", "final"):
            admitted = [role for role in COUNTS if ("validation" if role.endswith("validation") else "final" if role.endswith("test") else "train") == access]
            value = {"schema": SCHEMA, "classes": 4, "roles": {role: roles[role] for role in admitted}}
            name = access+"_labels.json"
            if access == "train":
                payloads[name] = value
                continue
            content, nonce = canonical(value)+b"\n", os.urandom(12)
            aad = {"protocol_sha256": sha(protocol_bytes), "task_id": task, "access": access, "plaintext_sha256": sha(content)}
            cipher = nonce+AESGCM(label_key).encrypt(nonce, content, canonical(aad))
            name += ".aesgcm"
            (directory/name).write_bytes(cipher)
            encrypted[access] = {"file": name, "sha256": sha(cipher), "bytes": len(cipher), "plaintext_bytes": len(content), "aad": aad}
        files = {}
        for name, value in payloads.items():
            content = canonical(value)+b"\n"
            (directory/name).write_bytes(content)
            files[name] = {"sha256": sha(content), "bytes": len(content)}
        files.update({entry["file"]: {k: entry[k] for k in ("sha256", "bytes")} for entry in encrypted.values()})
        receipt = {"schema": SCHEMA, "task_id": task, "protocol_sha256": sha(protocol_bytes), "files": files,
            "sealed_labels": encrypted, "rows": len(selected), "counts": COUNTS, "source_archive_sha256": DATASETS[task]["sha256"],
            "audit": {**audit, "eligible_components_by_bucket_class": support}, "authority": "DENY_ALL",
            "label_access": "train labels plaintext; V6 validation/final encrypted under separate evaluator-owned key",
            "semantics": "fresh components excluding every V5 selected role; old/current SHA partition; official test future"}
        content = canonical(receipt)+b"\n"
        (directory/"data_receipt.json").write_bytes(content)
        manifest["tasks"][task] = {"rows": len(selected), "data_receipt_sha256": sha(content), "files": files}
    manifest["wall_ns"] = time.perf_counter_ns()-began
    (root/"manifest.json").write_bytes(canonical(manifest)+b"\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("inputs", "prior-inputs", "output"):
        parser.add_argument("--"+name, required=True)
    parser.add_argument("--protocol")
    parser.add_argument("--feasibility-only", action="store_true")
    args = parser.parse_args()
    if args.feasibility_only:
        Path(args.output).write_bytes(canonical(feasibility(args.inputs, args.prior_inputs))+b"\n")
    else:
        import sys
        key = bytes.fromhex(sys.stdin.readline().strip())
        result = prepare(args.inputs, args.prior_inputs, args.output, args.protocol, key)
        print(json.dumps({"rows": {t: r["rows"] for t, r in result["tasks"].items()}}))
