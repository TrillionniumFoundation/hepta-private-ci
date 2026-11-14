#!/usr/bin/env python3
"""Independent standard-library replay of the pinned 112-call MemoryCell Qwen archive.

Checks source/reader lineage, whole ZIP manifests, raw->scored immutability,
exact original evidence bytes, unmodified answers, deterministic program tasks,
top-k selection, matched costs, citation-support counts and paired contrasts.
No model weights or answers are generated. Does NOT certify entailment,
chronological independence, source-family independence or production acceptance.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
import zipfile

MODEL_ZIP = "7a99db30fb5b1202fcd43073d22589b84315046dd34044277cc46351f1cbece8"
ORIGINAL_ZIP = "23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b"
GENERATOR = "6304b451268c73f3d1a605985226b102df841bbf"
PLAN_SHA = "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897"
KS = (1, 2, 3, 4, 6)
EVAL_ARMS = (
    "selected_k", "hybrid_k4", "hybrid_k6", "hybrid_k4_reversed", "single_hop",
    "entity_time", "organized", "program_support", "empty",
)
CORRECT_FIELDS = {"parsed_identifier", "strict_task_success", "required_sources_covered", "procedure_verification"}
RESPONSE = re.compile(r"\s*((?:site|mode)_[0-9a-f]{8})(?:\s*\[E[1-9][0-9]*\])*\s*\.?\s*\Z")
CITATION = re.compile(r"\[E([1-9][0-9]*)\]")
VIEW = "hepta.controlled-event.schema-expansion.v1"
ROOT_PROFILE = "hepta.memory-benchmark.source-root.v1"


def fail(msg):
    raise ValueError(msg)


def sha(buf):
    return hashlib.sha256(buf).hexdigest()


def digest(value):
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())


def strict_json(raw):
    def unique(pairs):
        data = {}
        for k, v in pairs:
            if k in data:
                fail("duplicate JSON key " + k)
            data[k] = v
        return data
    return json.loads(raw, object_pairs_hook=unique, parse_constant=lambda x: fail("nonfinite JSON " + x))


def verify_zip(path, expected, expected_count):
    actual = sha(path.read_bytes())
    assert actual == expected, (path.name, actual)
    docs = {}
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        assert 0 < len(infos) < 256
        assert sum(i.file_size for i in infos) < 20_000_000
        for info in infos:
            pn = PurePosixPath(info.filename)
            assert not pn.is_absolute() and ".." not in pn.parts and not info.is_dir()
            assert not stat.S_ISLNK(info.external_attr >> 16)
            name = str(pn)
            assert name not in docs
            docs[name] = z.read(info)
    manifest = docs.pop("SHA256SUMS").decode().splitlines()
    pins = {}
    for line in manifest:
        h, name = line.split("  ", 1)
        name = name.removeprefix("./")
        assert re.fullmatch("[0-9a-f]{64}", h) and name not in pins
        pins[name] = h
        assert sha(docs[name]) == h, "manifest mismatch " + name
    assert set(docs) == set(pins) and len(pins) == expected_count
    return docs


def root_digest(root):
    b = root.encode("utf-8")
    return sha(ROOT_PROFILE.encode() + b"\0" + len(b).to_bytes(8, "big") + b)


def emitted_docs(raw, scope, sources):
    delivered = raw["receipt"]["delivered_evidence"]
    derived = raw["receipt"]["derived_evidence"]
    selected = raw["selected"]
    assert [d["original_id"] for d in delivered] == selected
    assert [d["original_id"] for d in derived] == selected
    assert len(selected) == len(set(selected))
    assert raw["receipt"]["derivation_event_reads"] == sum(doc["scope"] == scope for doc in sources.values())
    assert raw["receipt"]["derived_view_digest"] == digest(derived)
    request = raw["citation_audit"]["request"]
    assert [s["label"] for s in request["sources"]] == [s["label"] for s in delivered]
    assert request["answer"] == raw["answer"]
    assert request["prompt_digest"] == raw["receipt"]["input_ids_digest"]
    for i,(item,exp) in enumerate(zip(delivered,derived),1):
        original = sources[item["original_id"]]
        content = original["content"]
        assert item["original_id"] == selected[i - 1]
        assert item["label"] == exp["label"] == f"E{i}"
        assert item["excerpt"] == content
        assert item["source_digest"] == exp["original_digest"] == digest(content)
        assert item["source_start"] == 0 and item["source_end"] == len(content.encode())
        assert item["scope"] == original["scope"] == scope
        assert item["root"] == original["root"]
        assert item["observed_at"] == original["observed_at"]
        assert exp["derivation_profile"] == VIEW
        fact = strict_json(content)
        prior = ", ".join(fact["supersedes"]) or "none explicitly named"
        expanded = (
            f"Event {fact['id']}: at logical revision {fact['revision']}, "
            f"entity {fact['entity']} has attribute {fact['attribute']} "
            f"with value {fact['value']}. Superseded event IDs: {prior}. "
            "This is a logical state revision, not a calendar date."
        )
        assert exp["text"] == expanded
        claim = request["sources"][i - 1]
        assert claim["excerpt"] == content
        assert claim["id"] == item["id"]
        assert claim["root"] == root_digest(item["root"])
    return {int(d["label"][1:]): d["original_id"] for d in delivered}


def compare_rows(raw, scored, cases, labels, original_sources, phase, selected_k, probe, single_hop=None):
    arms = [f"k{k}" for k in KS] if phase == "calibration" else list(EVAL_ARMS)
    assert len(raw) == len(scored) == 8 * len(arms)
    observed = [(x["question_id"], x["arm"]) for x in raw]
    planned = [(case["query"]["identity"], arm) for case in cases for arm in arms]
    assert observed == planned, "raw question/arm order or count differs"
    assert {(r["question_id"],r["arm"]) for r in scored} == set(planned)
    case_by_id = {c["query"]["identity"]: c for c in cases}
    label_by_id = {l["id"]: l for l in labels}
    assert set(label_by_id) == set(case_by_id) and len(case_by_id) == 8
    results = defaultdict(dict)
    for a,b in zip(raw,scored):
        assert {k:v for k,v in b.items() if k not in CORRECT_FIELDS} == a, "scorer rewrote raw answer"
        qid,arm=a["question_id"],a["arm"]
        case=case_by_id[qid]; lbl=label_by_id[qid]; q=case["query"]
        assert a["kind"] == lbl["kind"] == case["kind"]
        assert a["candidate_digest"] == case["candidate_digest"]
        assert a["status"] in ("succeeded", "failed")
        assert digest(tuple(case["candidate_ids"])) == case["candidate_digest"]
        if phase == "calibration": expected = tuple(case["candidate_ids"][:int(arm[1:])])
        else:
            controls = case["controls"]
            if arm == "selected_k": expected = tuple(case["candidate_ids"][:selected_k])
            elif arm == "hybrid_k4": expected = tuple(case["candidate_ids"][:4])
            elif arm == "hybrid_k6": expected = tuple(case["candidate_ids"][:6])
            elif arm == "hybrid_k4_reversed": expected = tuple(reversed(case["candidate_ids"][:4]))
            elif arm == "empty": expected = ()
            elif arm == "single_hop": expected = tuple(single_hop[qid])
            else: expected = tuple(controls[arm]["selected"])
        assert tuple(a["selected"]) == expected, "wrong selected sources for "+qid+":"+arm
        if a["status"] != "succeeded":
            results[qid][arm] = {"status": "failed"}
            continue
        receipt = a["receipt"]
        assert receipt["reader_identity"] and receipt["reader_profile"]
        assert receipt["view_profile"] == VIEW
        assert receipt["token_limit"] == 2048
        assert receipt["input_tokens"] <= 2048
        assert receipt["trainable_parameters"] == 0
        assert receipt["answer_postprocessed"] is False
        assert receipt["production_accepted"] is False
        assert receipt["semantic_citation_precision"] is None
        audit = a["citation_audit"]
        assert audit["judgement"] is None and audit["production_accepted"] is False
        req = audit["request"]
        assert req["query_id"] == qid and req["scope"] == q["scope"]
        assert req["question"] == q["content"]
        assert req["question_time"] == q["observed_at"]
        assert req["family_digest"] == digest(q["family"])
        bound = emitted_docs(a,q["scope"],original_sources)
        parsed = RESPONSE.fullmatch(a["answer"])
        parsed = parsed.group(1) if parsed else None
        assert b["parsed_identifier"] == parsed
        assert b["required_sources_covered"] == set(lbl["support"]).issubset(a["selected"])
        right = parsed == lbl["expected"]
        if lbl["kind"] == "procedure":
            request = {"operation":"execute","recipe":lbl["procedure"],"supplied":parsed or "invalid_response"}
            execution = subprocess.run(
                [sys.executable,"-I","-S",str(probe)],
                input=json.dumps(request,sort_keys=True),text=True,capture_output=True,timeout=10,check=False,
            )
            published = b["procedure_verification"]
            for key,val in (("request",request),("stdout",execution.stdout),("stderr",execution.stderr),("exit_code",execution.returncode)):
                assert published[key] == val, "changed bounded procedure output " + key
            right = execution.returncode == 0
        assert b["strict_task_success"] is right, "strict score drift"
        cited={bound[int(n)] for n in CITATION.findall(a["answer"])}
        results[qid][arm]={"status":"succeeded", "correct":right,"full_citation":right and set(lbl["support"]).issubset(cited), "input_tokens":receipt["input_tokens"], "generated_tokens":receipt["generated_tokens"], "seconds":receipt["seconds"], "selected":a["selected"],"prompt":receipt["input_ids_digest"],"generated_ids":receipt["generated_ids_digest"],"answer":a["answer"]}
    return results


def main(model_zip, frozen_zip, output):
    model=verify_zip(model_zip, MODEL_ZIP, 43)
    original=verify_zip(frozen_zip, ORIGINAL_ZIP, 35)
    assert model["tested-commit.txt"].decode().strip() == GENERATOR
    assert original["tested-commit.txt"].decode().strip() == "c9dd3aeff958fbdc4356a98718e96dec47f9b820"
    assert sha(original["plan/plan.json"]) == PLAN_SHA
    source_plan=strict_json(original["plan/plan.json"])
    originallabels=strict_json(original["observations/labels.json"])
    sources=strict_json(original["plan/source-view.json"])
    assert len(sources) == 108 and len({d["identity"] for d in sources}) == 108
    original_docs={d["identity"]:d for d in sources}
    assert sha(original["observations/labels.json"]) == source_plan["labels_sha"]
    original_by_id={r["id"]:r for r in originallabels}
    assert len(original_by_id) == 16
    prepared_plan=strict_json(model["prep/calibration-plan.json"])
    prepared_sources=strict_json(model["prep/calibration-sources.json"])
    prepared_labels=strict_json(model["prep/calibration-labels.json"])
    assert prepared_plan["historical_plan_sha256"] == PLAN_SHA
    assert prepared_plan["calibration_only"] and not prepared_plan["test_cases_materialized"]
    cal_ids=[c["query"]["identity"] for c in prepared_plan["cases"]]
    test_ids=[c["query"]["identity"] for c in source_plan["cases"]]
    assert len(cal_ids) == len(test_ids) == 8 and not set(cal_ids)&set(test_ids)
    assert all(s in sources for s in prepared_sources)
    assert {x["scope"] for x in prepared_sources} == set(cal_ids)
    assert set(prepared_plan["frozen_indices"]) == set(cal_ids)
    assert all(x==original_by_id[x["id"]] for x in prepared_labels)
    assert {x["id"] for x in prepared_labels} == set(cal_ids)
    policy=strict_json(model["calibration/frozen-policy.json"])
    assert policy["source_commit"] == GENERATOR
    assert policy["original_test_plan_sha256"] == PLAN_SHA
    assert policy["calibration_plan_sha256"] == sha(model["prep/calibration-plan.json"])
    assert policy["raw_answers_sha256"] == sha(model["calibration/raw-answers.jsonl"])
    assert policy["scored_answers_sha256"] == sha(model["calibration/scored-answers.json"])
    stage=strict_json(model["stage.json"])
    assert stage["tier"] == "qwen-3b" and stage["research_only"]
    assert stage["revision"] == "82f42baa094a9600e39ccd80d34058aeeb3abbc1"
    assert policy["stage_sha256"] == sha(model["stage.json"])
    inventory=strict_json(model["inventory.json"])
    assert policy["reader_identity"] == inventory["inventory_digest"]
    assert policy["selected_k"] in KS
    assert policy["frozen_before_evaluation"] and policy["production_accepted"] is False
    assert all(strict_json(model[p])["source_commit"] == GENERATOR for p in ("calibration/run.json","evaluation/run.json","evaluation/report.json","calibration/report.json"))
    assert strict_json(model["evaluation/run.json"])["policy_sha256"] == sha(model["calibration/frozen-policy.json"])
    assert sha(model["evaluation/raw-answers.jsonl"]) == strict_json(model["evaluation/report.json"])["raw_answers_sha256"]
    def get_jsonl(name):
        return [strict_json(x) for x in model[name].decode().splitlines()]
    with tempfile.TemporaryDirectory(prefix="hepta-memory-replay-") as temp:
        probe=Path(temp)/"event_probe.py"
        probe.write_bytes(original["source/event_probe.py"])
        cal=compare_rows(get_jsonl("calibration/raw-answers.jsonl"),strict_json(model["calibration/scored-answers.json"]),prepared_plan["cases"],prepared_labels,original_docs,"calibration",None,probe)
    public_specs=strict_json(original["observations/questions.json"])
    spec_by_id={x["id"]: x for x in public_specs}
    hop_control=strict_json(model["evaluation/single-hop-control.json"])
    assert hop_control["planned_questions"] == 8 and hop_control["source_selection_used_test_labels"] is False
    first_hop={}
    for case,info in zip(source_plan["cases"],hop_control["test_cases"]):
        qid=case["query"]["identity"]
        assert info["question_id"] == qid and info["ordered_candidates_sha256"] == case["candidate_digest"]
        spec=spec_by_id[qid]
        assert spec["phase"] == "test" and spec["kind"] == case["kind"]
        visible=[]
        for key in case["candidate_ids"]:
            ev=strict_json(original_docs[key]["content"])
            if ev["entity"] == spec["entity"] and ev["attribute"] == spec["path"][0] and ev["revision"] <= spec["revision"]:
                visible.append(key)
        assert len(visible) <= 4
        assert visible == info["first_hop"], "single hop not reproduced without labels"
        assert info["full_path"] == case["controls"]["entity_time"]["selected"]
        assert info["corrected_full_path"] == case["controls"]["organized"]["selected"]
        first_hop[qid]=visible
    with tempfile.TemporaryDirectory(prefix="hepta-memory-replay-") as temp:
        probe=Path(temp)/"event_probe.py"
        probe.write_bytes(original["source/event_probe.py"])
        eva=compare_rows(get_jsonl("evaluation/raw-answers.jsonl"),strict_json(model["evaluation/scored-answers.json"]),source_plan["cases"], [original_by_id[i] for i in test_ids],original_docs,"evaluation",policy["selected_k"],probe,first_hop)
    candidate_scores=[]
    for k in KS:
        arm=f"k{k}"
        candidates=[cal[q][arm] for q in cal]
        candidate_scores.append((k,sum(x["correct"] for x in candidates),sum(x["input_tokens"] for x in candidates)))
    selected=max(candidate_scores,key=lambda x:(x[1],-x[2],-x[0]))[0]
    assert selected == policy["selected_k"] == strict_json(model["calibration/report.json"])["frozen_k"]
    eval_report=strict_json(model["evaluation/report.json"])
    assert eval_report["selected_k"] == selected
    assert eval_report["total_attempts"] == 72
    evaluation={}
    for arm in EVAL_ARMS:
        entries=[eva[q][arm] for q in test_ids]
        assert all(x["status"]=="succeeded" for x in entries)
        v={"strict_correct":sum(x["correct"] for x in entries), "correct_with_full_program_declared_citations":sum(x["full_citation"] for x in entries),"input_tokens":sum(x["input_tokens"] for x in entries),"generated_tokens":sum(x["generated_tokens"] for x in entries),"reader_seconds":sum(x["seconds"] for x in entries)}
        actual=eval_report["success_by_arm"][arm]
        assert actual["strict_success"] == v["strict_correct"]
        assert actual["input_tokens"] == v["input_tokens"]
        assert actual["output_tokens"] == v["generated_tokens"]
        assert abs(actual["inference_seconds"]-v["reader_seconds"])<1e-5
        published=eval_report["formal_citation_chain"]["by_arm"][arm]
        assert published["strict_task_success"] == v["strict_correct"]
        assert published["correct_with_full_program_declared_citations"] == v["correct_with_full_program_declared_citations"]
        evaluation[arm]=v
    # Check same ordered evidence yields precisely identical model input and generations.
    repeat_pairs=0
    for q in test_ids:
        group=defaultdict(list)
        for arm in EVAL_ARMS:
            x=eva[q][arm]
            group[tuple(x["selected"])].append(x)
        for records in group.values():
            for a in range(len(records)):
                for b in range(a+1,len(records)):
                    left,right=records[a],records[b]
                    repeat_pairs+=1
                    assert (left["prompt"],left["generated_ids"],left["answer"],left["correct"]) == (right["prompt"],right["generated_ids"],right["answer"],right["correct"])
    assert repeat_pairs == eval_report["same_prompt_consistency"]["observed_identical_prompt_pairs"]
    comparisons={}
    for title,a,b in (("selected_minus_hybrid4","hybrid_k4","selected_k"),("entity_time_minus_single_hop","single_hop","entity_time"),("organized_minus_entity_time","entity_time","organized")):
        wins=sum(eva[q][b]["correct"] and not eva[q][a]["correct"] for q in test_ids)
        losses=sum(eva[q][a]["correct"] and not eva[q][b]["correct"] for q in test_ids)
        paired=eval_report["paired_contrasts"][title]
        assert paired["wins"]==wins and paired["losses"]==losses and paired["unknown_pairs"]==0
        comparisons[title]={"wins":wins,"losses":losses,"ties":8-wins-losses}
    result={
       "schema":"hepta.memorycell.exact-snapshot-replay.v1",
       "generated_commit": GENERATOR,
       "original_source_sha256": ORIGINAL_ZIP,
       "generated_artifact_sha256": MODEL_ZIP,
       "calibration_rows_verified": 40,
       "evaluation_rows_verified": 72,
       "manifest_members_checked": 43+35,
       "replayed_program_probes": sum(1 for q in cal for r in cal[q].values() if r["status"]=="succeeded" and original_by_id[q]["kind"]=="procedure") + sum(1 for q in eva for r in eva[q].values() if r["status"]=="succeeded" and original_by_id[q]["kind"]=="procedure"),
       "calibration_top_k": selected,
       "calibration_choices": candidate_scores,
       "evaluation":evaluation,
       "matched_prompt_pairs":repeat_pairs,
       "paired":comparisons,
       "hosted_independent_replay_finished":False,
       "human_semantic_adjudication":False,
       "independent_future_sample":False,
       "production_accepted":False,
       "verification":"read-only exact original bytes + independent strict scoring/program reexecution; no model generation"
    }
    output.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"result":"PASS","rows":112,"selected_k":selected,"arms":{k:v['strict_correct'] for k,v in evaluation.items()},"matched_prompt_pairs":repeat_pairs,"program_replays":result["replayed_program_probes"]},ensure_ascii=False))


if __name__=="__main__":
    if len(sys.argv) != 4:
        raise SystemExit("Usage: python memorycell_strong_rag_exact_replay.py MODEL_ZIP FROZEN_ZIP OUTPUT_JSON")
    main(Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]))
