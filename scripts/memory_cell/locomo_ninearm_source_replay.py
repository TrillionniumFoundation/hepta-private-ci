"""Independent, model-free 9-arm LoCoMo retrieval replay over fixed published families.

Only supplied public ZIP + previous label-blind 6-arm decisions are read at
`retrieve`; selection labels enter only `select`; evaluation labels only
`evaluate`. This is a retrospective published-corpus pilot, not future data.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

GENERATING_COMMIT = "fcc24ad653700ad5f47f09350cf7815242dc5de8"
SOURCE_SHA = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
ORIGINAL_DECISIONS_SHA = "0c80477394abadce7cfd192404ac2531c571e14a9dabdefb371633c1ae3aec89"
POPULATION_SHA = "f53ee0986825f30ec4503b1698639e230832d1c05351c689cb55ebdc4f01d6de"
HISTORIES_SHA = "b42a90e01df2eb8d2da8a77e6218dc1124b7c19005f52d23ef8c1acd0aeed5cc"
ZIPS = {
    "public": ("locomo-public-38206328621.zip", "51e18514c68f31220f4dcd072914f6e015aa9733b6c5b4a4d4e3b14dac25ec37"),
    "decisions": ("locomo-frozen-decisions-38206328621.zip", "3fb1c3272314d31b42ece1c74aa0250e2ecb06c6060cb011071d4654fef6f097"),
    "selection": ("locomo-selection-targets-38206328621.zip", "ba8e2282034c5bb51fe319e8909e11d028619f85dfbbce5a6fff78284f9f220c"),
    "evaluation": ("locomo-evaluation-targets-38206328621.zip", "d09823324003ab431301e60fbbb280e216ca03b686e178d4f36fb6d492981978"),
    "old_policy": ("locomo-selected-policy-38206328621.zip", "3913c112ff417a1d9e6aa5c0f11e61286a98815fc32b4eb5df9da8bac59b690d"),
    "old_report": ("locomo-heldout-coverage-38206328621.zip", "41866a4dd8a14abd9430338942f5d8c7f9affccacc110b6a4f27be32f2846823"),
}
OLD_ARMS = ("lexical_k2", "lexical_k4", "lexical_k8", "recent_k2", "recent_k4", "recent_k8")
ARMS = OLD_ARMS + ("fusion_k2", "fusion_k4", "fusion_k8")
SPLITS = ("train", "selection", "evaluation")
WORD = re.compile(r"[a-z0-9]+")


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(raw):
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise ValueError("duplicate JSON field")
            out[k] = v
        return out
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError("nonfinite")))


def read_zip(root, name):
    file, checksum = ZIPS[name]
    p = root / file
    if p.is_symlink() or not p.is_file() or sha(p.read_bytes()) != checksum:
        raise ValueError(f"unaltered external ZIP pin required: {name}")
    with zipfile.ZipFile(p) as z:
        members = z.infolist()
        if not 1 <= len(members) <= 20 or sum(x.file_size for x in members) > 8 * 1024 * 1024:
            raise ValueError("archive file-count/size limit")
        out = {}
        for info in members:
            key = PurePosixPath(info.filename)
            if key.is_absolute() or ".." in key.parts or str(key) in out or info.is_dir() or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError("unsafe duplicate/symlink member")
            if "\\" in info.filename or info.file_size > 5 * 1024 * 1024:
                raise ValueError("unsafe path or unbounded file")
            out[str(key)] = z.read(info)
    if "SHA256SUMS" in out:
        manifest = out.pop("SHA256SUMS").decode().splitlines()
        expect = {}
        for line in manifest:
            match = re.fullmatch(r"([a-f0-9]{64})  (?:\./)?(.+)", line)
            if not match or match.group(2) in expect:
                raise ValueError("invalid checksum manifest")
            expect[match.group(2)] = match.group(1)
        if set(expect) != set(out) or any(sha(out[k]) != v for k, v in expect.items()):
            raise ValueError("complete archive checksum mismatch")
    return out


def time_value(value):
    for fmt in ("%Y/%m/%d (%a) %H:%M", "%I:%M %p on %d %B, %Y"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        obj = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return obj.replace(tzinfo=timezone.utc) if obj.tzinfo is None else obj
    except (ValueError, AttributeError):
        raise ValueError("unregistered observation time") from None


def rank(question, documents):
    terms = set(WORD.findall(question["question"].lower()))
    counts = [Counter(WORD.findall(d["content"].lower())) for d in documents]
    lengths = [sum(cnt.values()) for cnt in counts]
    size = len(documents)
    if not size or not terms:
        raise ValueError("empty source list or query")
    avg = sum(lengths) / size
    df = {term: sum(term in c for c in counts) for term in terms}
    scored = []
    for d, cnt, length in zip(documents, counts, lengths, strict=True):
        value = 0.0
        for term in terms:
            tf = cnt[term]
            if tf:
                idf = math.log1p((size - df[term] + 0.5) / (df[term] + 0.5))
                value += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * length / max(avg, 1)))
        scored.append((value, d["identity"]))
    lexical = [key for _, key in sorted(scored, key=lambda x: (-x[0], x[1]))]
    recent = [d["identity"] for d in sorted(documents,
              key=lambda d: (time_value(d["observed_at"]), d["identity"]), reverse=True)]
    ra = {key: i for i, key in enumerate(lexical, start=1)}
    rb = {key: i for i, key in enumerate(recent, start=1)}
    fusion = sorted(ra, key=lambda k: (-(1 / (60 + ra[k]) + 1 / (60 + rb[k])), k))
    return dict(lexical=lexical, recent=recent, fusion=fusion)




def check_roles(public_root, selection_root=None, evaluation_root=None):
    """A later target ZIP must not be visible inside an earlier role's input."""
    roots = [(Path(public_root), {ZIPS["public"][0], ZIPS["decisions"][0]})]
    if selection_root is not None:
        roots.append((Path(selection_root), {ZIPS["selection"][0]}))
    if evaluation_root is not None:
        roots.append((Path(evaluation_root), {ZIPS[k][0] for k in ("evaluation", "old_policy", "old_report")}))
    physical = []
    for root, allowed in roots:
        if root.is_symlink() or not root.is_dir():
            raise ValueError("non-symlink isolated role directory required")
        actual = {p.name for p in root.iterdir()}
        if actual != allowed or any((root / name).is_symlink() for name in actual):
            raise ValueError("wrong role input census or premature private target exposure")
        physical.append(root.resolve(strict=True))
    if len(physical) != len(set(physical)):
        raise ValueError("role input directories may not alias")

def load_public(root):
    z = read_zip(root, "public")
    pop_bytes, hist_bytes = z["population.json"], z["histories.jsonl"]
    manifest = strict_json(z["histories-manifest.json"])
    if (sha(pop_bytes) != POPULATION_SHA or sha(hist_bytes) != HISTORIES_SHA
            or manifest["source_commit"] != GENERATING_COMMIT
            or manifest["original_source_sha256"] != SOURCE_SHA
            or manifest["population_sha256"] != POPULATION_SHA
            or manifest["histories_sha256"] != HISTORIES_SHA
            or manifest["target_file_in_reader_inputs"] is not False):
        raise ValueError("public source or its no-target seal drift")
    pop = strict_json(pop_bytes)
    sources = [strict_json(x) for x in hist_bytes.splitlines() if x]
    documents = {d["identity"]: d for d in sources}
    if (len(sources) != 5882 or len(documents) != len(sources)
            or pop["generating_source_commit"] != GENERATING_COMMIT
            or pop["model_input_contains_answers"] is not False
            or {k: len(pop["splits"][k]) for k in SPLITS} != {"train":48,"selection":16,"evaluation":16}):
        raise ValueError("invalid published original-source population")
    qids = [q["question_id"] for split in SPLITS for q in pop["splits"][split]]
    if len(qids) != 80 or len(set(qids)) != 80:
        raise ValueError("duplicate or missing original question")
    fam = [{q["native_family"] for q in pop["splits"][split]} for split in SPLITS]
    if [len(x) for x in fam] != [6,2,2] or any(fam[i] & fam[j] for i in range(3) for j in range(i+1,3)):
        raise ValueError("source-family leakage")
    return pop, documents


def compute(public, docs):
    rows = []
    for split in SPLITS:
        for q in public["splits"][split]:
            if (len(q["source_ids"]) != len(set(q["source_ids"]))
                    or any(s not in docs or docs[s]["scope"] != q["scope"] for s in q["source_ids"])):
                raise ValueError("query source census drift")
            selected_docs = [docs[k] for k in q["source_ids"]]
            if any(time_value(d["observed_at"]) > time_value(q["observation_time"]) for d in selected_docs):
                raise ValueError("future source exposure")
            order = rank(q, selected_docs)
            for arm in ARMS:
                prefix, count = arm.rsplit("_k", 1)
                chosen = order[prefix][:int(count)]
                rows.append(dict(
                    question_id=q["question_id"], split=split,
                    family_proxy_digest=q["family_proxy_digest"],
                    source_census_sha256=q["source_census_sha256"],
                    arm=arm, selected=chosen,
                    selected_source_bytes=sum(len(docs[k]["content"].encode()) for k in chosen),
                ))
    if len(rows) != 720 or len({(r["question_id"],r["arm"]) for r in rows}) != 720:
        raise ValueError("nine-arm retrieval census incomplete")
    return rows


def verify_original_six(root, newer):
    old = read_zip(root, "decisions")
    journal = old["decisions.jsonl"]
    if sha(journal) != ORIGINAL_DECISIONS_SHA:
        raise ValueError("published six-arm journal digest changed")
    receipt = strict_json(old["receipt.json"])
    if (receipt["generating_commit"] != GENERATING_COMMIT
            or receipt["original_decisions_sha256"] != ORIGINAL_DECISIONS_SHA
            or receipt["planned_questions"] != 80 or receipt["planned_arms"] != 6
            or receipt["model_generations"] != 0 or receipt["labels_opened"] is not False):
        raise ValueError("published original source-only receipt invalid")
    recorded = [strict_json(x) for x in journal.splitlines()]
    subset = [r for r in newer if r["arm"] in OLD_ARMS]
    if recorded != subset:
        raise ValueError("independent nine-arm implementation failed 480 original frozen decisions")
    return len(recorded)


def scores(pop, rows, split, targets):
    qs = pop["splits"][split]
    if set(targets) != {q["question_id"] for q in qs}:
        raise ValueError("selection and evaluation target partitions mixed")
    lookup = {(r["question_id"], r["arm"]): r for r in rows}
    results = {}
    for arm in ARMS:
        count=covered=unknown=outside=bytes_used=0
        per_family = {}
        for q in qs:
            target = targets[q["question_id"]]
            if (not isinstance(target.get("support"),list)
                    or type(target.get("unanswerable")) is not bool
                    or not isinstance(target.get("unresolved_support"),list)):
                raise ValueError("invalid original annotation")
            if any(not isinstance(s, str) or not s for s in target["support"] + target["unresolved_support"]):
                raise ValueError("invalid supported source identity")
            row=lookup[(q["question_id"],arm)]
            bytes_used+=row["selected_source_bytes"]
            bucket=per_family.setdefault(q["family_proxy_digest"],dict(eligible=0,covered=0))
            outside_source=bool(set(target["support"]) - set(q["source_ids"]))
            outside+=outside_source
            eligible=bool(target["support"]) and not target["unanswerable"] and not target["unresolved_support"] and not outside_source
            if eligible:
                count+=1;bucket["eligible"]+=1
                if set(target["support"]).issubset(row["selected"]):
                    covered+=1;bucket["covered"]+=1
            else:
                unknown+=1
        results[arm]=dict(planned=len(qs),eligible=count,full_annotated_support_covered=covered,
                          unknown_or_unanswerable=unknown,annotated_support_outside_original_pool=outside,
                          selected_source_bytes=bytes_used,per_family=per_family,
                          missing_outcome_lower=covered/len(qs),
                          missing_outcome_upper=(covered+unknown)/len(qs))
    return results


def write_new(path, contents):
    if path.exists() or path.is_symlink():
        raise ValueError("cannot overwrite immutable experiment output")
    with path.open("xb") as f:
        f.write(contents)
        f.flush()
        import os
        os.fsync(f.fileno())


def retrieve(root, output):
    check_roles(root)
    public, docs=load_public(root)
    rows=compute(public,docs)
    reproduced=verify_original_six(root,rows)
    output.mkdir(parents=True,exist_ok=False)
    raw=b"".join(canonical(x)+b"\n" for x in rows)
    write_new(output/"decisions.jsonl",raw)
    receipt=dict(schema="hepta.memorycell.locomo-nine-arm-independent-replay.v1",
      source_commit=GENERATING_COMMIT,published_old_decisions_sha256=ORIGINAL_DECISIONS_SHA,
      recomputed_old_six_rows=reproduced,public_population_sha256=POPULATION_SHA,
      original_histories_sha256=HISTORIES_SHA,planned_questions=80,planned_arms=9,
      original_nine_arm_rows=len(rows),raw_journal_sha256=sha(raw),
      labels_opened=False,model_answers_generated=0,production_accepted=False)
    write_new(output/"receipt.json",canonical(receipt)+b"\n")
    return receipt


def checked_decisions(root, output):
    public,docs=load_public(root)
    raw=(output/"decisions.jsonl").read_bytes()
    receipt=strict_json((output/"receipt.json").read_bytes())
    if (receipt["raw_journal_sha256"]!=sha(raw) or receipt["labels_opened"] is not False
            or receipt["planned_arms"]!=9 or receipt["planned_questions"]!=80):
        raise ValueError("original label-blind journal modified")
    recomputed=compute(public,docs)
    if raw != b"".join(canonical(x)+b"\n" for x in recomputed):
        raise ValueError("unsealed or posthoc retrieval decision")
    verify_original_six(root,recomputed)
    return public,recomputed


def select(public_root, selection_root, output):
    check_roles(public_root, selection_root)
    public,rows=checked_decisions(public_root,output)
    targets=strict_json(read_zip(selection_root,"selection")["targets.json"])
    result=scores(public,rows,"selection",targets)
    winner=sorted(ARMS,key=lambda a:(-result[a]["full_annotated_support_covered"],
                                    result[a]["selected_source_bytes"],a))[0]
    policy=dict(schema="hepta.memorycell.locomo-nine-arm-independent-selection.v1",
                selected_arm=winner,selection_scores=result,
                journal_sha256=sha((output/"decisions.jsonl").read_bytes()),
                heldout_labels_opened=False,production_accepted=False)
    write_new(output/"policy.json",canonical(policy)+b"\n")
    return policy


def evaluate(public_root, selection_root, evaluation_root, output):
    check_roles(public_root, selection_root, evaluation_root)
    public,rows=checked_decisions(public_root,output)
    polraw=(output/"policy.json").read_bytes()
    policy=strict_json(polraw)
    if (policy["schema"]!="hepta.memorycell.locomo-nine-arm-independent-selection.v1"
            or policy["journal_sha256"]!=sha((output/"decisions.jsonl").read_bytes())
            or policy["heldout_labels_opened"] is not False):
        raise ValueError("policy must be sealed before heldout target access")
    select_targets=strict_json(read_zip(selection_root,"selection")["targets.json"])
    scores_select=scores(public,rows,"selection",select_targets)
    winner=sorted(ARMS,key=lambda a:(-scores_select[a]["full_annotated_support_covered"],
                                    scores_select[a]["selected_source_bytes"],a))[0]
    if winner!=policy["selected_arm"] or scores_select!=policy["selection_scores"]:
        raise ValueError("policy selection was modified")
    targets=strict_json(read_zip(evaluation_root,"evaluation")["targets.json"])
    result=scores(public,rows,"evaluation",targets)
    old_policy=strict_json(read_zip(evaluation_root,"old_policy")["selection-policy.json"])
    old_report=strict_json(read_zip(evaluation_root,"old_report")["report.json"])
    if old_policy["selection_arm"]!="lexical_k8":
        raise ValueError("prior calibrated six-arm policy drift")
    for a in OLD_ARMS:
        old_sel=old_policy["selection_scores"][a]
        old_ev=old_report["evaluation"][a]
        for key in ("eligible","full_annotated_support_covered","selected_source_bytes","planned","unknown_or_unanswerable"):
            if scores_select[a][key]!=old_sel[key] or result[a][key]!=old_ev[key]:
                raise ValueError("independent original six-arm scoring mismatch")
    report=dict(schema="hepta.memorycell.locomo-nine-arm-independent-evaluation.v1",
      source_commit=GENERATING_COMMIT,original_pinned_six_arm_decisions_sha256=ORIGINAL_DECISIONS_SHA,
      journal_sha256=sha((output/"decisions.jsonl").read_bytes()),
      frozen_policy_sha256=sha(polraw),
      tested_families=2,selection_families=2,
      original_published_task_count=80,evaluation_questions=16,
      selected_arm=winner,selection=scores_select,
      evaluation=result,original_six_arm_replay_agrees=True,
      independent_source_family_authentication=False,
      published_data_pretraining_contamination_unknown=True,
      models_generated=0,citation_entailment_precision=None,
      production_accepted=False)
    write_new(output/"report.json",canonical(report)+b"\n")
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest="command",required=True)
    for command in ("retrieve", "select", "evaluate"):
        q = sub.add_parser(command)
        q.add_argument("public_zips", type=Path)
        if command in ("select", "evaluate"):
            q.add_argument("selection_zip", type=Path)
        if command == "evaluate":
            q.add_argument("evaluation_zips", type=Path)
        q.add_argument("experiment_directory", type=Path)
    a=p.parse_args()
    if a.command=="retrieve":
        result=retrieve(a.public_zips,a.experiment_directory)
    elif a.command=="select":
        result=select(a.public_zips,a.selection_zip,a.experiment_directory)
    else:
        result=evaluate(a.public_zips,a.selection_zip,a.evaluation_zips,a.experiment_directory)
    print(json.dumps({"stage":a.command,"result":result},ensure_ascii=False)[:1400])


if __name__=="__main__":
    main()
