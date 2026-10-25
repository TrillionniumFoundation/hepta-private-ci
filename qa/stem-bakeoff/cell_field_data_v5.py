"""Fresh author-source V5 cohorts; evaluation labels leave the preparer encrypted.

Selection uses source categories only for conflict rejection and class balance.
Official train/test partitions are preserved; old/current have no chronology.
No encoder, training outcome, historical prediction or heldout metric is read.
"""

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tarfile
import time
import unicodedata

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from cell_field_data_v4 import ARCHIVES as PRIOR_ARCHIVES, clean_message, connected_components
from prepare_news_cohorts import _read_archive, _read_bounded, canonical


SCHEMA = "hepta.cell-field-fresh-data.v5"
SALT = "cell-field-fresh-v5-20261025"
MAX_TEXT = 6000
COUNTS = {"old_train": 256, "old_probe": 128, "old_validation": 256, "old_test": 512,
          "current_train": 256, "current_probe": 128, "current_validation": 256, "future_test": 512}
DATASETS = {
    "agnews": {"file": "ag-news.tar.gz", "sha256": "4e2fc37d369e6e317a8b62d0d2f11d379f8c3dde60c07c35a46b069a246498ad",
        "bytes": 11784327, "prefix": "ag_news_csv", "class_count": 4, "train_rows": 120000, "test_rows": 7600,
        "classes": ["World", "Sports", "Business", "Sci/Tech"],
        "url": "https://drive.google.com/uc?export=download&id=0Bz8a_Dbh9QhbUDNpeUdjb0wxRms"},
    "dbpedia": {"file": "dbpedia.tar.gz", "sha256": "cad5773f85d7501bb2783833768bc624641cdddf7056000a06f12bcd0239a310",
        "bytes": 68341698, "prefix": "dbpedia_csv", "class_count": 14, "train_rows": 560000, "test_rows": 70000,
        "classes": ["Company", "EducationalInstitution", "Artist", "Athlete"],
        "url": "https://drive.google.com/uc?export=download&id=0Bz8a_Dbh9QhbQ2Vic1kxMmZZQ1k"},
}


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def normalized(value):
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", value).casefold()))


def identity_keys(title, body, text):
    values = {normalized(v) for v in (title, body, text, text[:MAX_TEXT])}
    return tuple(sorted(sha(v.encode()) for v in values if v))


def data_plan():
    return {"schema": SCHEMA, "salt": SALT, "counts": COUNTS, "maximum_text_characters": MAX_TEXT,
        "sources": DATASETS, "class_mapping": "original source classes1..4 map to0..3; all other DBpedia classes excluded after graph closure",
        "text": "original CSV title + newline + description/content; deterministic first6000characters",
        "normalization": "NFKC,casefold,Unicode word tokens,collapsed whitespace; source-only identity matching",
        "components": "union equal normalized title,body,full input or truncated input across all official splits and both complete corpora",
        "prior_exclusion": {"uci_all_titles": PRIOR_ARCHIVES["uci"], "20news_all_cleaned_bodies_subjects": PRIOR_ARCHIVES["newsgroups"]},
        "reject": ["class_conflict", "cross_task", "cross_official_split", "any_prior_identity", "normalized_text_under20characters"],
        "split": "official test supplies future; official train components partition old/current by fixed SHA parity",
        "selection": "stable salted component SHA order; disjoint balanced roles; no retries or outcome-based resampling",
        "evaluation_labels": "AES-256-GCM payloads; evaluator-owned key; authenticated protocol/task/access/plaintext hashes",
        "limits": "exact normalized identity exclusion; semantic paraphrase overlap and foundation pretraining exposure unknown"}


def prior_identities(directory):
    directory = Path(directory)
    keys = set()
    rows = _read_archive(directory / "uci-news.zip")
    for row in rows:
        keys.update(identity_keys(row["text"], "", row["text"]))
    uci_count = len(rows)
    del rows
    payload = _read_bounded(directory / "20news-bydate.tar.gz", 32 << 20)
    if sha(payload) != PRIOR_ARCHIVES["newsgroups"]:
        raise ValueError("prior source archive identity differs")
    news_count = 0
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as bundle:
        for member in bundle:
            if not member.isfile():
                continue
            if member.size > 2 << 20:
                raise ValueError("prior message exceeds source bound")
            with bundle.extractfile(member) as stream:
                body, subject, _, _ = clean_message(stream.read(member.size+1))
            keys.update(identity_keys(subject, body, body))
            news_count += 1
    return keys, {"uci_rows": uci_count, "newsgroup_messages": news_count,
                  "identity_hashes": len(keys), "identity_set_sha256": sha(sorted(keys))}


def corpus_rows(directory, task):
    spec = DATASETS[task]
    payload = _read_bounded(Path(directory) / spec["file"], spec["bytes"])
    if len(payload) != spec["bytes"] or sha(payload) != spec["sha256"]:
        raise ValueError("fresh corpus archive identity differs")
    rows, observed = [], Counter()
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as bundle:
        for member in bundle:
            split = next((s for s in ("train", "test") if member.name == spec["prefix"]+"/"+s+".csv"), None)
            if split is None:
                continue
            if not member.isfile() or member.size > 256 << 20 or observed[split]:
                raise ValueError("changed or duplicate source CSV member")
            with bundle.extractfile(member) as stream:
                for number, values in enumerate(csv.reader(io.TextIOWrapper(stream, encoding="utf-8", newline=""), strict=True)):
                    if len(values) != 3 or not 1 <= int(values[0]) <= spec["class_count"]:
                        raise ValueError("source CSV schema or label outside original classes")
                    label, title, body = int(values[0])-1, values[1], values[2]
                    text = title+"\n"+body
                    row_hash = sha(values)
                    rows.append({"task_id": task, "official_split": split, "label": label,
                        "source_id": task+":"+sha([split, number, row_hash]), "source_row_sha256": row_hash,
                        "text": text[:MAX_TEXT] if label < 4 else None,
                        "short": len(normalized(text)) < 20, "edges": identity_keys(title, body, text),
                        "truncated_characters": max(0, len(text)-MAX_TEXT)})
                    observed[split] += 1
    if dict(observed) != {s: spec[s+"_rows"] for s in ("train", "test")}:
        raise ValueError("source CSV row census changed")
    return rows


def candidates(inputs, prior_inputs):
    forbidden, prior_audit = prior_identities(prior_inputs)
    rows = [row for task in DATASETS for row in corpus_rows(inputs, task)]
    groups = connected_components(rows)
    selected, excluded = {task: [] for task in DATASETS}, defaultdict(list)
    for members in groups:
        ids = sorted(rows[i]["source_id"] for i in members)
        digest = sha(ids)
        tasks = {rows[i]["task_id"] for i in members}
        labels = {rows[i]["label"] for i in members}
        splits = {rows[i]["official_split"] for i in members}
        reasons = []
        for condition, reason in ((len(tasks) != 1, "cross_task"), (len(labels) != 1, "class_conflict"),
            (len(splits) != 1, "cross_official_split"), (any(rows[i]["short"] for i in members), "short_text"),
            (any(forbidden.intersection(rows[i]["edges"]) for i in members), "any_prior_identity")):
            if condition:
                reasons.append(reason)
        if reasons:
            for reason in reasons:
                excluded[reason].append(digest)
            continue
        label, task, split = next(iter(labels)), next(iter(tasks)), next(iter(splits))
        if label >= 4:
            excluded["outside_fixed_four_classes"].append(digest)
            continue
        source = min((rows[i] for i in members), key=lambda r: r["source_id"])
        bucket = "future" if split == "test" else ("old" if int(sha([SALT, "partition", task, digest])[:8], 16) % 2 == 0 else "current")
        selected[task].append({k: v for k, v in source.items() if k not in ("edges", "short")})
        selected[task][-1].update(bucket=bucket, component_id=task+"-group:"+digest,
            component_member_count=len(ids), component_members_sha256=sha(ids))
    audit = {"raw_rows": len(rows), "components": len(groups), "prior": prior_audit,
        "excluded_counts": {reason: len(ids) for reason, ids in excluded.items()}, "reason_counts_overlap": True,
        "excluded_component_hashes": {reason: sha(sorted(ids)) for reason, ids in excluded.items()}}
    return selected, audit


def select(rows, task):
    buckets, offsets, chosen = defaultdict(list), Counter(), []
    for row in rows:
        buckets[row["bucket"], row["label"]].append(row)
    for values in buckets.values():
        values.sort(key=lambda row: sha([SALT, task, row["component_id"]]))
    for role, count in COUNTS.items():
        bucket = role.split("_")[0]
        role_rows = []
        for label in range(4):
            key = bucket, label
            start, end = offsets[key], offsets[key]+count//4
            if end > len(buckets[key]):
                raise ValueError(f"source-only infeasibility for {task}/{role}/{label}")
            role_rows.extend(buckets[key][start:end])
            offsets[key] = end
        chosen.extend({**row, "role": role} for row in sorted(role_rows,
            key=lambda r: sha([SALT, task, role, r["component_id"]])))
    if len({r["component_id"] for r in chosen}) != sum(COUNTS.values()):
        raise ValueError("selected source component crosses roles")
    return chosen, {f"{bucket}/{label}": len(values) for (bucket, label), values in sorted(buckets.items())}


def feasibility(inputs, prior_inputs):
    rows, audit = candidates(inputs, prior_inputs)
    return {"data_plan": data_plan(), "audit": audit,
            "eligible": {task: select(rows[task], task)[1] for task in DATASETS},
            "selected_counts": {task: COUNTS for task in DATASETS}, "model_outcomes_read": False}


def prepare(inputs, prior_inputs, output, protocol, label_key):
    if not isinstance(label_key, bytes) or len(label_key) != 32:
        raise ValueError("evaluator-owned256-bit label key required")
    protocol_bytes = _read_bounded(protocol, 1 << 20)
    if json.loads(protocol_bytes).get("data_plan") != data_plan():
        raise ValueError("pre-outcome protocol does not contain the exact V5 source plan")
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    began = time.perf_counter_ns()
    rows, audit = candidates(inputs, prior_inputs)
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
            "label_access": "only train labels plaintext; encrypted validation/final; key absent from prepared data",
            "semantics": "official historical source partitions; old/current SHA partition; foundation pretraining exposure unknown"}
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
        prepare(args.inputs, args.prior_inputs, args.output, args.protocol, key)
