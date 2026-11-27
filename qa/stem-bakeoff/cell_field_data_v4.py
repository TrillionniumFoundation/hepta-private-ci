"""Byte-pinned fresh UCI and newsgroup cohorts with sealed, separate label roles.

Only source feasibility determines membership. No model outcomes or old result
labels are consumed. Dates absent from the sanitized newsgroup archive are never
invented: old/current partition original train components; future is official test.
"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import compat32
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile
import time

from prepare_news_cohorts import (_read_archive, _read_bounded, canonical, COUNTS,
                                  normalized_title, publisher_is_ood, select_rows)


SALT = "cell-field-joint-v4-20261025"
SCHEMA = "hepta.cell-field-joint-data.v4"
MAX_TEXT = 6000
CATEGORIES = ("comp.graphics", "rec.autos", "sci.space", "talk.politics.misc")
ARCHIVES = {"uci": "1f5f08691f0ce576cb0b5cfdbcb8c55e0ec14dda8f3e07933da72c500338845a",
            "newsgroups": "8f1b2514ca22a5ade8fbb9cfa5727df95fa587f4c87b786e15c759fa66d95610"}
PRIORS = {"v1": ("d3d8c203c2fd88966fa937d0e0b5cf2826399f558a26dc1e256e47ab479a0482", 512),
          "v2": ("e0e03839ba6cf957288023b04895eaceae5ac89a9b1ae161ff7518c22f9dd482", 480),
          "v3": ("56b0a717cd4afbd82e73a46064e2fe310a2a9c642433b6d9ff8108aa14fc1baa", 624),
          "retention": ("053e3799862adaad9a074b77c8f99a3018a5b1b9b4b3f7655b2c504b497f9e35", 480)}
ROLE_NAMES = ("old_train", "old_probe", "old_validation", "old_test", "current_train",
              "current_probe", "current_validation", "future_test")
ACCESS = ("train", "train", "validation", "final", "train", "train", "validation", "final")


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def data_plan():
    counts = {"uci": (64, 32, 32, 32, 32, 16, 32, 112),
              "newsgroups": (64, 32, 64, 64, 64, 32, 64, 128)}
    return {"salt": SALT, "maximum_text_characters": MAX_TEXT, "archive_sha256": ARCHIVES,
        "prior_source_pins": {name: {"sha256": pin, "rows": n} for name, (pin, n) in PRIORS.items()},
        "newsgroup_categories": list(CATEGORIES),
        "newsgroup_split": "original train component hash partition; official test future; no within-train chronology",
        "cleaning": "strip headers, quoted lines and signature; full and truncated normalized body plus subject/message-ID union",
        "tasks": {task: [{"role": role, "rows": n, "access": access,
            "bucket": (("2014-04" if role.startswith("old_") else "2014-05" if role.startswith("current_") else "2014-07")
                       if task == "uci" else role.split("_")[0])}
            for role, n, access in zip(ROLE_NAMES, amounts, ACCESS)] for task, amounts in counts.items()}}


def connected_components(rows):
    """Close all declared identity links before any role or class selection."""
    parent, seen = list(range(len(rows))), {}
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for index, row in enumerate(rows):
        for key in row["edges"]:
            if key in seen:
                a, b = find(index), find(seen[key])
                parent[max(a, b)] = min(a, b)
            else:
                seen[key] = index
    groups = defaultdict(list)
    for index in range(len(rows)):
        groups[find(index)].append(index)
    return list(groups.values())


def uci_candidates(archive, prior_directory):
    rows = _read_archive(archive)
    legacy = {r["source_id"] for cohort in select_rows(rows, COUNTS).values() for r in cohort}
    prior, provenance = defaultdict(list), {}
    for name, (pin, count) in PRIORS.items():
        payload = _read_bounded(Path(prior_directory) / (name + "-sources.json"), 2 << 20)
        if sha(payload) != pin:
            raise ValueError("prior source identity changed: " + name)
        source = json.loads(payload)["rows"]
        if len(source) != count or len({r["raw_source_id"] for r in source}) != count:
            raise ValueError("prior source census changed")
        for row in source:
            prior[row["raw_source_id"]].append((name, row))
        provenance[name] = {"sha256": pin, "bytes": len(payload), "rows": count}
    if not legacy | set(prior) <= {r["source_id"] for r in rows}:
        raise ValueError("prior identities absent from source archive")
    for row in rows:
        row["bucket"] = datetime.fromtimestamp(row["timestamp_ms"] / 1000, timezone.utc).strftime("%Y-%m")
        row["edges"] = (("story", row["source_group_id"]), ("title", normalized_title(row["text"])))
    groups, candidates, excluded = connected_components(rows), [], defaultdict(list)
    for members in groups:
        ids = sorted(rows[i]["source_id"] for i in members)
        component = "news-group:" + sha(ids)
        touched = [pair for rid in ids for pair in prior.get(rid, [])]
        for _, previous in touched:
            if (previous["component_id"] != component or previous["component_member_count"] != len(ids)
                    or previous["component_members_sha256"] != sha(ids)):
                raise ValueError("prior full component identity changed")
        reasons = []
        labels, buckets = {rows[i]["label"] for i in members}, {rows[i]["bucket"] for i in members}
        if len(labels) != 1:
            reasons.append("label_conflict")
        if len(buckets) != 1:
            reasons.append("cross_month")
        if legacy.intersection(ids):
            reasons.append("legacy_five")
        reasons += sorted({"previous_" + name for name, _ in touched})
        eligible = [i for i in members if not publisher_is_ood(rows[i]["publisher"])]
        if not eligible:
            reasons.append("only_ood_publishers")
        if reasons:
            for reason in reasons:
                excluded[reason].append(component)
            continue
        representative = rows[min(eligible, key=lambda i: (rows[i]["timestamp_ms"], rows[i]["source_id"]))]
        candidates.append({"label": next(iter(labels)), "bucket": next(iter(buckets)),
            "text": representative["text"][:MAX_TEXT], "source_id": "uci-news:" + representative["source_id"],
            "raw_source_id": representative["source_id"], "source_row_sha256": representative["source_row_sha256"],
            "timestamp_ms": representative["timestamp_ms"], "component_id": component,
            "component_member_count": len(ids), "component_members_sha256": sha(ids),
            "truncated_characters": max(0, len(representative["text"]) - MAX_TEXT)})
    audit = {"raw_rows": len(rows), "raw_components": len(groups), "prior_sources": provenance,
        "legacy_rows": len(legacy), "legacy_raw_ids_sha256": sha(sorted(legacy)),
        "prior_union_raw_ids": len(legacy | set(prior)),
        "excluded_component_counts": {k: len(v) for k, v in excluded.items()},
        "exclusion_ids_sha256": {k: sha(sorted(v)) for k, v in excluded.items()},
        "exclusion_counts_overlap": True, "prior_v1_provenance": "deterministic reconstruction matched exact published source SHA256",
        "edges": ["raw story", "normalized title"], "pretraining_exposure_excluded": False}
    return candidates, audit


def clean_message(raw):
    """Deterministic source-only cleaning; return full text and identity headers."""
    if not isinstance(raw, bytes) or len(raw) > 2 << 20:
        raise ValueError("bounded message bytes required")
    message = BytesParser(policy=compat32).parsebytes(raw, headersonly=True)
    parts = re.split(r"\r?\n\r?\n", raw.decode("latin1"), maxsplit=1)
    body = parts[1] if len(parts) == 2 else ""
    body = re.split(r"(?m)^-- ?$", body, maxsplit=1)[0]
    body = "\n".join(line for line in body.splitlines() if not re.search(
        r"(^\s*[>|]|\b(?:wrote|writes|said):\s*$|^In article\b)", line)).strip()
    subject = re.sub(r"^(?:(?:re|fw|fwd)\s*:\s*)+", "", normalized_title(str(message.get("Subject", ""))))
    return body, subject, normalized_title(str(message.get("Message-ID", ""))), bool(message.get("Date"))


def newsgroup_candidates(archive):
    payload = _read_bounded(archive, 32 << 20)
    if sha(payload) != ARCHIVES["newsgroups"]:
        raise ValueError("newsgroup archive hash mismatch")
    rows, removed, header_counts, expanded = [], Counter(), Counter(), 0
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as bundle:
        for member in bundle:
            if not member.isfile():
                continue
            parts = member.name.split("/")
            if (len(parts) != 3 or parts[0] not in ("20news-bydate-train", "20news-bydate-test")
                    or any(p in ("", ".", "..") for p in parts) or member.size > 2 << 20):
                raise ValueError("unexpected source archive member")
            expanded += member.size
            if expanded > 128 << 20:
                raise ValueError("source archive exceeds expanded budget")
            raw = bundle.extractfile(member).read()
            body, subject, message_id, date = clean_message(raw)
            if parts[1] in CATEGORIES:
                header_counts["target_messages"] += 1
                header_counts["Date"] += date
                header_counts["Message-ID"] += bool(message_id)
            if len(normalized_title(body)) < 20:
                removed["empty_or_short_cleaned_body"] += 1
                continue
            full_hash, input_hash = sha(normalized_title(body).encode()), sha(normalized_title(body[:MAX_TEXT]).encode())
            edges = [("body", full_hash), ("truncated_body", input_hash)]
            edges += [(key, value) for key, value in (("subject", subject), ("message_id", message_id)) if value]
            rows.append({"source_id": "20news:" + member.name, "raw_source_id": member.name,
                "category": parts[1], "split": parts[0], "edges": edges, "text": body[:MAX_TEXT],
                "source_row_sha256": sha(raw), "full_cleaned_body_sha256": full_hash,
                "normalized_input_sha256": input_hash, "truncated_characters": max(0, len(body) - MAX_TEXT)})
    groups, candidates, excluded = connected_components(rows), [], defaultdict(list)
    for members in groups:
        ids = sorted(rows[i]["raw_source_id"] for i in members)
        digest, labels = sha(ids), {rows[i]["category"] for i in members}
        component = "20news-group:" + digest
        if len(labels) != 1:
            excluded["category_conflict"].append(component)
            continue
        category = next(iter(labels))
        if category not in CATEGORIES:
            continue
        splits = {rows[i]["split"] for i in members}
        if len(splits) != 1:
            excluded["cross_official_split"].append(component)
            continue
        split = next(iter(splits))
        bucket = ("future" if split.endswith("test") else "old" if
                  int(sha((SALT + "/partition/" + digest).encode())[:8], 16) % 2 == 0 else "current")
        row = min((rows[i] for i in members), key=lambda r: r["raw_source_id"])
        candidates.append({**{k: v for k, v in row.items() if k not in ("edges", "category")},
            "label": CATEGORIES.index(category), "bucket": bucket, "component_id": component,
            "component_member_count": len(ids), "component_members_sha256": sha(ids)})
    return candidates, {"raw_rows_after_cleaning": len(rows), "raw_components": len(groups),
        "cleaning_removed": dict(removed), "target_header_counts": dict(header_counts),
        "excluded_component_counts": {k: len(v) for k, v in excluded.items()},
        "exclusion_ids_sha256": {k: sha(sorted(v)) for k, v in excluded.items()},
        "edges": ["full normalized cleaned body", "normalized 6000-character input", "normalized subject", "message-ID if present"],
        "old_current_temporal_claim": False, "pretraining_exposure_excluded": False}


def select_candidates(candidates, roles, task):
    buckets, offsets, selected = defaultdict(list), Counter(), []
    for row in candidates:
        buckets[(row["bucket"], row["label"])].append(row)
    for values in buckets.values():
        values.sort(key=lambda row: sha([SALT, task, row["component_id"]]))
    support = {f"{bucket}/{label}": len(rows) for (bucket, label), rows in sorted(buckets.items())}
    for role in roles:
        chosen = []
        for label in range(4):
            key = (role["bucket"], label)
            start, end = offsets[key], offsets[key] + role["rows"] // 4
            if end > len(buckets[key]):
                raise ValueError(f"insufficient {task}/{role['role']}/{label}; never resample after outcomes")
            chosen += buckets[key][start:end]
            offsets[key] = end
        selected += [{**row, "role": role["role"], "access": role["access"]}
            for row in sorted(chosen, key=lambda row: sha([SALT, task, role["role"], row["component_id"]]))]
    if len({row["component_id"] for row in selected}) != len(selected):
        raise ValueError("source component crossed role boundary")
    return selected, support


def prepare(uci_archive, newsgroups_archive, prior_directory, output, protocol):
    protocol_bytes = _read_bounded(protocol, 1 << 20)
    if json.loads(protocol_bytes).get("data_plan") != data_plan():
        raise ValueError("frozen joint protocol and exact data plan differ")
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    manifest = {"schema": SCHEMA, "protocol_sha256": sha(protocol_bytes), "tasks": {}}
    for task, function, args in (("uci", uci_candidates, (uci_archive, prior_directory)),
                                 ("newsgroups", newsgroup_candidates, (newsgroups_archive,))):
        candidates, audit = function(*args)
        selected, support = select_candidates(candidates, data_plan()["tasks"][task], task)
        audit["eligible_components_by_bucket_class"] = support
        directory = root / task
        directory.mkdir()
        sources, predictors, roles = [], [], defaultdict(lambda: {"indices": [], "labels": [], "source_ids": []})
        for index, row in enumerate(selected):
            source = {k: v for k, v in row.items() if k not in ("label", "text", "access")}
            source.update(index=index, task_id=task, source_group_id=row["component_id"],
                          input_text_sha256=sha(row["text"].encode()))
            sources.append(source)
            predictors.append({"source_id": row["source_id"], "source_version": "sha256:" + row["source_row_sha256"], "text": row["text"]})
            for key, value in (("indices", index), ("labels", row["label"]), ("source_ids", row["source_id"])):
                roles[row["role"]][key].append(value)
        payloads = {"sources.json": {"schema": SCHEMA, "rows": sources},
                    "predictors.json": {"schema": SCHEMA, "rows": predictors}}
        for access in ("train", "validation", "final"):
            payloads[access + "_labels.json"] = {"schema": SCHEMA, "classes": 4,
                "roles": {r["role"]: roles[r["role"]] for r in data_plan()["tasks"][task] if r["access"] == access}}
        files = {}
        for name, value in payloads.items():
            content = canonical(value) + b"\n"
            (directory / name).write_bytes(content)
            files[name] = {"sha256": sha(content), "bytes": len(content)}
        receipt = {"schema": SCHEMA, "task_id": task, "protocol_sha256": sha(protocol_bytes),
            "source_archive_sha256": ARCHIVES[task], "salt": SALT, "files": files,
            "roles": data_plan()["tasks"][task], "rows": len(selected), "audit": audit,
            "labels": "preparer sees source categories for balanced selection; separate payloads never read back",
            "semantics": "historical source holdouts; public pretraining exposure unknown",
            "authority": "DENY_ALL", "production_authority": False}
        (directory / "data_receipt.json").write_bytes(canonical(receipt) + b"\n")
        manifest["tasks"][task] = {"rows": len(selected), "data_receipt_sha256": sha(canonical(receipt) + b"\n"), "files": files}
    manifest.update(wall_ns=time.perf_counter_ns() - began, cpu_ns=time.process_time_ns() - cpu)
    (root / "manifest.json").write_bytes(canonical(manifest) + b"\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("uci-archive", "newsgroups-archive", "prior-directory", "output", "protocol"):
        parser.add_argument("--" + name, required=True)
    print(json.dumps(prepare(**vars(parser.parse_args()))), flush=True)
