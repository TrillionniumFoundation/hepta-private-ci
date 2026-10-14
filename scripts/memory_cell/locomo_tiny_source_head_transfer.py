"""Real frozen-public LoCoMo source-only 10-parameter Head; honest family transfer.

Original published LoCoMo 6/2/2 family-proxy split. Train on source-text
self-reconstruction ONLY (no QA answers); seal predictions BEFORE original
held-out source-support targets enter scorer. No Reader/model generation or
human sufficiency judgement; test families are published, not future sources.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import re
import time
import zipfile

PROFILE = "hepta.memorycell.locomo-selfsupervised-tiny-head-transfer.v1"
PUB_SHA = "51e18514c68f31220f4dcd072914f6e015aa9733b6c5b4a4d4e3b14dac25ec37"
DEC_SHA = "3fb1c3272314d31b42ece1c74aa0250e2ecb06c6060cb011071d4654fef6f097"
POP_SHA = "f53ee0986825f30ec4503b1698639e230832d1c05351c689cb55ebdc4f01d6de"
HISTORY_SHA = "b42a90e01df2eb8d2da8a77e6218dc1124b7c19005f52d23ef8c1acd0aeed5cc"
GENERATING = "fcc24ad653700ad5f47f09350cf7815242dc5de8"
ARMS = ("frozen_lexical_k8", "frozen_recent_k8", "trained_head_k8", "shuffled_null_k8")
FEATURES = (
    "query_token_document_coverage", "document_token_query_coverage",
    "log_overlap_count", "train_only_idf_overlap", "query_bigram_overlap",
    "capitalized_name_overlap", "length_inverse_log", "log_document_length",
    "candidate_recency_proxy", "intercept",
)
STEPS = 192
STOP = frozenset("the a an and or of to for on in at is are was were does do did how what where when who why which you your that with from have has had it this they i we our their its would could should about by after before also but kind".split())
WORD = re.compile(r"[a-z0-9]+")
NAME = re.compile(r"\b[A-Z][a-z]{2,}\b")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def strict(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate original JSON field")
            result[key] = value
        return result

    return json.loads(data, object_pairs_hook=unique, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite original JSON")))


def regular(path, *, limit=4_000_000):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise ValueError("missing or unbounded immutable public artifact")
    return path.read_bytes()


def original_zip(path, pin, expected):
    raw = regular(path, limit=7_000_000)
    if sha(raw) != pin:
        raise ValueError("immutable external ZIP SHA256 differs")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if set(names) != set(expected) or len(names) != len(expected):
            raise ValueError("unregistered or duplicate ZIP member")
        for item in archive.infolist():
            if item.is_dir() or item.file_size > 5_000_000:
                raise ValueError("unbounded original ZIP content")
        content = {name: archive.read(name) for name in expected}
    if "SHA256SUMS" in content:
        declared = {}
        for line in content["SHA256SUMS"].decode().splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?([a-zA-Z0-9_.\-/]+)", line)
            if not match or match[2] in declared:
                raise ValueError("invalid original SHA256SUMS entry")
            declared[match[2]] = match[1]
        if set(declared) != set(content) - {"SHA256SUMS"} or any(sha(content[k]) != v for k,v in declared.items()):
            raise ValueError("original ZIP inner member mismatch")
    return content


def tokens(text):
    if not isinstance(text,str) or len(text) > 100_000:
        raise ValueError("bounded source or query text required")
    return tuple(t for t in WORD.findall(text.lower()) if len(t) >= 2 and t not in STOP)


def features(question, document, idf, recency):
    q = set(tokens(question)); d = set(tokens(document))
    match = q & d
    denom_q = len(q) or 1; denom_d = len(d) or 1
    qb = set(zip(tokens(question), tokens(question)[1:]))
    db = set(zip(tokens(document), tokens(document)[1:]))
    names_q = set(NAME.findall(question)); names_d = set(NAME.findall(document))
    return (
        len(match) / denom_q, len(match) / denom_d, math.log1p(len(match)),
        sum(idf.get(t,0.0) for t in match)/denom_q,
        len(qb & db)/(len(qb) or 1),
        len(names_q & names_d)/(len(names_q) or 1),
        1.0/math.log1p(max(len(d),2)), math.log1p(len(d))/10.0,
        recency, 1.0,
    )


def loaded_public(public_zip, decisions_zip):
    public = original_zip(public_zip, PUB_SHA, ("histories-manifest.json","histories.jsonl","population.json"))
    frozen = original_zip(decisions_zip, DEC_SHA, ("SHA256SUMS","receipt.json","decisions.jsonl"))
    if sha(public["population.json"]) != POP_SHA or sha(public["histories.jsonl"]) != HISTORY_SHA:
        raise ValueError("published native population/history SHA drift")
    manifest, population, receipt = [strict(raw) for raw in (public["histories-manifest.json"],public["population.json"],frozen["receipt.json"])]
    if (manifest["histories_sha256"] != HISTORY_SHA or manifest["population_sha256"] != POP_SHA
        or manifest["source_commit"] != GENERATING or manifest["model_answers_generated"] != 0
        or population["generating_source_commit"] != GENERATING
        or population["model_input_contains_answers"] is not False
        or population["schema"] != "hepta.memorycell.locomo-family-only-pilot.v1"
        or population["census"]["split_family_proxies"] != {"train":6,"selection":2,"evaluation":2}
        or {k:len(v) for k,v in population["splits"].items()} != {"train":48,"selection":16,"evaluation":16}
        or receipt["generating_commit"] != GENERATING or receipt["labels_opened"] is not False
        or receipt["original_decisions_sha256"] != sha(frozen["decisions.jsonl"])):
        raise ValueError("original label-blind 6/2/2 source census drift")
    histories = [strict(raw) for raw in public["histories.jsonl"].splitlines()]
    if len(histories) != 5882 or len({r["identity"] for r in histories}) != len(histories):
        raise ValueError("missing published original LoCoMo documents")
    docs = {r["identity"]:r for r in histories}
    scopes = defaultdict(set)
    for r in histories:
        if (r["root"] != r["scope"] or not isinstance(r["content"],str)
            or not r["content"] or not r["identity"].startswith(r["scope"]+"/")):
            raise ValueError("cross-root or empty published conversation evidence")
        scopes[r["scope"]].add(r["identity"])
    family_splits={}
    for split,cases in population["splits"].items():
        for case in cases:
            family=case["family_proxy_digest"]
            if family_splits.setdefault(family,split)!=split or set(case["source_ids"]) != scopes[case["scope"]]:
                raise ValueError("source family/scope or exact candidate history drift")
    if len(family_splits)!=10:
        raise ValueError("same native family entered multiple partitions")
    decisions=[strict(line) for line in frozen["decisions.jsonl"].splitlines()]
    if len(decisions)!=480:
        raise ValueError("original six-arm source-only decision census incomplete")
    catalog={}
    for row in decisions:
        key=(row["question_id"],row["arm"])
        if key in catalog or not set(row["selected"]).issubset(docs):
            raise ValueError("duplicate or extraneous original retrieval decision")
        catalog[key] = row
    for cases in population["splits"].values():
        for case in cases:
            for arm in ("lexical_k8","recent_k8"):
                item=catalog[(case["question_id"],arm)]
                if (
                    len(item["selected"]) != 8
                    or item["source_census_sha256"] != case["source_census_sha256"]
                    or item["family_proxy_digest"] != case["family_proxy_digest"]
                    or item["split"] != next(
                        split for split, group in population["splits"].items()
                        if case in group
                    )
                    or not set(item["selected"]).issubset(case["source_ids"])
                    or item["selected_source_bytes"] != sum(
                        len(docs[key]["content"].encode())
                        for key in item["selected"]
                    )
                ):
                    raise ValueError("original strongest frozen retrieval decision drift")
    return population,docs,catalog


def idf_from_train(population, docs):
    train_scopes={c["scope"] for c in population["splits"]["train"]}
    corpus=[doc for doc in docs.values() if doc["scope"] in train_scopes]
    counter=Counter(t for doc in corpus for t in set(tokens(doc["content"])))
    return {t:math.log((len(corpus)+1)/(n+1)) for t,n in counter.items()}


def pseudo_training_data(population, docs, idf):
    """Train only from self-identified source passages, not benchmark QA labels."""
    train_scopes=sorted({c["scope"] for c in population["splits"]["train"]})
    if len(train_scopes)!=6:
        raise ValueError("six native training families required")
    rows=[]
    for scope in train_scopes:
        ids=sorted(k for k,d in docs.items() if d["scope"]==scope)
        for docid in ids:
            words=list(dict.fromkeys(tokens(docs[docid]["content"])))
            if len(words)<4:
                continue
            rank=sorted(words,key=lambda w:(-idf.get(w,0),w))
            query=" ".join(rank[:min(7,len(rank))])
            negative=sorted((k for k in ids if k!=docid), key=lambda k:sha(canonical(("negative",docid,k))))[:7]
            examples=[docid]+negative
            vectors=[features(query,docs[k]["content"],idf,recency=(i+1)/(len(ids)+1)) for i,k in enumerate(examples)]
            rows.append((docid,query,vectors))
    if len(rows)<100:
        raise ValueError("insufficient actual training-family self-supervision")
    return rows


def train(public_zip, decisions_zip, output):
    """Actually optimize 10 float64 parameters, before ever opening gold ZIP."""
    import torch
    population, docs, _ = loaded_public(public_zip,decisions_zip)
    idf=idf_from_train(population,docs)
    rows=pseudo_training_data(population,docs,idf)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(20261014)
        results={}
        for arm in ("trained_head_k8","shuffled_null_k8"):
            theta=torch.nn.Parameter(torch.zeros(10,dtype=torch.float64))
            opt=torch.optim.AdamW([theta],lr=0.035,weight_decay=0.01)
            start=theta.detach().clone();losses=[]
            for step in range(STEPS):
                key,query,values=rows[step%len(rows)]
                x=torch.tensor(values,dtype=torch.float64)
                logits=x@theta
                correct=0 if arm=="trained_head_k8" else (step%7)+1
                loss=torch.logsumexp(logits,0)-logits[correct]+0.001*(theta-start).square().sum()
                if not torch.isfinite(loss):
                    raise ValueError("nonfinite actual 10-param SGD")
                opt.zero_grad(set_to_none=True);loss.backward()
                torch.nn.utils.clip_grad_norm_([theta],1.0,error_if_nonfinite=True)
                opt.step();losses.append(float(loss.detach()))
            weights=theta.detach().tolist()
            delta=sum(v*v for v in weights)
            if not delta>0 or not all(math.isfinite(v) and abs(v)<100 for v in weights):
                raise ValueError("missing true gradient parameter update")
            results[arm]=dict(weights=weights,gradient_updates=STEPS,parameters=10,
                              update_squared_norm=delta,loss_first=losses[0],loss_final=losses[-1],
                              real_optimization=True,placebo_labels=(arm=="shuffled_null_k8"))
    output=Path(output)
    with output.open("xb") as frozen:
        frozen.write(canonical(dict(schema=PROFILE,source_commit=GENERATING,original_public_zip_sha256=PUB_SHA,
                                    original_retrieval_zip_sha256=DEC_SHA,features=FEATURES,
                                    train_family_count=6,training_source_examples=len(rows),train_question_labels_used=False,
                                    torch_runtime=str(torch.__version__),weights=results,
                                    evaluation_documents_seen_during_gradient_updates=False,
                                    generated_language_model_answers=0,production_accepted=False))+b"\n")
    return results


def choose8(question, candidates,docs,idf,weights):
    vectors=[(key,features(question,docs[key]["content"],idf,i/(len(candidates) or 1))) for i,key in enumerate(candidates)]
    return [key for key,v in sorted(vectors,key=lambda row:(-sum(a*b for a,b in zip(weights,row[1],strict=True)),row[0]))[:8]]


def predict(public_zip, decisions_zip, policy_file, output):
    population,docs,catalog=loaded_public(public_zip,decisions_zip)
    policy=strict(regular(policy_file))
    if (policy.get("schema")!=PROFILE or policy.get("original_public_zip_sha256")!=PUB_SHA
        or policy.get("original_retrieval_zip_sha256")!=DEC_SHA
        or policy.get("train_family_count")!=6
        or policy.get("train_question_labels_used") is not False
        or policy.get("evaluation_documents_seen_during_gradient_updates") is not False
        or set(policy.get("weights",{}))!={"trained_head_k8","shuffled_null_k8"}
        or any(r["gradient_updates"]!=STEPS or r["parameters"]!=10 or not r["real_optimization"] for r in policy["weights"].values())):
        raise ValueError("not a frozen actual source-only SGD checkpoint")
    idf=idf_from_train(population,docs)
    eval_cases=population["splits"]["evaluation"]
    output_rows=[]
    for case in eval_cases:
        candidates=case["source_ids"]
        for arm in ARMS:
            if arm.startswith("frozen_"):
                orig="lexical_k8" if arm=="frozen_lexical_k8" else "recent_k8"
                selected=catalog[(case["question_id"],orig)]["selected"]
            else:
                selected=choose8(case["question"],candidates,docs,idf,policy["weights"][arm]["weights"])
            selected_bytes=sum(len(docs[k]["content"].encode()) for k in selected)
            output_rows.append(dict(question_id=case["question_id"],family_proxy_digest=case["family_proxy_digest"],
                                    scope=case["scope"],arm=arm,selected=selected,selected_source_bytes=selected_bytes,
                                    source_census_sha256=case["source_census_sha256"],
                                    trainable_head_parameters=10 if "head" in arm or "shuffled" in arm else 0,
                                    generation_calls=0,heldout_gold_opened=False))
    if len(output_rows)!=16*len(ARMS):
        raise ValueError("expected 64 label-blind choices in 2 LoCoMo families")
    result=dict(schema=PROFILE,original_public_zip_sha256=PUB_SHA,original_retrieval_zip_sha256=DEC_SHA,
                policy_sha256=sha(regular(policy_file)),evaluation_family_proxy_count=2,
                evaluation_questions=16,independent_future_source_families=0,
                no_gold_evaluation_targets_read=True,model_generated_answers=0,
                external_published_benchmark_not_future=True,predictions=output_rows,
                production_accepted=False)
    with Path(output).open("xb") as frozen:
        frozen.write(canonical(result)+b"\n")
    return result



def seal(policy_file, predictions_file, output):
    """Commit before-gold source-selection bytes while target ZIP is absent."""
    policy, predictions = [strict(regular(x)) for x in (policy_file, predictions_file)]
    if (
        policy.get("schema") != PROFILE
        or policy.get("train_family_count") != 6
        or policy.get("train_question_labels_used") is not False
        or predictions.get("schema") != PROFILE
        or predictions.get("no_gold_evaluation_targets_read") is not True
        or predictions.get("model_generated_answers") != 0
        or predictions.get("evaluation_questions") != 16
        or len(predictions.get("predictions", [])) != 64
        or any(
            policy["weights"][arm]["gradient_updates"] != STEPS
            or policy["weights"][arm]["parameters"] != len(FEATURES)
            or not policy["weights"][arm]["real_optimization"]
            for arm in ("trained_head_k8", "shuffled_null_k8")
        )
    ):
        raise ValueError("source-only SGD or frozen before-gold journal missing")
    root = Path(output)
    report = dict(
        schema="hepta.memorycell.locomo-source-head-pre-target-seal.v1",
        original_published_pop_sha256=POP_SHA,
        original_published_decision_sha256=(
            "0c80477394abadce7cfd192404ac2531c571e14a9dabdefb371633c1ae3aec89"
        ),
        published_source_generating_commit=GENERATING,
        files={
            Path(policy_file).name: sha(regular(policy_file)),
            Path(predictions_file).name: sha(regular(predictions_file)),
        },
        actual_torch_training_updates=2 * STEPS,
        original_evaluation_family_groups=2,
        original_eval_questions=16,
        source_only_training=True,
        evaluation_target_bytes_opened=False,
        model_answers_generated=0,
        production_accepted=False,
    )
    with root.open("xb") as stream:
        stream.write(json.dumps(report, sort_keys=True, indent=2).encode() + b"\n")
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="phase",required=True)
    for phase in ("train", "predict", "seal"):
        action = sub.add_parser(phase)
        if phase != "seal":
            action.add_argument("public_zip", type=Path)
            action.add_argument("decisions_zip", type=Path)
        if phase != "train":
            action.add_argument("policy", type=Path)
        if phase == "seal":
            action.add_argument("predictions", type=Path)
        action.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.phase == "train":
        train(args.public_zip, args.decisions_zip, args.output)
    elif args.phase == "predict":
        predict(args.public_zip, args.decisions_zip, args.policy, args.output)
    else:
        seal(args.policy, args.predictions, args.output)


if __name__=="__main__":
    main()
