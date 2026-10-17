"""V13: original-source, no-model-cost lexical retrieval diagnostics.

This is SHADOW / DENY_ALL. Precommit -> rank (source only) -> score (label owner).
No pretrained forward, model training, Reader accuracy, or prospective qualification.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import time
import unicodedata

SCHEMA = "hepta.stem.v13.cheap-original-retrieval.shadow.v1"
CORPUS_SHA = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
OLD = ("conv-26", "conv-30", "conv-41", "conv-42", "conv-43", "conv-44")
HELD = ("conv-47", "conv-48", "conv-49", "conv-50")
QUESTION_COUNTS = {"conv-26":199, "conv-30":105, "conv-41":193, "conv-42":260,
    "conv-43":242, "conv-44":158, "conv-47":190, "conv-48":239, "conv-49":196, "conv-50":204}
WORD = re.compile(r"\w+", re.UNICODE)
ARMS = ("bm25", "phrase", "coverage", "char", "phrase_char", "char_only")
PRIMARY = "phrase_char" # chosen in source before any heldout scoring
K_VALUES = (3,16,32)
CONFIG = {"schema":SCHEMA+".frozen-config", "arms":list(ARMS), "primary":PRIMARY,
          "bm25_k1":1.2, "bm25_b":0.75, "phrase_bonus":0.7,
          "coverage_weights":[0.85,0.15], "char_weights":[0.8,0.2],
          "phrase_char_weights":[0.7,0.1,0.2], "trigram_length":3,
          "top_k":list(K_VALUES), "family_split":{"train":list(OLD),"heldout":list(HELD)},
          "gold_admitted_before_rank":False, "production_authorized":False}


def jbytes(obj):
    return json.dumps(obj,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode("utf-8")

def digest(obj):return sha256(jbytes(obj)).hexdigest()

def file_sha(path):
    h=sha256()
    with Path(path).open("rb") as f:
        for part in iter(lambda:f.read(1<<20),b""):h.update(part)
    return h.hexdigest()

def read_json(path):
    def pairs(rows):
        result={}
        for k,v in rows:
            if k in result:raise ValueError("duplicate JSON key")
            result[k]=v
        return result
    def reject(x):raise ValueError("nonfinite JSON constant: "+x)
    return json.loads(Path(path).read_bytes(),object_pairs_hook=pairs,parse_constant=reject)

def write_once(path,data):
    with Path(path).open("xb") as f:
        f.write(jbytes(data)+b"\n")
        f.flush()
        import os
        os.fsync(f.fileno())


def source_only(raw):
    if not isinstance(raw,list) or len(raw)!=10:raise ValueError("ten complete families required")
    families={}
    for item in raw:
        if type(item)!=dict or not isinstance(item.get("sample_id"),str):raise ValueError("family")
        fam=item["sample_id"]
        if fam in families or fam not in QUESTION_COUNTS:raise ValueError("family roster")
        conv=item.get("conversation"); qa=item.get("qa")
        if type(conv)!=dict or type(qa)!=list or len(qa)!=QUESTION_COUNTS[fam]:raise ValueError("question count")
        docs=[]; questions=[]; seen=set()
        for key,turns in conv.items():
            if not re.fullmatch(r"session_\d+",key):continue
            if type(turns)!=list:raise ValueError("session")
            for t in turns:
                if type(t)!=dict or not all(k in t for k in ("speaker","dia_id","text")):
                    raise ValueError("source turn")
                if not all(isinstance(t[k],str) for k in ("speaker","dia_id","text")):
                    raise ValueError("source type")
                sid=t["dia_id"]
                if not sid or sid in seen or not t["text"].strip():raise ValueError("source id/content")
                seen.add(sid)
                docs.append({"id":sid,"text":t["speaker"]+": "+t["text"]})
        for i,q in enumerate(qa):
            if type(q)!=dict or not isinstance(q.get("question"),str) or not q["question"].strip():
                raise ValueError("question")
            questions.append({"id":fam+"/q"+str(i),"text":q["question"]})
        if len(docs)<100 or len(seen)!=len(docs):raise ValueError("source census")
        families[fam]={"passages":docs,"questions":questions}
    if set(families)!=set(QUESTION_COUNTS):raise ValueError("missing family")
    return {"schema":SCHEMA+".source-only","original_dataset_sha256":CORPUS_SHA,
        "family_order":list(sorted(families)),"families":families,
        "contains_gold_or_answers":False,"future_windows":0,"production_authorized":False}


def assert_source(packet):
    if type(packet)!=dict or set(packet)!={"schema","original_dataset_sha256","family_order","families","contains_gold_or_answers","future_windows","production_authorized"}:
        raise ValueError("source key intrusion")
    if packet["schema"]!=SCHEMA+".source-only" or packet["original_dataset_sha256"]!=CORPUS_SHA:
        raise ValueError("source provenance")
    if packet["contains_gold_or_answers"] is not False or packet["production_authorized"] is not False or packet["future_windows"]!=0:
        raise ValueError("gold/authority intrusion")
    if packet["family_order"]!=sorted(QUESTION_COUNTS) or set(packet["families"])!=set(QUESTION_COUNTS):raise ValueError("family identity")
    for fam,entry in packet["families"].items():
        if type(entry)!=dict or set(entry)!={"passages","questions"}:raise ValueError("entry fields")
        docs=entry["passages"];qs=entry["questions"]
        if len(docs)<100 or len(qs)!=QUESTION_COUNTS[fam]:raise ValueError("census mismatch")
        ids=set()
        for d in docs:
            if type(d)!=dict or set(d)!={"id","text"} or type(d["id"])!=str or not d["id"] or type(d["text"])!=str or not d["text"].strip() or d["id"] in ids:raise ValueError("source field")
            ids.add(d["id"])
        for i,q in enumerate(qs):
            if type(q)!=dict or set(q)!={"id","text"} or q["id"]!=fam+"/q"+str(i) or type(q["text"])!=str or not q["text"].strip():raise ValueError("question field")


def words(text):return tuple(x.lower() for x in WORD.findall(text))

def grams(tokens):
    """Within-word unicode NFKC char trigrams, avoiding ungrounded cross-word links."""
    pieces=[]
    for token in tokens:
        norm=unicodedata.normalize("NFKC",token).lower()
        if len(norm)<3:pieces.append(norm)
        else:pieces.extend(norm[i:i+3] for i in range(len(norm)-2))
    return Counter(pieces)

class Index:
    def __init__(self,passages):
        if not passages or len(passages)<3:raise ValueError("passages")
        self.passages=passages
        self.tokens=[words(p["text"]) for p in passages]
        self.tfs=[Counter(x) for x in self.tokens]
        self.df=Counter(t for row in self.tokens for t in set(row))
        self.avglen=sum(map(len,self.tokens))/len(self.tokens)
        self.char_tf=[grams(x) for x in self.tokens]
        self.char_df=Counter(k for row in self.char_tf for k in row)
        n=len(self.tokens)
        self.word_idf={t:math.log1p((n-d+0.5)/(d+0.5)) for t,d in self.df.items()}
        self.char_idf={t:math.log1p((n-d+0.5)/(d+0.5)) for t,d in self.char_df.items()}
        self.char_norm=[math.sqrt(sum((freq*self.char_idf[term])**2 for term,freq in row.items())) for row in self.char_tf]
        self.bigrams=[Counter(zip(seq,seq[1:])) for seq in self.tokens]

    def rank(self,question):
        q=words(question)
        if not q:raise ValueError("blank question")
        qset=set(q)
        qbig=list(zip(q,q[1:]))
        widf=self.word_idf
        qweight=sum(widf.get(t,0.) for t in qset)
        phrase_total=sum(min(widf.get(x,0.),widf.get(y,0.)) for x,y in qbig)
        qchar=grams(q)
        qc={term:freq*self.char_idf.get(term,0.) for term,freq in qchar.items()}
        qnorm=math.sqrt(sum(v*v for v in qc.values()))
        bm=[];cov=[];phr=[];char=[]
        for i,tf in enumerate(self.tfs):
            length=len(self.tokens[i]);length_scale=1.2*(0.25+0.75*length/self.avglen)
            b=sum(widf.get(t,0.)*(f*2.2)/(f+length_scale) for t in qset if (f:=tf.get(t,0))>0)
            bm.append(b)
            cov.append(sum(widf.get(t,0.) for t in qset if t in tf)/(qweight or 1.))
            phr.append(sum(min(widf.get(x,0.),widf.get(y,0.)) for x,y in qbig if self.bigrams[i].get((x,y),0)) /(phrase_total or 1.))
            dnorm=self.char_norm[i]
            cp=sum(v*self.char_tf[i].get(k,0)*self.char_idf.get(k,0) for k,v in qc.items())
            char.append(cp/(qnorm*dnorm) if qnorm>0 and dnorm>0 else 0.)
        high=max(bm)
        bn=[v/high if high>0 else 0. for v in bm]
        out={"bm25":bm,
             "phrase":[b+CONFIG["phrase_bonus"]*p for b,p in zip(bm,phr)],
             "coverage":[.85*b+.15*c for b,c in zip(bn,cov)],
             "char":[.8*b+.2*c for b,c in zip(bn,char)],
             "phrase_char":[.7*b+.1*p+.2*c for b,p,c in zip(bn,phr,char)],
             "char_only":char}
        if set(out)!=set(ARMS) or any(len(scores)!=len(self.passages) or any(not math.isfinite(v) for v in scores) for scores in out.values()):raise ValueError("invalid scores")
        return {arm:[self.passages[i]["id"] for i in sorted(range(len(self.passages)),key=lambda j:(-scores[j],self.passages[j]["id"]))[:32]] for arm,scores in out.items()}


def plan_for(src):
    return {"schema":SCHEMA+".plan", "frozen_config":CONFIG,
       "config_sha256":digest(CONFIG),"source_sha256":digest(src),
       "original_dataset_sha256":CORPUS_SHA,
       "precommitted_primary":PRIMARY,
       "pre_rank_gold_loaded":False,"selected_on_heldout":False,
       "production_authorized":False}

def rank_source(src,plan):
    assert_source(src)
    if plan!=plan_for(src):raise ValueError("frozen plan changed")
    t0=time.process_time();wall=time.perf_counter()
    routes=[];nsource=0
    for fam in src["family_order"]:
        a=src["families"][fam]; docs=a["passages"]
        nsource+=len(docs)
        index=Index(docs)
        for q in a["questions"]:
            arms=index.rank(q["text"])
            routes.append({"id":q["id"],"family":fam,"top32":arms})
    if len(routes)!=1986 or nsource!=5882:raise ValueError("original complete roster changed")
    receipt={"schema":SCHEMA+".ranked", "plan_sha256":digest(plan),"source_sha256":digest(src),
             "config_sha256":digest(CONFIG),"original_dataset_sha256":CORPUS_SHA,
             "cases":routes,"case_count":len(routes),"source_turn_count":nsource,
             "model_forward_count":0,"trained_head_parameters":0,
             "phase_cpu_seconds":time.process_time()-t0,"phase_wall_seconds":time.perf_counter()-wall,
             "publisher_gold_loaded":False,"production_authorized":False}
    return receipt


def gold_for(raw,src):
    """Only in score process, after route bytes are sealed."""
    result={};expected={q["id"] for fam in src["family_order"] for q in src["families"][fam]["questions"]}
    for item in raw:
        fam=item["sample_id"]
        known={d["id"] for d in src["families"][fam]["passages"]}
        for i,q in enumerate(item["qa"]):
            refs=q.get("evidence")
            if type(refs)!=list or not refs or any(type(v)!=str or v not in known for v in refs):result[fam+"/q"+str(i)]=None
            else:result[fam+"/q"+str(i)]=set(refs)
    if set(result)!=expected:raise ValueError("missing publisher annotation")
    return result


def validate_routes(src,plan,routes):
    assert_source(src)
    if plan!=plan_for(src) or type(routes)!=dict or routes.get("schema")!=SCHEMA+".ranked" or routes.get("plan_sha256")!=digest(plan) or routes.get("source_sha256")!=digest(src) or routes.get("config_sha256")!=digest(CONFIG):raise ValueError("bad immutable plan/route identity")
    if routes.get("case_count")!=1986 or routes.get("source_turn_count")!=5882 or routes.get("model_forward_count")!=0 or routes.get("trained_head_parameters")!=0 or routes.get("publisher_gold_loaded") is not False or routes.get("production_authorized") is not False:raise ValueError("false source rank authority")
    rows=routes.get("cases")
    if type(rows)!=list or len(rows)!=1986:raise ValueError("missing original requests")
    expected={q["id"]:(fam,{d["id"] for d in src["families"][fam]["passages"]}) for fam,a in src["families"].items() for q in a["questions"]}
    found=set()
    for row in rows:
        if type(row)!=dict or set(row)!={"id","family","top32"}:raise ValueError("source row injected")
        ident=row["id"]
        if ident not in expected or ident in found or row["family"]!=expected[ident][0]:raise ValueError("duplicate/swapped original case")
        found.add(ident)
        if type(row["top32"])!=dict or set(row["top32"])!=set(ARMS):raise ValueError("wrong arms")
        for arm,ids in row["top32"].items():
            if type(ids)!=list or len(ids)!=32 or any(type(x)!=str or x not in expected[ident][1] for x in ids) or len(set(ids))!=32:
                raise ValueError("fabricated/duplicate evidence")
    if found!=set(expected):raise ValueError("incomplete source-first census")


def aggregate(routes, gold):
    famcounts={};anycounts={};allcounts={};base={}
    for fam in QUESTION_COUNTS:
        famcounts[fam]={"n":QUESTION_COUNTS[fam],"unknown":0}
        anycounts[fam]={arm:{str(k):0 for k in K_VALUES} for arm in ARMS}
        allcounts[fam]={arm:{str(k):0 for k in K_VALUES} for arm in ARMS}
        base[fam]={arm:{"gain_vs_bm25":0,"loss_vs_bm25":0,"membership_changed":0} for arm in ARMS if arm!="bm25"}
    for row in routes["cases"]:
        fam=row["family"];gid=row["id"]
        g=gold[gid]
        if g is None:
            famcounts[fam]["unknown"]+=1
            continue
        bh=bool(g.intersection(row["top32"]["bm25"][:3]))
        for arm,ids in row["top32"].items():
            for k in K_VALUES:
                hits=set(ids[:k]).intersection(g)
                anycounts[fam][arm][str(k)]+=bool(hits)
                allcounts[fam][arm][str(k)]+=g.issubset(set(ids[:k]))
            if arm!="bm25":
                ch=bool(g.intersection(ids[:3]))
                base[fam][arm]["gain_vs_bm25"]+=int(ch and not bh)
                base[fam][arm]["loss_vs_bm25"]+=int(bh and not ch)
                base[fam][arm]["membership_changed"]+=int(set(ids[:3])!=set(row["top32"]["bm25"][:3]))
    return famcounts,anycounts,allcounts,base


def score_result(src,plan,routes,raw):
    validate_routes(src,plan,routes)
    gold=gold_for(raw,src)
    famcounts,anycounts,allcounts,base=aggregate(routes,gold)
    if sum(famcounts[f]["unknown"] for f in HELD)!=7:
        raise ValueError("original unsupported publisher refs changed")
    if sum(anycounts[f]["bm25"]["3"] for f in HELD)!=372:
        raise ValueError("BM25 parity with original V9 model-owner protocol FAILED")
    by_arm={}
    for arm in ARMS:
        by_arm[arm]={"heldout_any_hit3":sum(anycounts[f][arm]["3"] for f in HELD),
                     "heldout_any_hit16":sum(anycounts[f][arm]["16"] for f in HELD),
                     "heldout_any_hit32":sum(anycounts[f][arm]["32"] for f in HELD),
                     "heldout_all_hit3":sum(allcounts[f][arm]["3"] for f in HELD),
                     "train_any_hit3":sum(anycounts[f][arm]["3"] for f in OLD),
                     "family_hit3":{f:anycounts[f][arm]["3"] for f in HELD},
                     "family_delta_vs_bm25":{f:anycounts[f][arm]["3"]-anycounts[f]["bm25"]["3"] for f in HELD}}
    public={"schema":SCHEMA+".public-negative.v1", "source_sha256":digest(src),
        "plan_sha256":digest(plan),"raw_rank_sha256":digest(routes),"original_dataset_sha256":CORPUS_SHA,
        "primary_precommitted":PRIMARY,"heldout_question_count":sum(QUESTION_COUNTS[f] for f in HELD),
        "independent_heldout_source_groups":len(HELD),"total_questions":1986,
        "publisher_unknown_heldout":sum(famcounts[f]["unknown"] for f in HELD),
        "fixed_arms":list(ARMS),"per_arm":by_arm,
        "per_family_pairwise_vs_bm25":{f:base[f] for f in HELD},
        "rank_process_cpu_seconds":routes["phase_cpu_seconds"],"rank_process_wall_seconds":routes["phase_wall_seconds"],
        "trained_head_updates":0,"pretrained_encoder_forwards":0,"original_reader_calls":0,
        "future_calendar_windows":0,"independent_semantic_qa":None,"equal_full_lifecycle_cost_to_v11":False,
        "full_task_superiority_verified":False,"stem_winner_verified":False,
        "production_authorized":False,"original_v6_seed41_retention_closed":False}
    return public


def _read_original(original):
    if Path(original).is_symlink() or file_sha(original)!=CORPUS_SHA:raise ValueError("original corpus file SHA mismatch")
    return read_json(original)

def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest="operation",required=True)
    for op in ("prepare","rank","score"):
        a=sub.add_parser(op)
        if op in ("prepare","score"):a.add_argument("--original",type=Path,required=True)
        if op in ("rank","score"):a.add_argument("--source",type=Path,required=True);a.add_argument("--plan",type=Path,required=True)
        if op=="prepare":a.add_argument("--source",type=Path,required=True);a.add_argument("--plan",type=Path,required=True)
        if op=="score":a.add_argument("--rank",type=Path,required=True)
        a.add_argument("--output",type=Path,required=op!="prepare")
    a=p.parse_args()
    if a.operation=="prepare":
        source=source_only(_read_original(a.original));assert_source(source);plan=plan_for(source)
        write_once(a.source,source);write_once(a.plan,plan)
        print(json.dumps({"phase":"prepare","source_sha256":digest(source),"gold_exported":False}))
    elif a.operation=="rank":
        source=read_json(a.source);plan=read_json(a.plan)
        ranked=rank_source(source,plan);write_once(a.output,ranked)
        print(json.dumps({"phase":"rank","cases":ranked["case_count"],"source_turn_count":ranked["source_turn_count"],"rank_sha256":digest(ranked),"cpu_seconds":ranked["phase_cpu_seconds"]}))
    else:
        source=read_json(a.source);plan=read_json(a.plan);ranked=read_json(a.rank)
        public=score_result(source,plan,ranked,_read_original(a.original))
        write_once(a.output,public)
        print(json.dumps({"phase":"score","bm25":public["per_arm"]["bm25"]["heldout_any_hit3"],"precommitted":public["per_arm"][PRIMARY]["heldout_any_hit3"],"scientific_promotion":False}))

if __name__=="__main__":main()
