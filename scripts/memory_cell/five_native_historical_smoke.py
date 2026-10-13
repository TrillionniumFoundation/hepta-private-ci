"""Historical real-weight smoke for the five-causal native backends.

Only the EXTERNALLY PINNED existing GitHub model/data artifact is accepted.
This diagnostic has no human-sufficient arm, independent review, new cohort,
causal efficacy verdict or production admission. It never fabricates these.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import time
import zipfile

import torch

import five_causal_experiments as contract
from five_causal_native import (
    NativeSession, SCHEMA, SYSTEM, public_text, reader_bindings, tokenizer_binding,
    train_heads,
)
from experiments.shared_stem_cell.execution import LocalTextGenerator, measured

ARCHIVE_SHA256 = "07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af"
ARTIFACT_ID = 11586991191
PACKAGING_COMMIT = "4e996a707a7717152ab36cccaed901c4bd8248a2"
LOCOMO_SHA256 = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
ENCODER_INVENTORY = "5afecdd6098fec07380bc10a30fd8debcffcd147274b3ffd18143f1fa86dc12a"
READER_INVENTORY = "afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c"


def require(ok, reason):
    contract.require(ok, reason)


def extract(archive, output):
    require(contract.file_sha(archive) == ARCHIVE_SHA256, "external original artifact SHA mismatch")
    output.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        require(len(names) == len(set(names)) and len(names) <= 100, "outer archive census")
        tar_names = [n for n in names if n.endswith(".tar.gz")]
        require(len(tar_names) == 1, "one original material tar required")
        info = z.getinfo(tar_names[0])
        require(info.file_size <= 1024**3, "tar too large")
        target = output / "original-material.tar.gz"
        with z.open(tar_names[0]) as source, target.open("xb") as dest:
            import shutil
            shutil.copyfileobj(source, dest)
    with tarfile.open(target) as tar:
        members = tar.getmembers()
        require(len(members) <= 10000 and sum(m.size for m in members) <= 2*1024**3, "material bound")
        names = set()
        for member in members:
            path = PurePosixPath(member.name)
            require(path.parts and not path.is_absolute() and ".." not in path.parts
                    and path.parts[0] == "memory-inputs" and (member.isfile() or member.isdir())
                    and path.as_posix() not in names, "unsafe/duplicate material entry")
            names.add(path.as_posix())
        tar.extractall(output, members=members, filter="data")
    return output / "memory-inputs"


def inventory(path):
    return {p.relative_to(path).as_posix(): {"sha256": contract.file_sha(p), "bytes": p.stat().st_size}
            for p in sorted(path.rglob("*")) if p.is_file() and ".cache" not in p.parts}


def snapshot(path, kind, expected_inventory):
    observed = inventory(path)
    require(contract.digest(observed) == expected_inventory, "original model/tokenizer inventory drift")
    require(not any(p.is_symlink() for p in path.rglob("*")), "linked original model")
    require(not any(p.is_file() and ".cache" in p.parts for p in path.rglob("*")),
            "unqualified cache files in archived model snapshot")
    # This revision identifies the immutable ARCHIVE PACKAGING source, NOT a
    # claimed Hub revision. Original weight/tokenizer hashes are the model pin.
    return {"kind": kind, "revision": PACKAGING_COMMIT,
            "revision_semantics": "github-artifact-packaging-source-not-hub-model-revision",
            "files": {k: v["sha256"] for k, v in observed.items()},
            "original_inventory_sha256": expected_inventory}


def store_bundle(root, manifest):
    raw = contract.canonical(manifest)
    digest = hashlib.sha256(raw).hexdigest()
    folder = root / "bundles"
    folder.mkdir(exist_ok=True)
    with (folder / (digest + ".json")).open("xb") as f:
        f.write(raw)
    return digest


def select_history(path, *, count=4):
    """Freeze natural question identities BEFORE reading target annotations.

    Selection uses only question text/identity/scope and deterministic digest.
    This reuses a historical benchmark and does NOT declare unseen tasks.
    """
    from native import load
    benchmark = load(path, "locomo", expected_sha256=LOCOMO_SHA256,
                     allow_unresolved_evidence=True)
    chosen = sorted(benchmark.questions, key=lambda q: contract.digest(q.identity))[:count]
    plan = [{"id": q.identity, "scope": q.scope, "family": q.family, "question": q.content}
            for q in chosen]
    return benchmark, chosen, plan


def requests_for_question(benchmark, query):
    """Oracle source-support is NOT human sufficiency or multi-hop entailment."""
    target = benchmark.targets[query.identity]
    history = list(benchmark.history(query))
    # Source labels are used only to define the diagnostic oracle intervention,
    # never transmitted to the Reader or called an independent sufficient set.
    supported = [d for d in history if d.identity in set(target.evidence)]
    terms = set(query.content.casefold().split())
    ordinary = sorted(history, key=lambda d: (-len(terms.intersection(d.content.casefold().split())), d.identity))[:3]
    def public(docs):
        return {"question": query.content, "options": [], "evidence": [
            {"id": "E"+str(i+1), "modality": "text", "text": d.content,
             "asset_sha256": None, "position": i} for i, d in enumerate(docs)]}
    return {"no_evidence": public([]), "lexical_retrieval": public(ordinary),
            "oracle_source_support": public(supported), "oracle_support_group_removed": public([])}, supported


def run(archive, output):
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    frozen = {"schema": "hepta.five-native.historical-smoke-plan.v1", "archive_sha256": ARCHIVE_SHA256,
              "artifact_id": ARTIFACT_ID, "packaging_commit": PACKAGING_COMMIT,
              "data_kind": "previously_exposed_public_development", "reader_questions": 4,
              "reader_maximum_tokens": 2048, "reader_maximum_new_tokens": 64,
              "training_steps": 32, "training_records": 32,
              "reader_review_generated": False, "production_accepted": False}
    contract.write_new(output / "plan.json", frozen)
    try:
        with measured() as acquisition:
            root = extract(archive, output / "staged")
        enc = snapshot(root / "encoder", "encoder", ENCODER_INVENTORY)
        reader = snapshot(root / "reader", "causal_lm", READER_INVENTORY)
        matches = [p for p in root.rglob("*.json") if p.stat().st_size > 50000
                   and contract.file_sha(p) == LOCOMO_SHA256]
        require(len(matches) == 1, "exact historical LoCoMo material missing/ambiguous")
        benchmark, queries, selection = select_history(matches[0])
        contract.write_new(output / "selected-public-questions.json", selection)
        session = NativeSession(root)
        # Tokenizer reads only the pinned local snapshot. Model is loaded once
        # by the actual NativeSession; no warm-up model discarded off-account.
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(root / "reader", local_files_only=True, trust_remote_code=False)
        binding = {k: contract.digest("not-applicable:"+k) for k in contract.BINDINGS}
        binding.update(reader_bindings(reader, tokenizer.chat_template, 2048, 64))
        manifest = {"schema": SCHEMA, "kind": "reader", "sharing": "shared",
                    "scope": "historical-diagnostic", "purpose": "development", "generation": "frozen-v1", "cell": "reader",
                    "model_path": "reader", "snapshot": reader, "maximum_tokens": 2048,
                    "maximum_new_tokens": 64, "bindings": binding}
        checkpoint = store_bundle(root, manifest)
        previous, records = "0"*64, []
        with (output / "raw-reader.jsonl").open("xb") as stream:
            for query in queries:
                requests, support = requests_for_question(benchmark, query)
                for arm, request in sorted(requests.items(), key=lambda pair: contract.digest([query.identity, pair[0]])):
                    trial = contract.digest([query.identity, arm])
                    packet = {"request": request, "checkpoint_sha256": checkpoint,
                              "bindings": binding, "timeout_seconds": 120}
                    request_sha = contract.digest(packet)
                    previous = contract.journal_append(stream, {"event": "started", "trial_id": trial,
                                                        "request_sha256": request_sha}, previous)
                    row = {"event": "finished", "trial_id": trial, "request_sha256": request_sha,
                           "question_id": query.identity, "condition": arm,
                           "source_support_count": len(support), "source_support_is_human_sufficiency": False,
                           "status": "failed", "result": None}
                    at = time.perf_counter()
                    try:
                        row["result"] = session.answer(packet, arm="fixed-historical-reader")
                        row["status"] = "succeeded"
                    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
                        row["error"] = type(error).__name__ + ": " + str(error)[:512]
                    row["wall_seconds_including_process_start"] = time.perf_counter()-at
                    if row["wall_seconds_including_process_start"] > 120:
                        row["status"] = "timeout"
                    previous = contract.journal_append(stream, row, previous)
                    records.append(row)
        raw_sha = contract.file_sha(output / "raw-reader.jsonl")
        contract.write_new(output / "raw-seal.json", {"raw_sha256": raw_sha, "tail": previous, "planned": 16})
        reader_resources = session.close()
        contract.write_new(output / "reader-resources.json", reader_resources)
        # Only AFTER raw output sealing: exact-answer diagnostic. No paraphrase
        # judge, sufficiency label or positive qualification is manufactured.
        scores = []
        for row in records:
            target = benchmark.targets[row["question_id"]]
            answer = row["result"]["answer"] if row["status"] == "succeeded" else None
            scores.append({"trial_id": row["trial_id"], "condition": row["condition"],
                           "status": row["status"], "exact_answer": bool(answer is not None and answer.strip() == str(target.answer).strip()),
                           "exact_refusal": bool(answer is not None and answer.strip() == "I do not have enough evidence."),
                           "independent_semantic_judgment": None})
        contract.write_new(output / "reader-diagnostic-scores.json", {"raw_sha256": raw_sha, "rows": scores})
        # Actual train-only Head optimization using benchmark category labels.
        # Category prediction is explicitly NOT evidence ranking/Reader ability.
        selected = sorted([q for q in benchmark.questions if q.scope == queries[0].scope],
                          key=lambda q: contract.digest(q.identity))[:32]
        categories = sorted({str(benchmark.targets[q.identity].category) for q in selected})
        require(len(categories) >= 2, "category training lacks two classes")
        training = {"schema": "hepta.five-native.training.v1", "data_kind": "historical_development",
                    "model_path": "encoder", "snapshot": enc, "maximum_tokens": 512,
                    "steps": 32, "seed": 20261013, "head_kind": "gated", "rows": [
                        {"id": contract.digest(q.identity), "cell": "category", "scope": "historical-one-source",
                         "split": "train", "request": {"question": q.content, "options": categories, "evidence": []},
                         "label": categories.index(str(benchmark.targets[q.identity].category))} for q in selected]}
        trained = train_heads(training, root, output / "head-training")
        result = {"schema": "hepta.five-native.historical-result.v1", "raw_sha256": raw_sha,
                  "reader_planned": 16, "reader_successes": sum(r["status"] == "succeeded" for r in records),
                  "reader_failures": sum(r["status"] != "succeeded" for r in records),
                  "reader_actual_forward_calls": sum(c["model_calls"] for c in reader_resources["calls"]),
                  "head_encoder_calls": trained["encoder_forward_calls"], "head_training_steps": 32,
                  "actual_head_parameter_change": trained["cells"][0]["models"]["trained"]["sha256"] != trained["cells"][0]["models"]["frozen"]["sha256"],
                  "acquisition_cost": acquisition, "total_wall_seconds": time.perf_counter()-started,
                  "independent_unseen_task_evidence": False, "reader_adequacy_established": False,
                  "sharing_superiority": False, "five_experiments_completed": False, "production_accepted": False}
        contract.write_new(output / "result.json", result)
        require(result["reader_failures"] == 0, "historical smoke has failed Reader attempts; retained, not skipped")
        require(result["reader_actual_forward_calls"] > 0 and result["head_encoder_calls"] > 0
                and result["actual_head_parameter_change"], "real inference/training not observed")
        return result
    except Exception as error:
        contract.write_new(output / "failure.json", {"error_type": type(error).__name__, "error": str(error)[:2048],
                            "total_wall_seconds": time.perf_counter()-started,
                            "model_efficacy_established": False, "production_accepted": False})
        raise


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    print(json.dumps(run(a.archive, a.output), sort_keys=True))
