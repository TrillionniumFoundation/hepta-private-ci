"""Read-only Unicode source recovery for a *privileged* frozen Reader diagnostic.

The registered native MiniLM encoder remains ASCII-only.  This V2 experiment
reconstructs only annotation-selected source excerpts from the SHA256-pinned
original LoCoMo conversation after V1 predictions and Reader plans are sealed.
Neither natural-language gold answers nor the original corpus are exposed to
inference.  The extra evidence is an oracle diagnostic, not retrieval gain.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import hashlib
import json
import re
import sys
import tempfile

from associative_locomo_shadow import (
    DATASET_SHA256, ascii_ok, canonical, exclusive, read_regular, strict_json,
)
from associative_cell import sha256
from associative_question_conditioned import (
    REGISTERED_READER_IDENTITY, _answer_with_fixed_reader, _token_f1,
)
from associative_reader_premise import (
    ARMS, MAX_NEW_TOKENS, PER_FAMILY, _read_plan as read_v1_plan,
)

SCHEMA = "hepta.privileged-reader-unicode-recovery.research.v2"
READER_SCHEMA = "hepta.privileged-reader-unicode-read.research.v2"
PINNED_V1_PLAN_SHA256 = "404c0fa14adc96d1a20e8c8a894e5f9e6f77392da8cced05bdadc6248c0686eb"
PINNED_PUBLIC_SHA256 = "e3c9fe407afcc08a153eeb0122b107314443335cb8f153b6557693bdbf900455"
MAX_READER_SOURCE_BYTES = 3072
MAX_PLAN_BYTES = 512 * 1024
MAX_EVIDENCE = 8


def _read_source(dataset_file):
    raw = read_regular(dataset_file, maximum=8 * 1024 * 1024)
    if sha256(raw) != DATASET_SHA256:
        raise ValueError("pinned original LoCoMo dataset digest changed")
    rows = strict_json(raw)
    if not isinstance(rows, list) or len(rows) != 10:
        raise ValueError("pinned ten-dialogue original required")
    return {r["sample_id"]: r for r in rows}


def _source_index(raw_record):
    conversation = raw_record.get("conversation")
    if not isinstance(conversation, dict):
        raise ValueError("no original conversation")
    index = {}
    for session, content in conversation.items():
        if not re.fullmatch(r"session_\d+", session) or not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict):
                raise ValueError("invalid original conversation event")
            sid, speaker, text = (item.get("dia_id"), item.get("speaker"), item.get("text"))
            if (not isinstance(sid, str) or not re.fullmatch(r"D\d+:\d+", sid)
                or sid in index or not isinstance(speaker, str) or not speaker
                or not isinstance(text, str) or not text.strip()
                or len((speaker + ": " + text).encode("utf-8")) > MAX_READER_SOURCE_BYTES
                or any(ord(c) < 32 and c not in "\r\n\t" for c in text)):
                raise ValueError("nonunique, non-text or unbounded original source")
            index[sid] = dict(speaker=speaker, text=text, session=session)
    return index


def _lesion(qid, ids):
    return min(ids, key=lambda sid: (
        hashlib.sha256(("hepta.premise-lesion.v1\0" + qid + "\0" + sid).encode()).digest(), sid
    ))


def _recovered(dataset, old_plan, public):
    if (not isinstance(public, dict) or len(public.get("families", [])) != 10
        or old_plan.get("planned_questions") != 20
        or old_plan.get("planned_attempts") != 40
        or old_plan.get("arms") != list(ARMS)
        or old_plan.get("public_sha256") != PINNED_PUBLIC_SHA256):
        raise ValueError("incompatible pinned source/plan admission")
    originals = {family: _source_index(rec) for family, rec in dataset.items()}
    public_map = {
        g["family"]: {d["id"]: d for d in g["sources"]}
        for g in public["families"]
    }
    plan_rows = old_plan["entries"]
    if len(plan_rows) != 40:
        raise ValueError("original Reader experiment has missing attempts")
    results, recovered_ids, changed_questions = [], [], set()
    for previous in plan_rows:
        row = dict(previous)
        qid, family = row["question_id"], row["family"]
        if family not in dataset or family not in public_map or not qid.startswith(family + "/q"):
            raise ValueError("source family or question identity drift")
        number = int(qid.rsplit("/q", 1)[1])
        questions = dataset[family].get("qa")
        if not isinstance(questions, list) or number >= len(questions):
            raise ValueError("original question missing")
        question = questions[number]
        if not isinstance(question, dict) or question.get("question") != row["question"]:
            raise ValueError("question text was changed")
        ids = question.get("evidence")
        if (not isinstance(ids, list) or not 1 <= len(ids) <= MAX_EVIDENCE
            or len(set(ids)) != len(ids) or not all(isinstance(x, str) for x in ids)):
            raise ValueError("incomplete, duplicate or non-list original evidence annotations")
        if row["source_support_complete"]:
            # Freeze every original V1 input and its evidence ordering/contents.
            if row["arm"] == "annotated_all":
                if set(x["source_id"] for x in row["evidence"]) != set(ids):
                    raise ValueError("v1 annotated evidence diverged from original")
            for e in row["evidence"]:
                source = originals[family].get(e["source_id"])
                if (source is None or e["text"] != source["speaker"] + ": " + source["text"][:384]
                    or e["source_id"] not in public_map[family]):
                    raise ValueError("v1 sealed original evidence text/ID changed")
        else:
            if (row["source_status"] != "missing-or-unresolved-annotation"
                or row["evidence"] or qid != "conv-49/q0014"):
                raise ValueError("unregistered missing-source recovery candidate")
            sources = []
            for sid in ids:
                source = originals[family].get(sid)
                if source is None:
                    raise ValueError("annotated source genuinely missing from original")
                in_existing = sid in public_map[family]
                if in_existing:
                    existing = public_map[family][sid]
                    if (existing["text"] != source["text"]
                        or existing["speaker"] != source["speaker"]):
                        raise ValueError("already admitted source was changed")
                else:
                    if ascii_ok(source["text"]) and ascii_ok(source["speaker"] + ": " + source["text"]):
                        raise ValueError("excluded original was not rejected by ASCII-only policy")
                    if sid not in recovered_ids:
                        recovered_ids.append(sid)
                sources.append(source)
            if row["arm"] == "annotated_minus_one":
                keep = [sid for sid in ids if sid != _lesion(qid, ids)]
            else:
                keep = list(ids)
            row["evidence"] = [
                dict(label=f"E{i}", source_id=sid, source_start=0,
                     text=originals[family][sid]["speaker"] + ": " + originals[family][sid]["text"])
                for i, sid in enumerate(keep, start=1)
            ]
            row["source_support_complete"] = True
            row["source_status"] = "gold-selected-original-utf8-source-recovery"
            changed_questions.add(qid)
        results.append(row)
    if (len(results) != 40 or changed_questions != {"conv-49/q0014"}
        or set(recovered_ids) != {"D23:15", "D22:12"}):
        raise ValueError("unexpected source recovery scope or new evidence")
    return results, sorted(recovered_ids)


def produce(dataset_file, v1_plan_dir, public_json, output_dir):
    """Trusted planner only; never pass source corpus or reference answers to Reader."""
    v1, seal = read_v1_plan(v1_plan_dir)
    original_raw = read_regular(Path(v1_plan_dir) / "plan.json", maximum=MAX_PLAN_BYTES)
    if sha256(original_raw) != PINNED_V1_PLAN_SHA256:
        raise ValueError("unregistered V1 premise plan")
    raw_public = read_regular(public_json)
    if sha256(raw_public) != PINNED_PUBLIC_SHA256:
        raise ValueError("unregistered V1 public source view")
    records, recovered = _recovered(_read_source(dataset_file), v1, strict_json(raw_public))
    plan = dict(schema=SCHEMA, original_plan_sha256=sha256(original_raw),
                dataset_sha256=DATASET_SHA256, public_sha256=PINNED_PUBLIC_SHA256,
                source_journal_sha256=v1["source_journal_sha256"],
                arms=list(ARMS), planned_questions=20, planned_attempts=40,
                recovered_source_ids=recovered, recovered_questions=["conv-49/q0014"],
                entries=records, gold_selected_source_ids_used=True,
                raw_gold_answers_included=False,
                retriever_or_memory_utility_comparison=False,
                independently_verified_semantic_sufficiency=False,
                production_accepted=False)
    _validate_plan(plan)
    out = Path(output_dir)
    out.mkdir(exist_ok=False)
    digest = exclusive(out / "plan.json", plan)
    exclusive(out / "seal.json", dict(schema=SCHEMA, plan_sha256=digest,
        original_plan_sha256=sha256(original_raw), public_sha256=PINNED_PUBLIC_SHA256,
        planned_attempts=40, source_recovery_sha256=sha256(canonical(recovered)),
        no_gold_answer_fields=True, production_accepted=False))
    return dict(schema=SCHEMA, planned=40, annotated_sources_available=20,
                recovered_source_ids=recovered, plan_sha256=digest,
                independent_semantic_sufficiency_verified=False,
                production_accepted=False)


def _validate_plan(p):
    if (not isinstance(p, dict) or p.get("schema") != SCHEMA
        or p.get("original_plan_sha256") != PINNED_V1_PLAN_SHA256
        or p.get("public_sha256") != PINNED_PUBLIC_SHA256
        or p.get("dataset_sha256") != DATASET_SHA256
        or p.get("planned_questions") != 20 or p.get("planned_attempts") != 40
        or p.get("recovered_questions") != ["conv-49/q0014"]
        or set(p.get("recovered_source_ids", [])) != {"D23:15", "D22:12"}
        or p.get("arms") != list(ARMS)
        or p.get("raw_gold_answers_included") is not False
        or p.get("production_accepted") is not False):
        raise ValueError("invalid or unregistered Unicode recovery plan")
    rows=p.get("entries")
    if not isinstance(rows, list) or len(rows) != 40:
        raise ValueError("incomplete Unicode Reader plan")
    seen=set(); grouped=defaultdict(dict);count=Counter()
    for row in rows:
        if (not isinstance(row, dict)
            or set(row) != {"question_id","family","arm","question","source_support_complete","source_status","evidence"}
            or row["arm"] not in ARMS or row["source_support_complete"] is not True
            or not isinstance(row["question"], str) or not row["question"].strip()
            or not isinstance(row["evidence"], list) or not 0 <= len(row["evidence"]) <= MAX_EVIDENCE):
            raise ValueError("invalid Reader premise entry")
        key = row["question_id"], row["arm"]
        if key in seen:
            raise ValueError("duplicate Reader attempt")
        seen.add(key);grouped[row["question_id"]][row["arm"]]=row
        if row["arm"] == "annotated_all":
            count[row["family"]]+=1
        for i, source in enumerate(row["evidence"], 1):
            if (not isinstance(source, dict) or set(source) != {"label","source_id","source_start","text"}
                or source["label"] != f"E{i}" or source["source_start"] != 0
                or not isinstance(source["source_id"], str)
                or not isinstance(source["text"], str) or not source["text"].strip()
                or len(source["text"].encode("utf-8")) > MAX_READER_SOURCE_BYTES):
                raise ValueError("unbound, malformed or oversized Reader evidence")
    if len(grouped)!=20 or len(count)!=10 or any(k!=2 for k in count.values()):
        raise ValueError("source-family Reader census drift")
    for qid, arms in grouped.items():
        if set(arms) != set(ARMS):
            raise ValueError("missing paired source condition")
        full = [e["source_id"] for e in arms["annotated_all"]["evidence"]]
        less = [e["source_id"] for e in arms["annotated_minus_one"]["evidence"]]
        if (not full or len(less) != len(full)-1
            or less != [sid for sid in full if sid != _lesion(qid,full)]):
            raise ValueError("premise lesion changed or did not remove exactly one")
    return grouped


def read_plan(folder):
    folder=Path(folder)
    if (not folder.is_dir() or folder.is_symlink()
        or {x.name for x in folder.iterdir()} != {"plan.json","seal.json"}
        or any(x.is_symlink() or not x.is_file() for x in folder.iterdir())):
        raise ValueError("isolated exact two-file Unicode plan required")
    raw=read_regular(folder/"plan.json",maximum=MAX_PLAN_BYTES)
    meta=strict_json(read_regular(folder/"seal.json"))
    plan=strict_json(raw)
    _validate_plan(plan)
    if (meta.get("schema") != SCHEMA or meta.get("plan_sha256") != sha256(raw)
        or meta.get("original_plan_sha256") != PINNED_V1_PLAN_SHA256
        or meta.get("planned_attempts") != 40
        or meta.get("source_recovery_sha256") != sha256(canonical(plan["recovered_source_ids"]))
        or meta.get("no_gold_answer_fields") is not True
        or meta.get("production_accepted") is not False):
        raise ValueError("unsealed or altered Unicode Reader plan")
    return plan,meta


def run_reader(plan_dir, reader_dir, output_dir):
    plan, meta=read_plan(plan_dir)
    from reader_reference import ReferenceReader
    from pretrained import file_inventory
    from native import digest
    path=Path(reader_dir)
    if not path.is_dir() or path.is_symlink():
        raise ValueError("pinned Reader weights directory required")
    if digest(file_inventory(path)) != REGISTERED_READER_IDENTITY:
        raise ValueError("frozen Reader identity drift")
    reader=ReferenceReader(path,expected_inventory=REGISTERED_READER_IDENTITY)
    target=Path(output_dir);target.mkdir(exist_ok=False)
    rows=[]
    for entry in plan["entries"]:
        try:
            result=_answer_with_fixed_reader(reader,entry,MAX_NEW_TOKENS)
        except Exception as err:
            result=dict(status="failed",reason=type(err).__name__,answer=None)
        rows.append(dict(question_id=entry["question_id"],family=entry["family"],
            arm=entry["arm"],evidence_ids=[s["source_id"] for s in entry["evidence"]],
            result=result))
    reader.verify_frozen()
    digest_j=exclusive(target/"reader-journal.json",rows)
    receipt=dict(schema=READER_SCHEMA,plan_sha256=meta["plan_sha256"],
        journal_sha256=digest_j,planned=40,reader_identity=reader.identity,
        reader_profile=reader.profile,success_count=sum(r["result"].get("status")=="succeeded" for r in rows),
        labels_visible=False,source_recovery_is_privileged=True,
        independent_sufficiency_verified=False,production_accepted=False)
    exclusive(target/"reader-seal.json",receipt)
    return receipt


def review(dataset_file, original_plan_dir, original_public_json, v2_plan_dir, v2_reader_dir, output):
    """Independent verifier: reread original gold only after sealed inference."""
    plan,meta=read_plan(v2_plan_dir)
    original=_read_source(dataset_file)
    with tempfile.TemporaryDirectory(prefix="hepta-unicode-verify-") as temp:
        reconstructed=Path(temp)/"plan"
        produce(dataset_file,original_plan_dir,original_public_json,reconstructed)
        if read_regular(reconstructed/"plan.json",maximum=MAX_PLAN_BYTES) != read_regular(Path(v2_plan_dir)/"plan.json",maximum=MAX_PLAN_BYTES):
            raise ValueError("sealed Reader input differs from original source reconstruction")
    raw=read_regular(Path(v2_reader_dir)/"reader-journal.json",maximum=MAX_PLAN_BYTES)
    records=strict_json(raw)
    receipt=strict_json(read_regular(Path(v2_reader_dir)/"reader-seal.json"))
    if (receipt.get("schema") != READER_SCHEMA
        or receipt.get("journal_sha256") != sha256(raw)
        or receipt.get("plan_sha256") != meta["plan_sha256"]
        or receipt.get("planned") != 40
        or receipt.get("labels_visible") is not False
        or receipt.get("reader_identity") != REGISTERED_READER_IDENTITY
        or receipt.get("production_accepted") is not False):
        raise ValueError("incomplete or unsealed Reader execution")
    expected={(e["question_id"],e["arm"]):e for e in plan["entries"]}
    if not isinstance(records,list) or len(records)!=40:
        raise ValueError("incomplete Reader results")
    seen=set();scores=defaultdict(list);state=defaultdict(Counter);pair={}
    for row in records:
        if (not isinstance(row,dict) or set(row)!={"question_id","family","arm","evidence_ids","result"}):
            raise ValueError("foreign Reader response")
        k=(row["question_id"],row["arm"])
        if k not in expected or k in seen:
            raise ValueError("missing or duplicate Reader response")
        seen.add(k)
        e=expected[k]
        if (row["family"] != e["family"] or row["evidence_ids"]!=[x["source_id"] for x in e["evidence"]]):
            raise ValueError("Reader used unregistered evidence")
        result=row["result"]
        if (not isinstance(result,dict) or result.get("status") not in ("succeeded","failed","unavailable")):
            raise ValueError("unrecognized Reader attempt outcome")
        state[e["arm"]][result["status"]]+=1
        qnum=int(row["question_id"].rsplit("/q",1)[1])
        gold=original[e["family"]]["qa"][qnum].get("answer")
        if result["status"]=="succeeded":
            if (not isinstance(result.get("answer"),str) or not result["answer"].strip()
                or result.get("reader_identity")!=REGISTERED_READER_IDENTITY):
                raise ValueError("missing actual frozen Reader answer/identity")
            if isinstance(gold,str) and gold.strip():
                value=_token_f1(result["answer"],gold)
                scores[e["arm"]].append(value)
                pair.setdefault(row["question_id"],{})[e["arm"]]=value
            else:
                state[e["arm"]]["unscorable-reference"]+=1
    if set(expected)!=seen:
        raise ValueError("Reader attempt census changed")
    diffs=[vals["annotated_all"]-vals["annotated_minus_one"] for vals in pair.values() if set(vals)==set(ARMS)]
    report=dict(schema=SCHEMA,plan_sha256=meta["plan_sha256"],reader_journal_sha256=receipt["journal_sha256"],
        paired_scored=len(diffs),source_supported_questions=20,
        by_arm={name:dict(planned=20,mean_token_f1=sum(scores[name])/len(scores[name]) if scores[name] else None,
                           scored=len(scores[name]),statuses=dict(state[name])) for name in ARMS},
        paired_mean_oracle_minus_removed=sum(diffs)/len(diffs) if diffs else None,
        gold_premises_selected_after_earlier_ranking=True,independent_semantic_sufficiency_verified=False,
        memorycell_gain_claim=False,statistically_significant_superiority=False,production_accepted=False)
    exclusive(output,report)
    return report


def main(argv=None):
    argv=sys.argv if argv is None else argv
    if len(argv)<2:
        raise SystemExit("plan|reader|review")
    if argv[1]=="plan" and len(argv)==6:
        result=produce(argv[2],argv[3],argv[4],argv[5])
    elif argv[1]=="reader" and len(argv)==5:
        result=run_reader(argv[2],argv[3],argv[4])
    elif argv[1]=="review" and len(argv)==8:
        result=review(argv[2],argv[3],argv[4],argv[5],argv[6],argv[7])
    else:
        raise SystemExit("usage: plan ORIGINAL_JSON V1_PLAN_DIR PUBLIC_JSON NEW_DIR | reader PLAN_DIR PINNED_READER_DIR NEW_DIR | review ORIGINAL_JSON V1_PLAN_DIR PUBLIC_JSON V2_PLAN_DIR V2_READER_DIR NEW_REPORT")
    print(json.dumps(result,sort_keys=True,ensure_ascii=False))

if __name__=="__main__":
    main()
