"""V14 independent postseal scorer, stdlib-only; NEVER import model/proposer.

Refuses incomplete source groups, wrong hidden-label ZIP, changed predictions,
forged paths, or a synthetic-grammar label conflicting with the source owner.
Group-level paired bootstrap treats 120 groups, not 480 candidate predictions,
as the independent held sampling unit. Research DENY_ALL.
"""
from collections import defaultdict
from hashlib import sha256
import argparse
import json
import math
from pathlib import Path
import random
import re
import time
from zipfile import ZipFile

PUBLIC_ZIP_SHA256='efee1e07fdb26cb9f3222a86244ad8a41062b0c647a3be762d76c688826995af'
HELD_ZIP_SHA256='b98fa92913d07e34a67c0e45c3e021308cd9a56ce5c64c02c31a243a35be28b4'
PUBLIC_FILE_SHA256='1b027fd2708068da25674415789906a575a00383abe5712255a432e8679e913c'
SOURCE_SEAL_SHA256='4de11a06a4d481696fe6efc3a6a1f8085806aeffc7f20a3d14fb07d4dc30d608'
HELD_MEMBER_SHA256='31fc4230ce888e325c8b956af0f6bab5b17d8825d3a5e9b9f26a46e65974ea73'
ARMS=('train_idf','unlabeled_transductive_idf','unlabeled_transductive_reverse','first_candidate')
VARIANTS=('original','fact_permutation','meaning_preserving_paraphrase')
TYPES=('object','person','box','shelf','room','building','district')
FACT_TEMPLATES=(
    re.compile(r'The ([a-z]+) belongs to ([A-Z][a-z]+)\.'),
    re.compile(r'([A-Z][a-z]+) stores all their possessions in the ([a-z]+) box\.'),
    re.compile(r'The ([a-z]+) box is on the ([a-z]+) shelf\.'),
    re.compile(r'The ([a-z]+) shelf is in the ([a-z]+) room\.'),
    re.compile(r'The ([a-z]+) room is in the ([a-z]+) building\.'),
    re.compile(r'The ([a-z]+) building is in the ([a-z]+) district\.'),
)
QUESTION=re.compile(r'Where is the ([a-z]+) at the (box|shelf|room|building|district) level\?')
CANDIDATE=re.compile(r'The ([a-z]+) (box|shelf|room|building|district)\.')
TOKEN=re.compile(r'[a-z]+')


def digest(obj):
    return sha256(json.dumps(obj,sort_keys=True,separators=(',', ':'),allow_nan=False).encode()).hexdigest()


def zip_member(path,expected,name):
    original=Path(path)
    if original.is_dir():
        blob=(original/name).read_bytes()
    else:
        if sha256(original.read_bytes()).hexdigest()!=expected:
            raise ValueError('original registered zip file bytes mismatch')
        with ZipFile(original) as z:
            if z.testzip() is not None or name not in z.namelist():
                raise ValueError('original ZIP CRC/member invalid')
            blob=z.read(name)
    permitted={'public.json':PUBLIC_FILE_SHA256,
               'source-seal.json':SOURCE_SEAL_SHA256,
               'held-labels-restricted.json':HELD_MEMBER_SHA256}
    if name not in permitted or sha256(blob).hexdigest()!=permitted[name]:
        raise ValueError('original member source bytes invalid')
    return json.loads(blob)


def independently_derive_truth(row):
    """Formal source truth independent of original source-owner labels and ML path."""
    if type(row) is not dict or set(row)!={'case_id','source_group','facts','question','candidate'}:
        raise ValueError('only public original truth-bearing facts allowed')
    target=QUESTION.fullmatch(row['question'])
    proposed=CANDIDATE.fullmatch(row['candidate'])
    if not target or not proposed or target.group(2)!=proposed.group(2):
        raise ValueError('incomplete declared synthetic grammar question')
    stop=TYPES.index(target.group(2))
    graph={}
    for sentence in row['facts']:
        matched=[(i,m) for i,pat in enumerate(FACT_TEMPLATES) if (m:=pat.fullmatch(sentence))]
        if len(matched)!=1:
            raise ValueError('source fact not in independent registered grammar')
        level,m=matched[0]
        src,dst=m.groups()
        key=(level,src.lower())
        if key in graph:
            raise ValueError('ambiguous independent source binding')
        graph[key]=dst.lower()
    current=target.group(1)
    for level in range(stop):
        if (level,current) not in graph:
            raise ValueError('missing complete 2–6-hop public source truth')
        current=graph[(level,current)]
    return int(current==proposed.group(1))


def percentile(v,q):
    if not v:raise ValueError('nonempty group bootstrap required')
    return sorted(v)[int((len(v)-1)*q)]


def paired_group_ci(groups, values_a, values_b=None, *, resamples=1600):
    """Bootstrap GROUP means, keeping all worlds/candidates together."""
    if not groups or set(groups)!=set(values_a) or values_b is not None and set(groups)!=set(values_b):
        raise ValueError('complete paired independently grouped observations required')
    rng=random.Random(1714)
    n=len(groups)
    out=[]
    for _ in range(resamples):
        selected=[groups[rng.randrange(n)] for _ in range(n)]
        mu=sum(values_a[g]-(values_b[g] if values_b is not None else 0) for g in selected)/n
        out.append(mu)
    return [percentile(out,.025),percentile(out,.975)]


def review(public_zip,held_zip,plan_path,seal_path,output):
    started=time.process_time_ns()
    original=zip_member(public_zip,PUBLIC_ZIP_SHA256,'public.json')
    owner=zip_member(public_zip,PUBLIC_ZIP_SHA256,'source-seal.json')
    held=zip_member(held_zip,HELD_ZIP_SHA256,'held-labels-restricted.json')
    plan=json.loads(Path(plan_path).read_text())
    seal=json.loads(Path(seal_path).read_text())
    if (plan.get('schema')!='hepta.v14.all-evidence-slot-protocol.v1'
            or plan.get('protocol_sha256')!=digest({k:v for k,v in plan.items() if k!='protocol_sha256'})
            or plan.get('source_sha256')!=digest(original)
            or plan.get('source_owner_sha256')!=digest(owner)
            or seal.get('schema')!='hepta.v14.no-oracle-raw-public-predictions.v1'
            or seal.get('source_sha256')!=digest(original)
            or seal.get('source_owner_sha256')!=digest(owner)
            or seal.get('preregistered_plan_sha256')!=plan['protocol_sha256']
            or seal.get('prediction_sha256')!=digest(seal.get('predictions'))
            or seal.get('predicted_variants')!=list(VARIANTS)
            or seal.get('predicted_arms')!=list(ARMS)
            or seal.get('original_held_answer_labels_loaded') is not False
            or seal.get('pretrained_forward_count')!=0
            or seal.get('sgd_optimizer_updates')!=0
            or seal.get('authority')!='DENY_ALL'
            or seal.get('production_accepted') is not False
            or seal.get('model_selection_permitted') is not False
            or owner.get('held_label_sha256')!=digest(held)):
        raise ValueError('immutable preregistered plan, original secret, predictions or research posture changed')
    ids={c['case_id'] for c in original if not c['case_id'].startswith('train/')}
    if len(ids)!=960 or set(held)!=ids or any(type(v) is not int or v not in (0,1) for v in held.values()):
        raise ValueError('exact complete held task universe required')
    raw_by_id={row['case_id']:row for row in original}
    groups=defaultdict(list)
    for cid in sorted(ids):
        row=raw_by_id[cid]
        role,depth,grp,world,answer=cid.split('/')
        if (role not in ('held_known','held_novel') or not 2<=int(depth)<=6
                or not world.startswith('world-') or not answer.startswith('candidate-')
                or independently_derive_truth(row)!=held[cid]):
            raise ValueError('independent semantic reference disagrees with sealed source truth')
        groups[(role,int(depth),row['source_group'])].append(cid)
    if len(groups)!=240 or any(len(v)!=4 for v in groups.values()):
        raise ValueError('240 complete four-row held source groups required')
    for idx in groups.values():
        if sorted(held[c] for c in idx)!=[0,0,1,1]:
            raise ValueError('counterfactual both-world gold balance missing')
    scores=[]
    per_depth=[]
    subgroup_data=defaultdict(dict)
    all_predictions=seal['predictions']
    all_traces=seal['discovered_slots_and_paths']
    for variant in VARIANTS:
        if set(all_predictions.get(variant,{}))!=set(ARMS) or set(all_traces.get(variant,{}))!=set(ARMS):
            raise ValueError('complete fixed variant and arm universe required')
        for arm in ARMS:
            predictions=all_predictions[variant][arm]
            traces=all_traces[variant][arm]
            if set(predictions)!=ids or set(traces)-ids or (arm=='first_candidate' and traces):
                raise ValueError('complete original case IDs and no forged oracle traces required')
            for cid,p in predictions.items():
                if p is not None and (type(p) is not int or p not in (0,1)):
                    raise ValueError('only abstention or 0/1 predictions allowed')
            if arm!='first_candidate' and set(traces)!=ids:
                raise ValueError('complete all-facts provenance paths required')
            # Basic independent path-integrity check: each witnessed hop must be an
            # observed extracted directed slot pair of some admitted public fact.
            for cid,t in traces.items():
                row=raw_by_id[cid]
                if (type(t) is not dict or set(t)!={'path','dist','start','candidate','fact_slots'}
                        or type(t['path']) is not list or type(t['dist']) is not int
                        or len(t['fact_slots'])!=len(row['facts'])):
                    raise ValueError('complete bounded graph trace required')
                if not (t['dist']==99 and not t['path'] or t['dist']==len(t['path'])-1<=6):
                    raise ValueError('trace hop geometry inconsistent')
                pairs=set()
                for k,a,b in t['fact_slots']:
                    if type(k) is not int or not 0<=k<len(row['facts']) or a==b:
                        raise ValueError('trace mentions invalid fact index or same endpoint')
                    pairs.add((a,b))
                if any((a,b) not in pairs for a,b in zip(t['path'],t['path'][1:])):
                    raise ValueError('claimed transition absent from discovered source facts')
            for role in ('held_known','held_novel'):
                cohort=[key for key in groups if key[0]==role]
                group_values={}
                count=correct=abstained=paired=paired_correct=group_exact=0
                for group_key in cohort:
                    cids=groups[group_key]
                    hits=[int(predictions[cid] is not None and predictions[cid]==held[cid]) for cid in cids]
                    right=sum(hits)
                    count+=len(cids);correct+=right
                    abstained+=sum(predictions[cid] is None for cid in cids)
                    group_exact+=int(right==4)
                    variants=defaultdict(list)
                    for cid in cids:
                        variants[cid.split('/')[-1]].append(cid)
                    if len(variants)!=2 or any(len(v)!=2 for v in variants.values()):
                        raise ValueError('two repeated candidate worlds required')
                    paired+=2
                    paired_correct+=sum(int(all(predictions[c] is not None and predictions[c]==held[c] for c in v)) for v in variants.values())
                    group_values[group_key]=right/4
                if (len(cohort)!=120 or count!=480 or paired!=240):
                    raise ValueError('complete source-group unit counts required')
                record=dict(variant=variant,arm=arm,role=role,candidates=count,
                    candidate_correct=correct,candidate_accuracy=correct/count,
                    abstained=abstained,groups=len(cohort),all_four_groups=group_exact,
                    paired_candidates=paired,both_worlds_correct=paired_correct,
                    paired_accuracy=paired_correct/paired,
                    source_group_accuracy_ci95=paired_group_ci(cohort,group_values))
                subgroup_data[variant,arm,role]=group_values
                scores.append(record)
                for depth in range(2,7):
                    selected=[(g,groups[g]) for g in cohort if g[1]==depth]
                    if len(selected)!=24:
                        raise ValueError('24 independent source groups per held depth required')
                    cc=[cid for _,ids4 in selected for cid in ids4]
                    dd=sum(predictions[cid] is not None and predictions[cid]==held[cid] for cid in cc)
                    no=sum(predictions[cid] is None for cid in cc)
                    per_depth.append(dict(variant=variant,arm=arm,role=role,depth=depth,
                        source_groups=len(selected),candidate_correct=dd,candidates=len(cc),
                        abstained=no,accuracy_with_abstention_failure=dd/len(cc)))
    comparisons=[]
    for role in ('held_known','held_novel'):
        keys=sorted(k for k in groups if k[0]==role)
        for a,b,comparison in ((('original','unlabeled_transductive_idf'),('original','train_idf'),'unlabeled_transductive_minus_inductive'),
                               (('original','unlabeled_transductive_idf'),('meaning_preserving_paraphrase','unlabeled_transductive_idf'),'original_minus_paraphrase'),
                               (('original','unlabeled_transductive_idf'),('original','unlabeled_transductive_reverse'),'forward_minus_reversed')):
            v1,v2=subgroup_data[a[0],a[1],role],subgroup_data[b[0],b[1],role]
            comparisons.append(dict(role=role,comparison=comparison,
                mean_group_accuracy_difference=sum(v1[g]-v2[g] for g in keys)/len(keys),
                group_bootstrap_diff_ci95=paired_group_ci(keys,v1,v2)))
    report=dict(schema='hepta.v14.original-held-postseal-review.v1',
       original_source_sha256=digest(original),source_owner_secret_sha256=digest(held),
       preregistered_plan_sha256=plan['protocol_sha256'],prediction_sha256=seal['prediction_sha256'],
       original_distinct_held_source_groups=240, source_groups_per_role=120,
       per_cohort_arm_results=scores,per_depth_results=per_depth,
       paired_source_group_comparisons=comparisons,
       original_v7_joint_gate_passed=False,
       exploratory_nonpreregistered_natural_capability=False,
       transductive_cannot_establish_future_generalization=True,
       scripted_paraphrases_not_human_natural_language=True,
       held_label_used_only_in_postseal_review=True,
       pretrained_forward_count=0,real_model_weights_loaded=False,
       no_FBSDE_NDU_causal_gain=True,
       reviewed_cpu_ns=time.process_time_ns()-started,
       model_selected=False,production_accepted=False,authority='DENY_ALL')
    report['results_sha256']=digest(scores)
    with Path(output).open('x') as f:
        json.dump(report,f,sort_keys=True,indent=2,allow_nan=False)
        f.write('\n')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for s in ('public','held','plan','seal','output'):
        p.add_argument('--'+s,required=True)
    a=p.parse_args()
    r=review(a.public,a.held,a.plan,a.seal,a.output)
    print(json.dumps(dict(source_groups=r['original_distinct_held_source_groups'],result_hash=r['results_sha256'],rows=len(r['per_cohort_arm_results']))))

if __name__=='__main__':main()
