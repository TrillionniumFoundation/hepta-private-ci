"""Independent, offline verification of fixed, completed MemoryCell stem archive.

No weights, model calls, learned-state mutation, semantic judgment or authority.
Prints a bounded JSON receipt; never interprets execution success as accuracy.
"""
import collections
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import zipfile

PIN = "1db7f8f7c13a1f718d5065956f14d554d3fe328c415fac4bb145d1eaf9d913c8"
SOURCE = "675970bb610c70bb0ec30a2dee05c025440510e6"
TREE = "d280ba53070fb6457c04ff0d97fbb14ebbdbc3fb"
ARMS = ("frozen_rerank", "prototype", "linear", "gated", "lineage_lora_gated", "independent_lora_gated")
PHASES = ("select", "retention", "test", "transfer")
STAGES = (16, 32, 48)
CHECK_FIELDS = ("answer", "status", "selected", "receipt", "family", "cell", "pool_digest", "feature_digest", "head_sha256", "encoder_identity")


def verify(path):
    path = Path(path)
    assert path.is_file() and not path.is_symlink()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == PIN, "outer artifact mismatch"
    with zipfile.ZipFile(path) as z:
        files = z.infolist()
        assert len(files) == 131 and sum(i.file_size for i in files) < 64 * 1024**2
        names = [i.filename for i in files]
        assert len(names) == len(set(names))
        assert all(not PurePosixPath(n).is_absolute() and ".." not in PurePosixPath(n).parts and "\\" not in n and not stat.S_ISLNK(i.external_attr >> 16) for i, n in zip(files, names))
        manifest = {}
        for line in z.read("SHA256SUMS").decode().splitlines():
            m = re.fullmatch(r"([a-f0-9]{64})  (?:\./)?(.+)", line)
            assert m is not None
            sha, name = m.groups()
            assert name not in manifest
            manifest[name] = sha
        assert len(manifest) == 130 and set(manifest) == set(names) - {"SHA256SUMS"}
        for name, sha in manifest.items():
            h = hashlib.sha256()
            with z.open(name) as stream:
                for piece in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(piece)
            assert h.hexdigest() == sha, f"member differs: {name}"
        assert z.read("tested-commit.txt").decode().strip() == SOURCE
        assert z.read("tested-tree.txt").decode().strip() == TREE
        plan = json.loads(z.read("comparison/preregistered.json"))
        report = json.loads(z.read("comparison/report.json"))
        scored = json.loads(z.read("comparison/scored-policy-attempts.json"))
        raw = [json.loads(line) for line in z.read("comparison/policy-predictions.jsonl").decode().splitlines()]
        fit = json.loads(z.read("comparison/within-head-train-fit.json"))
        ceiling = json.loads(z.read("comparison/post-policy-native-source-ceiling.json"))
        empty = [json.loads(line) for line in z.read("comparison/reader-no-evidence.jsonl").decode().splitlines()]
        assert plan["source_commit"] == SOURCE
        assert tuple(plan["arms"]) == ARMS
        assert tuple(plan["curriculum_attempted_examples"]) == STAGES
        cohorts = plan["questions"]
        assert len(cohorts["train"]) == 48
        assert all(len(cohorts[x]) == 8 for x in PHASES)
        assert report["census"] == {"planned": 576, "recorded": 576, "complete": True}
        assert report["logical_policy_attempts"] == 576
        assert report["semantic_citation_precision"] is None
        assert report["production_accepted"] is False
        assert len(scored) == len(raw) == 576
        def key(r): return (r["stage"], r["phase"], r["question_id"], r["arm"])
        raw_idx = {}
        for r in raw:
            k = key(r)
            assert k not in raw_idx and r["status"] == "succeeded" and isinstance(r["answer"], str)
            raw_idx[k] = r
        assert len(raw_idx) == 576
        expected_keys = {(stage, phase, q, arm) for stage in STAGES for phase in PHASES for q in cohorts[phase] for arm in ARMS}
        assert set(raw_idx) == expected_keys
        for s in scored:
            k = key(s)
            r = raw_idx.pop(k)
            assert all(s[n] == r[n] for n in CHECK_FIELDS), f"scorer mutated raw prediction: {k}"
            assert s["citation_structure"]["semantic_precision"] is None
            assert s["citation_structure"]["markers"] == 0
            assert s["source_choice_correct"] in (0, 1)
        assert not raw_idx
        by_key = {(r["stage"], r["phase"], r["question_id"], r["arm"]): r for r in scored}
        phases = {}
        flips = []
        for phase in PHASES:
            n = sum(r["phase"] == phase for r in scored)
            changed = []
            for row in scored:
                if row["phase"] != phase or row["arm"] == "frozen_rerank":
                    continue
                if row["selection_geometry"]["changed_selected_candidate"]:
                    frozen = by_key[row["stage"], row["phase"], row["question_id"], "frozen_rerank"]
                    item = {"stage": row["stage"], "phase": phase, "arm": row["arm"], "question_id": row["question_id"], "frozen_weak_source": frozen["source_choice_correct"], "learned_weak_source": row["source_choice_correct"], "same_answer": row["answer"] == frozen["answer"]}
                    changed.append(item)
                    flips.append(item)
            phases[phase] = {"executed_policy_rows": n, "learned_policy_rows": 5 * 8 * 3, "changed_selection_rows": len(changed), "correct_source_gains": sum(x["frozen_weak_source"] == 0 and x["learned_weak_source"] == 1 for x in changed), "original_frozen_correct_per_checkpoint": sum(r["source_choice_correct"] for r in scored if r["phase"] == phase and r["stage"] == 48 and r["arm"] == "frozen_rerank")}
        assert len(flips) == 1 and flips[0]["stage"] == 48 and flips[0]["phase"] == "retention"
        assert flips[0]["frozen_weak_source"] == flips[0]["learned_weak_source"] == 0
        assert flips[0]["same_answer"]
        assert not phases["test"]["changed_selection_rows"] and not phases["transfer"]["changed_selection_rows"]
        assert len(fit["checkpoints"]) == 30
        assert len(ceiling["decisions"]) == 32
        assert len(empty) == 32 and all(x["status"] == "succeeded" for x in empty)
        actual = report["reader"]
        assert actual["actual_attempts"] == actual["actual_successes"] == 44
        assert actual["actual_failed_attempts"] == 0 and actual["cache_hits"] == 543
        assert all(r["citation_structure"]["markers"] == 0 for r in scored)
        support = {}
        for phase in PHASES:
            rows = [d for d in ceiling["decisions"] if d["phase"] == phase]
            assert len(rows) == 8
            support[phase] = {"native_answerable": sum(d["weak_native_support_resolved"] for d in rows), "support_absent_from_candidate_pool": sum(d["weak_native_support_resolved"] and d["candidate_pool_available"] and d["native_support_available_in_pool"] is False for d in rows), "frozen_top1_missed_present_support": sum(d["missed_native_support_within_pool"] is True for d in rows)}
        return {"schema":"hepta.memorycell.independent-strict-native-census.v1", "source_commit":SOURCE, "source_tree":TREE, "workflow_run":38114716982, "artifact_id":11693693993, "zip_sha256":PIN, "verified_inner_sha256_members":len(manifest), "preregistered_policy_rows":576, "executed_policy_rows":len(scored), "all_policy_calls_succeeded":True, "distinct_model_reader_executions":actual["actual_attempts"], "actual_reader_successes":actual["actual_successes"], "cached_reader_reuses":actual["cache_hits"], "isolated_no_evidence_model_calls":len(empty), "citation_markers":0, "semantic_citation_precision":None, "phases":phases, "changed_selection_details":flips, "posthoc_native_source_ceiling":support, "heldout_or_prospective_generalization_established":False, "parameter_memory_superiority_established":False, "production_accepted":False, "no_new_model_execution_by_this_audit":True}


if __name__ == "__main__":
    if len(sys.argv) not in (2,3):
        sys.exit("usage: verify_memorycell_native_576.py ARCHIVE.zip [receipt.json]")
    receipt = verify(sys.argv[1])
    payload = json.dumps(receipt, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if len(sys.argv) == 3:
        out=Path(sys.argv[2])
        with out.open('x',encoding='utf-8') as f: f.write(payload)
    print(payload)
