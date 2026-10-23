"""Fail-closed A-I MemoryCell acceptance protocol.

This is an evidence validator, NOT nine trained memory models. Source publishing,
prediction execution and gold adjudication must be separate processes. Only the
independently pinned original LoCoMo bytes qualify for the historical census.
A valid ledger establishes integrity, not semantic QA quality or superiority.
"""

import argparse
from collections import defaultdict
from dataclasses import dataclass
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import random
import stat
import statistics

from memory_retrieval_data import (
    SOURCE_SHA256, canonical, load_source, sha,
)
from memory_retrieval_scoring import score_query, summarize

SCHEMA = "hepta.memory-nine-arm-acceptance.v1"
SOURCE_SCHEMA = "hepta.memory-nine-arm-public-source.v1"
ROW_SCHEMA = "hepta.memory-nine-arm-prediction.v1"
MANIFEST_SCHEMA = "hepta.memory-nine-arm-artifacts.v1"
SEAL_SCHEMA = "hepta.memory-nine-arm-seal.v1"
PARENT_PLAN_SHA256 = "62216f4a7b69fb9f27e087b49daa5249bfb485e99ef96b88123d8fb8b025ff2f"
ARMS = {
    "A": "bm25",
    "B": "dense_bm25_reranker",
    "C": "graph_retrieval",
    "D": "typed_untrained",
    "E": "shared_encoder_single_trained_head",
    "F": "shared_encoder_multiple_typed_heads",
    "G": "learned_sparse_router",
    "H": "learned_meta_graph",
    "I": "split_merge_evolution",
}
COMPARISONS = (
    ("D", "C"), ("E", "D"), ("F", "E"), ("G", "F"),
    ("H", "G"), ("I", "H"), ("I", "B"), ("I", "C"),
)
PARTITIONS = {
    "development": ["conv-30", "conv-41"],
    "calibration": ["conv-26", "conv-44"],
    "evaluation": ["conv-47", "conv-42", "conv-48", "conv-43", "conv-49", "conv-50"],
}
ROW_KEYS = frozenset((
    "schema", "plan_sha256", "arm", "query_id", "group",
    "model_artifact_sha256", "reader_artifact_sha256", "reader_request_digest",
    "source_frontier_sha256", "forget_frontier_sha256",
    "selected_ids", "context_sha256", "context_bytes",
    "status", "answer", "runtime",
))
RUNTIME_KEYS = frozenset((
    "wall_ns", "peak_rss_bytes", "resident_tensor_bytes", "encoder_forwards",
    "dense_forwards", "reranker_forwards", "typed_lookups",
    "head_forwards", "router_forwards", "graph_traversals",
    "reader_forwards", "reader_input_tokens", "reader_output_tokens",
))
MANIFEST_KEYS = frozenset((
    "arm", "model_artifact_sha256", "shared_encoder_sha256",
    "training_groups", "calibration_groups", "head_training_steps",
    "router_training_steps", "graph_training_steps", "trained_heads",
    "split_count", "merge_count", "files",
))
MAX_INPUT = 256 * 1024 * 1024
MAX_ARTIFACT = 512 * 1024 * 1024
MAX_CONTEXT = 4096
MAX_TURNS = 8


class AdmissionError(ValueError):
    """A failed integrity, completeness or authority assertion."""


def require(predicate, reason):
    if not predicate:
        raise AdmissionError(reason)


def is_sha(value):
    return (type(value) is str and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


def _pairs_unique(pairs):
    value = {}
    for key, datum in pairs:
        require(key not in value, "duplicate JSON object key")
        value[key] = datum
    return value


def read_json(path, *, max_bytes=MAX_INPUT):
    file = Path(path)
    st = file.lstat()
    require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1
            and 0 < st.st_size <= max_bytes, "unsafe or unbounded JSON file")
    raw = file.read_bytes()
    require(len(raw) == st.st_size, "JSON changed during read")
    try:
        return json.loads(raw, object_pairs_hook=_pairs_unique,
                          parse_constant=lambda _: require(False, "nonfinite JSON"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise AdmissionError("invalid JSON: " + str(exc)) from exc


def exclusive_json(path, data):
    """Create-only, fsynced JSON; never rewrite a registered plan/seal/report."""
    b = canonical(data) + b"\n"
    path = Path(path)
    require(path.parent.is_dir() and not path.parent.is_symlink(), "unsafe output parent")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(b)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return sha(b)


def build_public_projection(source_file):
    """Trusted publisher only: omit all answers, labels, annotations and gold IDs."""
    corpora, queries, _ = load_source(source_file)
    return {
        "schema": SOURCE_SCHEMA,
        "source_sha256": SOURCE_SHA256,
        "turns": {
            group: [{"source_id": turn.source_id, "frame": turn.render()}
                    for turn in corpus.turns]
            for group, corpus in sorted(corpora.items())
        },
        "queries": {
            q.query_id: {"group": q.group, "text": q.text}
            for q in queries
        },
    }


def freeze_plan(parent, public, *, reader, tokenizer, prompt, source_frontier,
                forget_frontier, max_reader_input_tokens=1024,
                max_reader_output_tokens=64):
    """Freeze without opening gold; legacy historical cohort is NOT newly blind."""
    require(sha(canonical(parent)) == PARENT_PLAN_SHA256, "wrong parent LoCoMo plan")
    require(parent.get("source_sha256") == SOURCE_SHA256
            and parent.get("partitions") == PARTITIONS
            and len(parent.get("query_ids", [])) == 1986
            and len(set(parent["query_ids"])) == 1986, "parent plan census changed")
    require(public.get("schema") == SOURCE_SCHEMA
            and public.get("source_sha256") == SOURCE_SHA256
            and sorted(public.get("queries", {})) == sorted(parent["query_ids"]),
            "public projection missing or leaking question census")
    require(set(public.get("turns", {})) == set(sum(PARTITIONS.values(), [])),
            "public corpus source groups changed")
    require(all(is_sha(v) for v in (reader, tokenizer, prompt,
                                   source_frontier, forget_frontier)),
            "unbound reader or evidence identity")
    require(type(max_reader_input_tokens) is int and 1 <= max_reader_input_tokens <= 8192
            and type(max_reader_output_tokens) is int and 1 <= max_reader_output_tokens <= 512,
            "unbounded reader token ceiling")
    return {
        "schema": SCHEMA, "source_sha256": SOURCE_SHA256,
        "parent_plan_sha256": PARENT_PLAN_SHA256,
        "public_projection_sha256": sha(canonical(public)),
        "partitions": PARTITIONS,
        "query_ids": list(parent["query_ids"]),
        "arms": ARMS,
        "comparisons": [list(item) for item in COMPARISONS],
        "max_turns": MAX_TURNS, "max_context_bytes": MAX_CONTEXT,
        "reader_artifact_sha256": reader, "tokenizer_sha256": tokenizer,
        "prompt_sha256": prompt,
        "source_frontier_sha256": source_frontier,
        "forget_frontier_sha256": forget_frontier,
        "max_reader_input_tokens": max_reader_input_tokens,
        "max_reader_output_tokens": max_reader_output_tokens,
        "reference_dataset_previously_examined": True,
        "genuinely_future_holdout": False,
        "original_answer_correctness_available": False,
        "source_independence_authenticated": False,
        "production_activation_allowed": False,
        "authority": "DENY_ALL",
    }


def check_plan(plan, public, *, require_original=True):
    require(plan.get("schema") == SCHEMA and plan.get("arms") == ARMS
            and plan.get("comparisons") == [list(p) for p in COMPARISONS]
            and plan.get("partitions") == PARTITIONS
            and plan.get("max_turns") == MAX_TURNS
            and plan.get("max_context_bytes") == MAX_CONTEXT
            and plan.get("authority") == "DENY_ALL"
            and plan.get("production_activation_allowed") is False
            and plan.get("genuinely_future_holdout") is False
            and plan.get("original_answer_correctness_available") is False
            and plan.get("source_independence_authenticated") is False,
            "changed protocol or unjustified future/authority claim")
    require(public.get("schema") == SOURCE_SCHEMA
            and plan.get("public_projection_sha256") == sha(canonical(public))
            and plan.get("source_sha256") == public.get("source_sha256"),
            "unbound public projection")
    qids = plan.get("query_ids")
    require(type(qids) is list and len(qids) == len(set(qids))
            and sorted(qids) == sorted(public.get("queries", {})),
            "question census mismatch")
    require(is_sha(plan.get("source_frontier_sha256"))
            and is_sha(plan.get("forget_frontier_sha256"))
            and all(is_sha(plan.get(key)) for key in (
                "reader_artifact_sha256", "tokenizer_sha256", "prompt_sha256")),
            "invalid source/reader pins")
    require(type(plan.get("max_reader_input_tokens")) is int
            and 1 <= plan["max_reader_input_tokens"] <= 8192
            and type(plan.get("max_reader_output_tokens")) is int
            and 1 <= plan["max_reader_output_tokens"] <= 512,
            "invalid reader ceiling")
    if require_original:
        require(plan.get("parent_plan_sha256") == PARENT_PLAN_SHA256
                and plan.get("source_sha256") == SOURCE_SHA256
                and len(qids) == 1986
                and set(public["turns"]) == set(sum(PARTITIONS.values(), []))
                and plan.get("reference_dataset_previously_examined") is True,
                "not the independently pinned historical LoCoMo protocol")
    for qid, query in public["queries"].items():
        require(type(query) is dict and set(query) == {"group", "text"}
                and qid.startswith(query["group"] + ":qa:")
                and query["group"] in public["turns"]
                and type(query["text"]) is str and bool(query["text"].strip()),
                "invalid public query")
    for group, turns in public["turns"].items():
        require(type(turns) is list and turns and len(turns) <= 4096, "invalid source turns")
        ids = [t["source_id"] for t in turns]
        require(len(set(ids)) == len(ids)
                and all(type(t) is dict and set(t) == {"source_id", "frame"}
                        and type(t["source_id"]) is str and type(t["frame"]) is str
                        for t in turns), "bad source frame")


def check_manifests(plan, manifests, artifact_root):
    require(type(manifests) is dict and manifests.get("schema") == MANIFEST_SCHEMA
            and manifests.get("plan_sha256") == sha(canonical(plan)),
            "unbound manifest census")
    entries = manifests.get("arms")
    require(type(entries) is list and len(entries) == len(ARMS)
            and {m.get("arm") for m in entries} == set(ARMS),
            "incomplete arm artifact inventory")
    root = Path(artifact_root).resolve(strict=True)
    require(root.is_dir(), "missing actual artifact root")
    by_arm = {}
    encoder = None
    for m in entries:
        arm = m["arm"]
        require(type(m) is dict and set(m) == MANIFEST_KEYS
                and is_sha(m["model_artifact_sha256"])
                and is_sha(m["shared_encoder_sha256"]), "bad artifact manifest")
        for name in ("head_training_steps", "router_training_steps",
                     "graph_training_steps", "trained_heads", "split_count", "merge_count"):
            require(type(m[name]) is int and 0 <= m[name] <= 10_000_000,
                    "invalid observed learning/evolution count")
        train = m["training_groups"]
        cal = m["calibration_groups"]
        require(type(train) is list and type(cal) is list
                and len(train) == len(set(train)) and len(cal) == len(set(cal))
                and set(train) <= set(PARTITIONS["development"])
                and set(cal) <= set(PARTITIONS["calibration"])
                and not set(train) & set(cal)
                and not set(train) & set(PARTITIONS["evaluation"]),
                "training/calibration/test group contamination")
        if arm in "ABCD":
            require(m["head_training_steps"] == 0 and m["router_training_steps"] == 0
                    and m["graph_training_steps"] == 0 and m["split_count"] == 0
                    and m["merge_count"] == 0, "untrained arm contains local updates")
        if arm in "EFGHI":
            require(m["head_training_steps"] > 0 and m["trained_heads"] >= (2 if arm in "FGHI" else 1),
                    "required trained Cell Head evidence absent")
            require(train, "training sources absent")
            if encoder is None:
                encoder = m["shared_encoder_sha256"]
            require(encoder == m["shared_encoder_sha256"], "E-I do not share the Encoder")
        if arm in "GHI":
            require(m["router_training_steps"] > 0, "required real Router training absent")
        if arm in "HI":
            require(m["graph_training_steps"] > 0, "required learned graph absent")
        if arm == "I":
            require(m["split_count"] > 0 and m["merge_count"] > 0,
                    "split and merge must both be executed, not proposed only")
        files = m["files"]
        require(type(files) is list and files and len(files) <= 128,
                "no physical model/plan files")
        seen = set()
        for item in files:
            require(type(item) is dict and set(item) == {"path", "sha256", "bytes"}
                    and type(item["path"]) is str and item["path"] not in seen
                    and is_sha(item["sha256"])
                    and type(item["bytes"]) is int and 0 < item["bytes"] <= MAX_ARTIFACT,
                    "unbound model bytes")
            seen.add(item["path"])
            relative = Path(item["path"])
            require(not relative.is_absolute() and ".." not in relative.parts,
                    "artifact escapes root")
            full = root / relative
            require(full.resolve(strict=True).is_relative_to(root), "artifact path outside root")
            st = full.lstat()
            require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1
                    and st.st_size == item["bytes"], "artifact not a regular pinned file")
            require(sha(full.read_bytes()) == item["sha256"], "artifact changed")
        # The manifest's model binding is a digest of its complete physical inventory.
        require(m["model_artifact_sha256"] == sha(canonical(files)),
                "model binding disagrees with the physical inventory")
        by_arm[arm] = m
    return by_arm


def _iter_attempts(file):
    path = Path(file)
    st = path.lstat()
    require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1
            and 0 < st.st_size <= MAX_INPUT, "missing/unbounded attempt journal")
    with path.open("rb") as stream:
        for number, raw in enumerate(stream, 1):
            require(0 < len(raw) <= 64 * 1024 and raw.endswith(b"\n"),
                    "unframed or oversized row")
            try:
                row = json.loads(raw, object_pairs_hook=_pairs_unique,
                                 parse_constant=lambda _: require(False, "nonfinite JSON"))
            except (ValueError, UnicodeDecodeError) as exc:
                raise AdmissionError(f"bad row {number}: {exc}") from exc
            require(type(row) is dict, "non-object journal row")
            yield row


def validate_attempts(plan, public, manifests, artifact_root, attempts, *,
                      require_original=True):
    """Pure verification: no gold passed to, opened by, or needed by this function."""
    check_plan(plan, public, require_original=require_original)
    by_arm = check_manifests(plan, manifests, artifact_root)
    rosters = {g: {t["source_id"]: t["frame"] for t in turns}
               for g, turns in public["turns"].items()}
    seen, rows = set(), []
    totals = {a: {k: 0 for k in RUNTIME_KEYS} for a in ARMS}
    plan_sha = sha(canonical(plan))
    for row in _iter_attempts(attempts):
        require(set(row) == ROW_KEYS and row.get("schema") == ROW_SCHEMA
                and row.get("plan_sha256") == plan_sha
                and row.get("arm") in ARMS and row.get("query_id") in public["queries"],
                "unknown/forged row, arm or plan")
        arm, qid = row["arm"], row["query_id"]
        key = (arm, qid)
        require(key not in seen, "duplicate prediction")
        seen.add(key)
        group = public["queries"][qid]["group"]
        require(row["group"] == group and row["model_artifact_sha256"]
                == by_arm[arm]["model_artifact_sha256"]
                and row["source_frontier_sha256"] == plan["source_frontier_sha256"]
                and row["forget_frontier_sha256"] == plan["forget_frontier_sha256"],
                "wrong group, model, source or forget frontier")
        selected = row["selected_ids"]
        require(type(selected) is list and len(selected) <= MAX_TURNS
                and len(set(selected)) == len(selected)
                and all(type(source_id) is str and source_id in rosters[group]
                        for source_id in selected), "unknown or duplicate evidence reference")
        actual_context = "".join(rosters[group][x] for x in selected).encode()
        require(row["context_sha256"] == sha(actual_context)
                and type(row["context_bytes"]) is int
                and row["context_bytes"] == len(actual_context) <= MAX_CONTEXT,
                "forged or over-budget Reader context")
        require(row["reader_artifact_sha256"] == plan["reader_artifact_sha256"]
                and row["reader_request_digest"] == sha(canonical({
                    "domain": "hepta.memory-nine-arm-reader-request.v1",
                    "query_id": qid,
                    "question": public["queries"][qid]["text"],
                    "context_sha256": row["context_sha256"],
                    "reader": plan["reader_artifact_sha256"],
                    "tokenizer": plan["tokenizer_sha256"],
                    "prompt": plan["prompt_sha256"],
                })), "Reader/prompt/context binding drift")
        require(row["status"] in ("accepted", "abstained", "unavailable")
                and type(row["answer"]) is str and len(row["answer"].encode()) <= 16_384
                and (bool(row["answer"].strip()) if row["status"] == "accepted"
                     else row["answer"] == ""), "invalid model output/abstention")
        runtime = row["runtime"]
        require(type(runtime) is dict and set(runtime) == RUNTIME_KEYS
                and all(type(x) is int and 0 <= x <= (1 << 62)
                        for x in runtime.values()), "missing/invalid physical resource counters")
        require(runtime["wall_ns"] > 0 and runtime["peak_rss_bytes"] > 0
                and runtime["reader_input_tokens"] <= plan["max_reader_input_tokens"]
                and runtime["reader_output_tokens"] <= plan["max_reader_output_tokens"]
                and runtime["reader_forwards"] == (1 if row["status"] == "accepted" else 0)
                and (runtime["reader_output_tokens"] > 0 if row["status"] == "accepted"
                     else runtime["reader_output_tokens"] == 0), "Reader/cost receipt mismatch")
        if arm == "A":
            require(not any(runtime[x] for x in (
                "dense_forwards", "reranker_forwards", "typed_lookups",
                "head_forwards", "router_forwards", "graph_traversals")),
                "BM25 included a different architecture")
        if arm in "EFGHI":
            require(runtime["head_forwards"] > 0 or row["status"] == "unavailable",
                    "trained Head never invoked")
        if arm in "GHI":
            require(runtime["router_forwards"] > 0 or row["status"] == "unavailable",
                    "learned Router never invoked")
        for k in RUNTIME_KEYS:
            totals[arm][k] += runtime[k]
        rows.append(row)
    require(len(seen) == len(ARMS) * len(public["queries"]),
            "not all nine arms executed every question")
    for arm, key_list in {
        "B": ("dense_forwards", "reranker_forwards"),
        "C": ("graph_traversals",),
        "D": ("typed_lookups",),
        "E": ("head_forwards",),
        "F": ("head_forwards",),
        "G": ("router_forwards",),
        "H": ("graph_traversals", "router_forwards"),
        "I": ("graph_traversals", "router_forwards"),
    }.items():
        require(all(totals[arm][k] > 0 for k in key_list),
                "required architecture physically absent: " + arm)
    return rows, totals


def seal(plan, public, manifests, artifact_root, attempts, destination, *,
         require_original=True):
    rows, totals = validate_attempts(plan, public, manifests, artifact_root,
                                     attempts, require_original=require_original)
    # No gold is loaded, opened or returned by this process.
    data = {
        "schema": SEAL_SCHEMA,
        "plan_sha256": sha(canonical(plan)),
        "public_projection_sha256": sha(canonical(public)),
        "artifact_manifest_sha256": sha(canonical(manifests)),
        "attempts_sha256": sha(Path(attempts).read_bytes()),
        "question_arm_rows": len(rows),
        "resource_totals": totals,
        "gold_opened": False,
        "model_outputs_independently_reexecuted": False,
        "production_activation_allowed": False,
    }
    exclusive_json(destination, data)
    return data


def _signflip_exact(deltas):
    """Descriptive paired source-group test; no independence warranty."""
    n = len(deltas)
    require(1 <= n <= 16, "unbounded or missing paired groups")
    actual = statistics.fmean(deltas)
    count = sum(statistics.fmean(s * d for s, d in zip(signs, deltas))
                >= actual - 1e-12
                for signs in itertools.product((-1, 1), repeat=n))
    return count / (1 << n)


def _bootstrap_ci(deltas, seed, draws=2048):
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(deltas, k=len(deltas)))
                   for _ in range(draws))
    return [means[int(0.025 * draws)], means[int(0.975 * draws) - 1]]


def adjudicate(plan, public, manifests, artifact_root, attempts, sealed, source,
               *, require_original=True):
    """Gold may be read only after the externally persisted no-gold seal exists."""
    seal_record = read_json(sealed)
    require(seal_record.get("schema") == SEAL_SCHEMA
            and seal_record.get("gold_opened") is False
            and seal_record.get("attempts_sha256") == sha(Path(attempts).read_bytes())
            and seal_record.get("plan_sha256") == sha(canonical(plan))
            and seal_record.get("public_projection_sha256") == sha(canonical(public))
            and seal_record.get("artifact_manifest_sha256") == sha(canonical(manifests))
            and seal_record.get("gold_opened") is False
            and seal_record.get("model_outputs_independently_reexecuted") is False
            and seal_record.get("production_activation_allowed") is False,
            "sealed predictions or bindings changed")
    rows, totals = validate_attempts(plan, public, manifests, artifact_root,
                                     attempts, require_original=require_original)
    require(seal_record.get("resource_totals") == totals
            and seal_record.get("question_arm_rows") == len(rows)
            and seal_record.get("attempts_sha256") == sha(Path(attempts).read_bytes()),
            "postseal resource census, row count or attempt bytes drift")
    corpora, queries, gold = load_source(source)
    expected_public = {
        "schema": SOURCE_SCHEMA, "source_sha256": SOURCE_SHA256,
        "turns": {
            group: [{"source_id": t.source_id, "frame": t.render()}
                    for t in corpus.turns]
            for group, corpus in sorted(corpora.items())
        },
        "queries": {
            q.query_id: {"group": q.group, "text": q.text} for q in queries
        },
    }
    require(sha(canonical(public)) == sha(canonical(expected_public)),
            "public projection differs from immutable source")
    queries_by_id = {q.query_id: q for q in queries}
    scored = {a: [] for a in ARMS}
    for row in rows:
        qid = row["query_id"]
        scored[row["arm"]].append(score_query(
            queries_by_id[qid], gold[qid], row["selected_ids"],
            accepted=(row["status"] == "accepted")))
    per_arm = {a: summarize([r for r in scored[a]
                             if r["group"] in PARTITIONS["evaluation"]]) for a in ARMS}
    # Retain every question including unavailable/adversarial/missing annotations.
    by_id = {a: {r["query_id"]: r for r in scored[a]
                 if r["group"] in PARTITIONS["evaluation"]} for a in ARMS}
    p_values, entries = [], []
    for left, right in COMPARISONS:
        require(set(by_id[left]) == set(by_id[right]), "unpaired test question")
        grouped = defaultdict(list)
        for qid in sorted(by_id[left]):
            x, y = by_id[left][qid], by_id[right][qid]
            require((x["group"], x["category"], x["annotation_status"],
                     x["gold_evidence_count"], x["unresolved_evidence"]) ==
                    (y["group"], y["category"], y["annotation_status"],
                     y["gold_evidence_count"], y["unresolved_evidence"]),
                    "attempted unequal gold/denominator comparison")
            if x["all_support_recalled"] is not None:
                grouped[x["group"]].append(
                    x["all_support_recalled"] - y["all_support_recalled"])
        deltas = [statistics.fmean(grouped[g]) for g in PARTITIONS["evaluation"]
                  if grouped[g]]
        require(len(deltas) == len(PARTITIONS["evaluation"]),
                "missing heldout source group in paired comparison")
        p = _signflip_exact(deltas)
        p_values.append(p)
        entries.append({
            "left": left, "right": right,
            "paired_source_groups": len(deltas),
            "group_macro_difference": statistics.fmean(deltas),
            "descriptive_percentile_95_interval": _bootstrap_ci(
                deltas, 20261023 + len(entries)),
            "one_sided_exact_signflip_p_unadjusted": p,
        })
    # Holm family-wise adjustment over the COMPLETE preregistered family.
    adjusted = [0.0] * len(entries)
    maximum = 0.0
    for rank, index in enumerate(sorted(range(len(p_values)),
                                        key=lambda i: (p_values[i], i))):
        maximum = max(maximum, min(1.0, (len(p_values) - rank) * p_values[index]))
        adjusted[index] = maximum
    for entry, p in zip(entries, adjusted):
        entry["holm_adjusted_p"] = p
        entry["descriptive_only"] = True
    return {
        "schema": "hepta.memory-nine-arm-adjudication.v1",
        "plan_sha256": sha(canonical(plan)),
        "sealed_attempts_sha256": seal_record["attempts_sha256"],
        "arms": per_arm, "comparisons": entries,
        "physical_resource_totals_self_reported": totals,
        "matched_total_resource_cost_verified": False,
        "evaluation_question_census": sum(q.group in PARTITIONS["evaluation"] for q in queries),
        "independent_source_groups": 6,
        "answer_correctness_measured": False,
        "semantic_citation_entailment_measured": False,
        "reader_outputs_independently_reexecuted": False,
        "physical_cost_independently_attested": False,
        "future_time_windows": 0,
        "superiority_established": False,
        "production_activation_allowed": False,
        "authority": "DENY_ALL",
        "decision": "HOLD_NO_GO",
        "blockers": [
            "historical dataset already examined; no independent future windows",
            "only six unauthenticated source-family groups",
            "semantic Reader correctness and citation entailment not scored",
            "physical model/training/resource evidence lacks independent reexecution",
            "causal lesion, forgetting, and production authority unqualified",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    project = commands.add_parser("project")
    project.add_argument("--original", required=True)
    project.add_argument("--output", required=True)
    freeze = commands.add_parser("freeze")
    freeze.add_argument("--parent-plan", required=True)
    freeze.add_argument("--public", required=True)
    for name in ("reader", "tokenizer", "prompt", "source-frontier", "forget-frontier"):
        freeze.add_argument("--" + name, required=True)
    freeze.add_argument("--output", required=True)
    for name in ("seal", "score"):
        sub = commands.add_parser(name)
        for field in ("plan", "public", "manifests", "artifact-root", "attempts", "output"):
            sub.add_argument("--" + field, required=True)
        if name == "score":
            sub.add_argument("--sealed", required=True)
            sub.add_argument("--original", required=True)
    args = parser.parse_args()
    if args.command == "project":
        exclusive_json(args.output, build_public_projection(args.original))
    elif args.command == "freeze":
        plan = freeze_plan(
            read_json(args.parent_plan), read_json(args.public),
            reader=args.reader, tokenizer=args.tokenizer, prompt=args.prompt,
            source_frontier=args.source_frontier, forget_frontier=args.forget_frontier)
        exclusive_json(args.output, plan)
    else:
        plan, public = read_json(args.plan), read_json(args.public)
        manifests = read_json(args.manifests)
        if args.command == "seal":
            seal(plan, public, manifests, args.artifact_root,
                 args.attempts, args.output)
        else:
            result = adjudicate(
                plan, public, manifests, args.artifact_root, args.attempts,
                args.sealed, args.original)
            exclusive_json(args.output, result)
            print(canonical({"decision": result["decision"],
                             "blockers": result["blockers"]}).decode())


if __name__ == "__main__":
    main()
