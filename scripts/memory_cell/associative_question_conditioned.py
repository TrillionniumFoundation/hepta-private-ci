"""Frozen-source LoCoMo question-conditioned associative memory and fixed-reader lab.

Research only. ``prepare`` alone may inspect benchmark answers. ``run`` and
``reader`` accept a physically separate PUBLIC folder (no hidden labels), seal
all predictions before ``review`` can score them, and never grant evidence or
model-selection authority. This is not a production memory owner.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import json
import math
import os
import re
import sys
import time

import numpy as np
import torch

from associative_cell import AssociativeCell, Experience, ReadQuery, TrainingCut, sha256
from associative_locomo_shadow import (
    DATASET_SHA256, ascii_ok, bm25_score, bm25_table, canonical,
    chosen, exclusive, kind_of, ordered, prepare as prepare_prefix,
    read_regular, rrf, strict_json, tokens,
)
from associative_minilm_offline import MiniLMOfflineEncoder
from associative_text_bridge import PinnedTextProjection

SCHEMA = "hepta.associative-question-conditioned-fullsource.research.v1"
READER_SCHEMA = "hepta.associative-question-conditioned-reader.research.v1"
ARMS = ("frozen", "auto_association", "question_conditioned",
        "dense", "bm25", "rrf", "rrf_question_conditioned")
READER_ARMS = ("empty", "bm25", "rrf", "question_conditioned", "rrf_question_conditioned")
SOURCES_MAX, QUESTIONS_PER_FAMILY, TRAIN_PREFIX = 1024, 24, 128
RANK, DIMENSION, TRAIN_STEPS, TOP_K, RRF_K = 8, 64, 128, 8, 60
Q_TEMPLATE = "source-only-keyword-probe-v1"
REGISTERED_READER_IDENTITY = "afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c"
STOPWORDS = frozenset("a an and are as at be but by can do for from had has have i in is it my of on or our she so that the their them there they this to was were what when where who why will with you your about said know thing something".split())


def _read_public(folder, *, reviewer=False):
    folder = Path(folder)
    if not reviewer and ((folder / "private.json").exists() or (folder / "private.json").is_symlink()):
        raise ValueError("hidden labels must be physically isolated from model worker")
    raw_manifest = read_regular(folder / "manifest.json")
    raw_public = read_regular(folder / "public.json")
    manifest = strict_json(raw_manifest)
    if (manifest.get("schema") != SCHEMA or manifest.get("dataset_sha256") != DATASET_SHA256
        or manifest.get("public_sha256") != sha256(raw_public)
        or manifest.get("private_sha256") is None or manifest.get("production_accepted") is not False):
        raise ValueError("public source identity or manifest drift")
    data = strict_json(raw_public)
    _check_public(data)
    if (manifest.get("family_count") != 10 or manifest.get("question_count") != 240
        or manifest.get("source_count") != sum(len(g["sources"]) for g in data["families"])):
        raise ValueError("manifest source/question census drift")
    return data, manifest


def _check_public(public):
    if (not isinstance(public, dict) or set(public) != {"schema", "dataset_sha256", "policy", "families"}
        or public["schema"] != SCHEMA or public["dataset_sha256"] != DATASET_SHA256
        or public["policy"] != dict(source_policy="all-eligible-ascii",
                                     source_max=SOURCES_MAX, question_limit=QUESTIONS_PER_FAMILY,
                                     train_prefix=TRAIN_PREFIX)
        or not isinstance(public["families"], list) or len(public["families"]) != 10):
        raise ValueError("invalid public corpus policy or family census")
    seen_families, total_q = set(), 0
    for group in public["families"]:
        if not isinstance(group, dict) or set(group) != {"family", "sources", "questions"}:
            raise ValueError("invalid public group fields")
        family, docs, questions = group["family"], group["sources"], group["questions"]
        if (not isinstance(family, str) or not re.fullmatch(r"conv-\d{1,4}", family)
            or family in seen_families or not isinstance(docs, list)
            or not TRAIN_PREFIX <= len(docs) <= SOURCES_MAX
            or not isinstance(questions, list) or len(questions) != QUESTIONS_PER_FAMILY):
            raise ValueError("invalid or repeated public dialogue")
        seen_families.add(family)
        ids, seqs, qids = set(), set(), set()
        for doc in docs:
            if (not isinstance(doc, dict) or set(doc) != {"id", "speaker", "text", "session", "seq", "kind"}
                or not isinstance(doc["id"], str) or not re.fullmatch(r"D\d+:\d+", doc["id"])
                or doc["id"] in ids or not isinstance(doc["speaker"], str)
                or not ascii_ok(doc["speaker"] + ": " + doc["text"])
                or not isinstance(doc["session"], str) or not re.fullmatch(r"session_\d+", doc["session"])
                or doc["kind"] != kind_of(doc["text"])
                or type(doc["seq"]) is not int or doc["seq"] < 1 or doc["seq"] in seqs):
                raise ValueError("invalid source record or duplicated identity")
            ids.add(doc["id"]); seqs.add(doc["seq"])
        if seqs != set(range(1, len(docs)+1)):
            raise ValueError("source chronology drift")
        for q in questions:
            if (not isinstance(q, dict) or set(q) != {"id", "text", "kind"}
                or not isinstance(q["id"], str) or not re.fullmatch(re.escape(family) + r"/q\d{4}", q["id"])
                or q["id"] in qids or not ascii_ok(q["text"])
                or q["kind"] != kind_of(q["text"])):
                raise ValueError("test question labels or identity drift")
            qids.add(q["id"])
        total_q += len(qids)
    if total_q != 240:
        raise ValueError("unexpected test question count")


def prepare_full(dataset_file, output):
    """Trusted-only preparation. Keep all eligible source turns without gold selection."""
    raw = read_regular(dataset_file)
    if sha256(raw) != DATASET_SHA256:
        raise ValueError("frozen original LoCoMo input mismatch")
    original = strict_json(raw)
    with TemporaryDirectory(prefix="mcell-prefix-admission-") as scratch:
        previous = Path(scratch) / "prepared"
        prepare_prefix(dataset_file, previous, source_limit=256,
                       question_limit=QUESTIONS_PER_FAMILY)
        previous_public = strict_json(read_regular(previous / "public.json"))
        previous_private = strict_json(read_regular(previous / "private.json"))
    by_family = {rec["sample_id"]: rec for rec in original}
    public_groups, private_labels = [], {}
    for group in previous_public["families"]:
        family = group["family"]
        rec = by_family[family]
        source, seen = [], set()
        conversation = rec["conversation"]
        sessions = sorted((name for name, data in conversation.items()
                           if re.fullmatch(r"session_\d+", name) and isinstance(data, list)),
                          key=lambda name: int(name.split("_")[1]))
        for session in sessions:
            for utterance in conversation[session]:
                did, speaker, content = (utterance.get("dia_id"), utterance.get("speaker"), utterance.get("text"))
                if (not isinstance(did, str) or not isinstance(speaker, str) or did in seen):
                    raise ValueError("missing or duplicate original source")
                seen.add(did)
                if ascii_ok(content) and ascii_ok(speaker + ": " + content):
                    source.append(dict(id=did, speaker=speaker, text=content,
                                       session=session, seq=len(seen), kind=kind_of(content)))
        # The old 256-source run is a strictly checked prefix of this same pool.
        if len(source) > SOURCES_MAX or source[:256] != group["sources"]:
            raise ValueError("full-source prefix or resource bound drift")
        # Filtered-out non-ASCII records can make seq noncontiguous: preserve the
        # source's real raw order instead, but canonicalize dense public sequence.
        for index, doc in enumerate(source, start=1):
            doc["seq"] = index
        for q in group["questions"]:
            prior = previous_private["annotations"][q["id"]]
            idx = int(q["id"].rsplit("q", 1)[1])
            reference = rec["qa"][idx]
            answer = reference.get("answer")
            if (not isinstance(answer, (str, list, int, float, bool, type(None)))
                or (isinstance(answer, str) and len(answer.encode()) > 8192)):
                raise ValueError("unbounded or unrecognized hidden reference")
            private_labels[q["id"]] = dict(prior, answer=answer)
        public_groups.append(dict(family=family, sources=source, questions=group["questions"]))
    public = dict(schema=SCHEMA, dataset_sha256=DATASET_SHA256,
                  policy=dict(source_policy="all-eligible-ascii", source_max=SOURCES_MAX,
                              question_limit=QUESTIONS_PER_FAMILY, train_prefix=TRAIN_PREFIX),
                  families=public_groups)
    _check_public(public)
    private = dict(schema=SCHEMA, annotations=private_labels)
    dest=Path(output)
    dest.mkdir(exist_ok=False)
    public_sha=exclusive(dest / "public.json", public)
    private_sha=exclusive(dest / "private.json", private)
    manifest=dict(schema=SCHEMA, dataset_sha256=DATASET_SHA256,
                  public_sha256=public_sha, private_sha256=private_sha,
                  family_count=10, source_count=sum(len(g["sources"]) for g in public_groups),
                  question_count=len(private_labels), labels_used_for_training=False,
                  independently_admitted=False, production_accepted=False)
    exclusive(dest / "manifest.json",manifest)
    return manifest


def pseudo_question(doc):
    """Source-only probe; no benchmark question or answer is used to construct it."""
    if not isinstance(doc, dict) or set(doc) != {"id", "speaker", "text", "session", "seq", "kind"}:
        raise ValueError("invalid synthetic question source")
    unique=[]
    for word in tokens(doc["text"]):
        if 3 <= len(word) <= 28 and word not in STOPWORDS and word not in unique:
            unique.append(word)
        if len(unique) == 5:
            break
    if not unique:
        unique = tokens(doc["text"])[:3]
    if not unique:
        raise ValueError("cannot make source-only cue")
    speaker=doc["speaker"][:64]
    if not ascii_ok(speaker):
        raise ValueError("invalid speaker cue")
    return f"What did {speaker} say about {' '.join(unique)}?"


def _encode_batches(projection, texts):
    output=[]
    for offset in range(0,len(texts),16):
        output.extend(projection.encode(texts[offset:offset+16]))
    return tuple(output)


def _normalize(matrix):
    matrix=np.asarray(matrix,dtype=np.float32)
    norms=np.linalg.norm(matrix,axis=1,keepdims=True)
    if matrix.ndim!=2 or not np.isfinite(matrix).all() or (norms<1e-8).any():
        raise ValueError("invalid nonzero representation")
    return matrix/np.maximum(norms,1e-9)


def run(public_dir, encoder_dir, output_dir):
    """Deterministic, source-only 240-question, 7-arm frozen-weight experiment."""
    public, manifest=_read_public(public_dir)
    out=Path(output_dir);out.mkdir(exist_ok=False)
    encoder=MiniLMOfflineEncoder(encoder_dir)
    projection=PinnedTextProjection(encoder,dimension=DIMENSION)
    journal=[];artifacts={};family_resources={}
    start=time.perf_counter()
    prior_threads=torch.get_num_threads();torch.set_num_threads(2)
    try:
        for group in public["families"]:
            fam=group["family"];docs=group["sources"];queries=group["questions"]
            # Every source is accessible to retrieval, but trainable parameters
            # see only the same FIRST 128 originals in both training arms.
            source_texts=[d["speaker"]+": "+d["text"] for d in docs]
            val_texts=[d["text"] for d in docs]
            source_cues=_encode_batches(projection,source_texts)
            source_values=_encode_batches(projection,val_texts)
            pseudo_cues=_encode_batches(projection,[pseudo_question(d) for d in docs[:TRAIN_PREFIX]])
            train_auto=tuple(Experience(f"{fam}/{d['id']}",fam,fam,f"{fam}/{d['id']}",
                                        d["kind"],projection.identity,d["seq"],
                                        source_cues[i],source_values[i])
                             for i,d in enumerate(docs[:TRAIN_PREFIX]))
            train_pseudo=tuple(Experience(f"{fam}/{d['id']}",fam,fam,f"{fam}/{d['id']}",
                                          d["kind"],projection.identity,d["seq"],
                                          pseudo_cues[i],source_values[i])
                               for i,d in enumerate(docs[:TRAIN_PREFIX]))
            cut=TrainingCut(fam,projection.identity,TRAIN_PREFIX,
                            frozenset(r.root for r in train_auto),frozenset({fam}),
                            frozenset(),frozenset(),sha256(canonical(dict(
                                family=fam,public_sha256=manifest["public_sha256"],
                                train_prefix=TRAIN_PREFIX,training_policy="source-only"))))
            frozen=AssociativeCell(DIMENSION,RANK,projection.identity,fam,seed=313)
            automatic,auto_receipt=frozen.propose_update(train_auto,cut,revoked=set(),
                                                          steps=TRAIN_STEPS,lr=0.25)
            conditioned,cond_receipt=frozen.propose_update(train_pseudo,cut,revoked=set(),
                                                            steps=TRAIN_STEPS,lr=0.25)
            if (frozen.parameter_count()!=automatic.parameter_count()
                or automatic.parameter_count()!=conditioned.parameter_count()
                or auto_receipt["steps"]!=cond_receipt["steps"]):
                raise ValueError("training capacity/budget mismatch")
            # Historical parent and both research candidates are artifact only.
            per_model={}
            folder=out / "cells";folder.mkdir(exist_ok=True)
            for name,cell in (("auto",automatic),("question",conditioned)):
                payload=cell.export()
                restored=AssociativeCell.restore(payload,expected_sha256=sha256(payload),
                    encoder_identity=projection.identity,scope=fam,
                    allowed_roots={r.root for r in train_auto},revoked=set())
                if sha256(restored.export())!=sha256(payload):
                    raise ValueError("artifact-only restore mismatch")
                per_model[name]=sha256(payload)
                exclusive(folder / f"{fam}-{name}.json",payload)
            artifacts[fam]=dict(per_model,param_count=automatic.parameter_count(),
                                source_lineage_count=len(automatic.roots))
            query_vectors=_encode_batches(projection,[q["text"] for q in queries])
            normalized_source=_normalize(source_cues)
            normalized_values=_normalize(source_values)
            bm25=bm25_table(source_texts)
            for q,vec in zip(queries,query_vectors,strict=True):
                rq=ReadQuery(fam,q["kind"],projection.identity,1_800_000_000,vec)
                vec=np.asarray(vec,dtype=np.float32)
                baseline={"frozen":frozen,"auto_association":automatic,
                          "question_conditioned":conditioned}
                ranks={}
                for name,cell in baseline.items():
                    output_vec=np.asarray(cell.read(rq,revoked=set()),dtype=np.float32)
                    output_vec/=max(float(np.linalg.norm(output_vec)),1e-9)
                    ranks[name]=ordered(normalized_values@output_vec,docs)
                dense=ordered(normalized_source@vec,docs)
                lexical=ordered(bm25_score(q["text"],bm25),docs)
                fused=rrf(dense,lexical,constant=RRF_K)
                q_rank={index:rank for rank,index in enumerate(ranks["question_conditioned"],start=1)}
                # Fixed before reading any held-out label, hence no post-hoc tuning.
                fused_query=[fused[i]+0.25/(RRF_K+q_rank[i]) for i in range(len(docs))]
                ranks.update(dense=dense,bm25=lexical,
                             rrf=ordered([fused[i] for i in range(len(docs))],docs),
                             rrf_question_conditioned=ordered(fused_query,docs))
                journal.append(dict(question_id=q["id"],family=fam,kind=q["kind"],
                                    predictions={name:[docs[i]["id"] for i in ranks[name][:TOP_K]]
                                                 for name in ARMS}))
            family_resources[fam]=dict(source_pool=len(docs),train_prefix=TRAIN_PREFIX,
                                       encoder_texts=projection.encoded_texts,
                                       encoder_batches=projection.model_calls,
                                       train_steps=TRAIN_STEPS,
                                       pseudo_template=Q_TEMPLATE)
    finally:
        torch.set_num_threads(prior_threads)
    journal_sha=exclusive(out / "journal.json",journal)
    seal=dict(schema=SCHEMA,public_sha256=manifest["public_sha256"],
              journal_sha256=journal_sha,complete_count=len(journal),
              arms=list(ARMS),source_pool_size=sum(len(g["sources"]) for g in public["families"]),
              training_prefix=TRAIN_PREFIX,optimizer_steps_per_arm=TRAIN_STEPS,
              trainable_parameter_count_per_arm=next(iter(artifacts.values()))["param_count"],
              training_question_labels_accessed=False,
              pretrained_reader_executed=False,production_accepted=False,
              mean_elapsed_seconds=time.perf_counter()-start,
              encoder_identity=projection.identity,shared_encoder_bytes=sum(p.stat().st_size for p in Path(encoder_dir).iterdir() if p.is_file()),
              artifacts=artifacts,family_resources=family_resources)
    if len(journal)!=240:
        raise ValueError("incomplete question census")
    exclusive(out / "seal.json",seal)
    return seal


def _checked_run(public_dir, run_dir, *, reviewer=False):
    public, manifest=_read_public(public_dir, reviewer=reviewer)
    journal_raw=read_regular(Path(run_dir)/"journal.json")
    seal=strict_json(read_regular(Path(run_dir)/"seal.json"))
    if (seal.get("schema") != SCHEMA or seal.get("public_sha256")!=manifest["public_sha256"]
        or seal.get("journal_sha256")!=sha256(journal_raw)
        or seal.get("complete_count")!=240 or seal.get("arms")!=list(ARMS)
        or seal.get("training_question_labels_accessed") is not False):
        raise ValueError("noncanonical or unsealed predictions")
    journal=strict_json(journal_raw)
    expected={(g["family"],q["id"]) for g in public["families"] for q in g["questions"]}
    seen=set()
    groups={g["family"]:{s["id"] for s in g["sources"]} for g in public["families"]}
    for row in journal:
        if (not isinstance(row,dict) or set(row)!={"question_id","family","kind","predictions"}
            or (row["family"],row["question_id"]) not in expected
            or (row["family"],row["question_id"]) in seen
            or set(row["predictions"])!=set(ARMS)):
            raise ValueError("extra, missing or duplicate inference arm")
        seen.add((row["family"],row["question_id"]))
        for ids in row["predictions"].values():
            if (not isinstance(ids,list) or len(ids)!=TOP_K or len(ids)!=len(set(ids))
                or not set(ids)<=groups[row["family"]]):
                raise ValueError("prediction contains non-source or missing candidate")
    if seen!=expected:
        raise ValueError("incomplete sealed reader census")
    return public,manifest,journal,seal


def review(prepared_dir, run_dir, target_file):
    public,manifest,journal,seal=_checked_run(prepared_dir,run_dir,reviewer=True)
    hidden_raw=read_regular(Path(prepared_dir)/"private.json")
    if sha256(hidden_raw)!=manifest["private_sha256"]:
        raise ValueError("hidden reference digest mismatch")
    hidden=strict_json(hidden_raw)
    if hidden.get("schema")!=SCHEMA or not isinstance(hidden.get("annotations"),dict):
        raise ValueError("invalid private reference")
    labels=hidden["annotations"]
    available={g["family"]:{d["id"] for d in g["sources"]} for g in public["families"]}
    results={arm:[] for arm in ARMS};family_results=defaultdict(lambda:{a:[] for a in ARMS})
    unresolved=0;positive=0;eligible=0
    if set(labels)!={row["question_id"] for row in journal}:
        raise ValueError("hidden question identity drift")
    for row in journal:
        gold=labels[row["question_id"]]
        if gold["unresolved_reference"]:
            unresolved+=1;continue
        evidence=set(gold["evidence"])
        if not evidence:
            continue
        positive+=1
        is_eligible=evidence<=available[row["family"]]
        eligible+=int(is_eligible)
        for arm,predicted in row["predictions"].items():
            result=dict(eligible=is_eligible,complete=evidence<=set(predicted),
                        any_hit=bool(evidence&set(predicted)),first=predicted[0] in evidence)
            results[arm].append(result)
            family_results[row["family"]][arm].append(result)
    def aggregate(rows):
        elig=[r for r in rows if r["eligible"]]
        return dict(referenced=len(rows),complete_in_pool=len(elig),
                    complete_top8_all_referenced=sum(r["complete"] for r in rows),
                    complete_top8_eligible=sum(r["complete"] for r in elig),
                    any_top8_all_referenced=sum(r["any_hit"] for r in rows),
                    first_hit=sum(r["first"] for r in rows))
    report=dict(schema=SCHEMA,public_sha256=manifest["public_sha256"],
                journal_sha256=seal["journal_sha256"],dialogue_families=10,
                independent_family_authentication=False,planned_questions=240,
                reference_positive=positive,reference_unresolved=unresolved,
                reference_eligible=eligible,
                by_arm={arm:aggregate(v) for arm,v in results.items()},
                by_family={fam:{a:aggregate(v) for a,v in arm.items()} for fam,arm in family_results.items()},
                reader_executed=False,semantic_citation_precision=None,
                causal_advantage_claim=False,production_accepted=False)
    exclusive(target_file,report)
    return report


def _select_reader_questions(public,per_family):
    if type(per_family) is not int or not 1<=per_family<=4:
        raise ValueError("pre-registered per-family reader budget 1..4")
    return {q["id"] for g in public["families"]
            for q in sorted(g["questions"],key=lambda item:(
                hashlib.sha256(("hepta.fixed-reader.v1\0"+item["id"]).encode()).digest(),item["id"]))[:per_family]}


def reader_inputs(public_dir,run_dir,per_family=2):
    """Pure deterministic evidence assembly, no pretrained inference required."""
    public,manifest,journal,seal=_checked_run(public_dir,run_dir)
    chosen_ids=_select_reader_questions(public,per_family)
    indexed={g["family"]:({d["id"]:d for d in g["sources"]},
                          {q["id"]:q for q in g["questions"]}) for g in public["families"]}
    for row in journal:
        qid=row["question_id"]
        if qid not in chosen_ids:
            continue
        docs,qs=indexed[row["family"]]
        for arm in READER_ARMS:
            identifiers=[] if arm=="empty" else row["predictions"][arm]
            # Exact source excerpt at byte offset 0; never silently synthesize
            # an answer or add source text absent from ranked evidence.
            evidence=[dict(label=f"E{i}",source_id=did,source_start=0,
                           text=docs[did]["speaker"]+": "+docs[did]["text"][:384])
                      for i,did in enumerate(identifiers,start=1)]
            yield dict(question_id=qid,family=row["family"],arm=arm,
                       question=qs[qid]["text"],evidence=evidence,
                       public_sha256=manifest["public_sha256"],
                       ranked_journal_sha256=seal["journal_sha256"])


def _answer_with_fixed_reader(reader,example,max_tokens):
    from bundle_reader import SYSTEM
    from native import digest
    ids=reader.tokenizer.apply_chat_template([
        dict(role="system",content=SYSTEM),
        dict(role="user",content=json.dumps(dict(
            question=example["question"],evidence=[dict(label=e["label"],
                  text=e["text"]) for e in example["evidence"]]),ensure_ascii=False))],
        tokenize=True,add_generation_prompt=True)
    if not ids or len(ids)>2048 or len(ids)+max_tokens>reader.model.config.max_position_embeddings:
        return dict(status="unavailable",input_tokens=len(ids),reason="prompt-budget",answer=None)
    tensor=torch.tensor([ids],dtype=torch.long)
    started=time.perf_counter()
    with torch.inference_mode():
        output=reader.model.generate(input_ids=tensor,attention_mask=torch.ones_like(tensor),
            max_new_tokens=max_tokens,do_sample=False,num_beams=1,use_cache=True,
            eos_token_id=reader.tokenizer.eos_token_id,
            pad_token_id=reader.tokenizer.eos_token_id)
    emitted=output[0,len(ids):].tolist()
    answer=reader.tokenizer.decode(emitted,skip_special_tokens=True,clean_up_tokenization_spaces=False)
    if not answer.strip():
        return dict(status="failed",input_tokens=len(ids),reason="empty-generation",answer=None)
    return dict(status="succeeded",input_tokens=len(ids),generated_tokens=len(emitted),
                input_ids_digest=digest(ids),generated_ids_digest=digest(emitted),
                seconds=time.perf_counter()-started,answer=answer,
                reader_identity=reader.identity,reader_profile=reader.profile,
                evidence_source_ids=[v["source_id"] for v in example["evidence"]],
                no_answer_postprocessing=True,semantic_citation_precision=None)


def read_with_fixed_reader(public_dir, run_dir, reader_dir, target_dir, *, per_family=2,max_tokens=48):
    """Fixed SmolLM2 diagnostic on ranked evidence, never on answer labels."""
    if type(max_tokens) is not int or not 8<=max_tokens<=64:
        raise ValueError("bounded registered decoder budget required")
    if Path(public_dir,"private.json").exists():
        raise ValueError("hidden labels visible to Reader")
    from reader_reference import ReferenceReader
    from pretrained import file_inventory
    from native import digest
    # Actual reader bytes are bound before loading any weights.
    reader_dir=Path(reader_dir)
    if not reader_dir.is_dir() or reader_dir.is_symlink():
        raise ValueError("reader directory must be regular")
    model_inventory=file_inventory(reader_dir)
    if digest(model_inventory) != REGISTERED_READER_IDENTITY:
        raise ValueError("unregistered frozen Reader weights")
    reader=ReferenceReader(reader_dir,expected_inventory=REGISTERED_READER_IDENTITY)
    out=Path(target_dir);out.mkdir(exist_ok=False)
    records=[]
    for example in reader_inputs(public_dir,run_dir,per_family=per_family):
        try:
            observed=_answer_with_fixed_reader(reader,example,max_tokens)
        except Exception as error:
            observed=dict(status="failed",reason=type(error).__name__,answer=None)
        records.append(dict(question_id=example["question_id"],arm=example["arm"],
                            family=example["family"],evidence_ids=[s["source_id"] for s in example["evidence"]],
                            result=observed))
    reader.verify_frozen()
    expected=per_family*10*len(READER_ARMS)
    if len(records)!=expected:
        raise ValueError("incomplete fixed-reader record census")
    digest_records=exclusive(out/"reader-journal.json",records)
    meta=dict(schema=READER_SCHEMA,source_journal_sha256=strict_json(read_regular(Path(run_dir)/"seal.json"))["journal_sha256"],
              reader_journal_sha256=digest_records,planned=expected,
              reader_identity=reader.identity,reader_profile=reader.profile,
              max_new_tokens=max_tokens,per_family=per_family,
              trainable_reader_parameters=0,labels_visible=False,
              independent_semantic_judge=False,production_accepted=False)
    exclusive(out/"reader-seal.json",meta)
    return meta


def _token_f1(predicted,reference):
    a=tokens(predicted);b=tokens(reference)
    if not a or not b:return float(not a and not b)
    x,y=Counter(a),Counter(b);common=sum((x&y).values())
    if not common:return 0.0
    p,r=common/len(a),common/len(b)
    return 2*p*r/(p+r)


def review_reader(prepared_dir,run_dir,reader_dir,target):
    public,manifest,journal,rank_seal=_checked_run(prepared_dir,run_dir,reviewer=True)
    reader_seal=strict_json(read_regular(Path(reader_dir)/"reader-seal.json"))
    records_raw=read_regular(Path(reader_dir)/"reader-journal.json")
    if (reader_seal.get("schema")!=READER_SCHEMA
        or reader_seal.get("source_journal_sha256")!=rank_seal["journal_sha256"]
        or reader_seal.get("reader_journal_sha256")!=sha256(records_raw)
        or reader_seal.get("labels_visible") is not False):
        raise ValueError("reader journal not frozen against source ranking")
    records=strict_json(records_raw)
    hidden_raw=read_regular(Path(prepared_dir)/"private.json")
    if sha256(hidden_raw)!=manifest["private_sha256"]:
        raise ValueError("reader reference not pinned")
    answers=strict_json(hidden_raw)["annotations"]
    expected={q["id"] for g in public["families"] for q in g["questions"]}
    ids=set(); scores=defaultdict(list);rejected=defaultdict(int)
    ranking={(row["question_id"],arm):identifiers
             for row in journal for arm,identifiers in row["predictions"].items()}
    for record in records:
        if (not isinstance(record,dict) or set(record)!={"question_id","family","arm","evidence_ids","result"}
            or record["question_id"] not in expected or record["arm"] not in READER_ARMS
            or (record["question_id"],record["arm"]) in ids):
            raise ValueError("duplicate or foreign fixed-reader outcome")
        ids.add((record["question_id"],record["arm"]))
        expected_sources=[] if record["arm"]=="empty" else ranking[(record["question_id"],record["arm"])]
        if record["evidence_ids"] != expected_sources:
            raise ValueError("reader supplied or omitted evidence differs from sealed ranking")
        result=record["result"]
        if not isinstance(result,dict) or result.get("status") not in ("succeeded","failed","unavailable"):
            raise ValueError("unknown reader execution status")
        if result["status"]!="succeeded":
            rejected[record["arm"]]+=1
            continue
        answer=answers[record["question_id"]].get("answer")
        if not isinstance(answer,str) or not answer.strip():
            rejected[record["arm"]]+=1
            continue
        scores[record["arm"]].append(_token_f1(result["answer"],answer))
    expected_ids=_select_reader_questions(public,reader_seal["per_family"])
    if ids!={(qid,arm) for qid in expected_ids for arm in READER_ARMS}:
        raise ValueError("incomplete blinded reader census")
    report=dict(schema=READER_SCHEMA,rank_journal_sha256=rank_seal["journal_sha256"],
                reader_journal_sha256=reader_seal["reader_journal_sha256"],
                by_arm={a:dict(planned=len(expected_ids),scored=len(scores[a]),
                               failures_or_unscored=rejected[a],
                               diagnostic_token_f1_mean=sum(scores[a])/len(scores[a]) if scores[a] else None)
                        for a in READER_ARMS},
                reference_answer_comparison_independent=False,
                semantic_citation_precision=None,source_family_count=10,
                statistically_significant_superiority=False,production_accepted=False)
    exclusive(target,report)
    return report


def main(argv=None):
    argv=sys.argv if argv is None else argv
    if len(argv)<2:
        raise SystemExit("prepare|run|review|reader|review-reader")
    action=argv[1]
    if action=="prepare" and len(argv)==4:
        result=prepare_full(argv[2],argv[3])
    elif action=="run" and len(argv)==5:
        result=run(argv[2],argv[3],argv[4])
    elif action=="review" and len(argv)==5:
        result=review(argv[2],argv[3],argv[4])
    elif action=="reader" and len(argv)==6:
        result=read_with_fixed_reader(argv[2],argv[3],argv[4],argv[5])
    elif action=="review-reader" and len(argv)==6:
        result=review_reader(argv[2],argv[3],argv[4],argv[5])
    else:
        raise SystemExit("usage: prepare DATASET NEW_DIR | run PUBLIC ENCODER NEW_DIR | review PREPARED RUN NEW_REPORT | reader PUBLIC RUN READER NEW_DIR | review-reader PREPARED RUN READER_RUN NEW_REPORT")
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2))

if __name__=="__main__":
    main()
