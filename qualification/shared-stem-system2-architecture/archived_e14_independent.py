#!/usr/bin/env python3
"""Independent four-archived-ZIP E14 retrospective CPU/quality negative result.

Reopen the ORIGINAL, successful GitHub source-head / synthetic-merge blind and
independent original-human score artifacts. Never select a model/NDU controller.
No new pretrained forward, no complete-service or genuine prospective effect.
"""
from __future__ import annotations
from collections import defaultdict
from fractions import Fraction
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile
import argparse
import json
import math

ARCHIVES = {
 'blind_source': 'e8cc5bfad419de8976c467df676bc20f91f6a4d37af376b55bfdb58a8ab43a81',
 'blind_merge': 'e143cdc891bfefb93df6b25fe12d5bdb73084531b419a0a4e9b8dde2531f5146',
 'score_source': 'd7ee5bc9d8f4a3f2323dc83dc6e94fee31db2966a610f3af4ede148562506908',
 'score_merge': 'efd3525b6c412b1681333b1f1185a6879973ae93340b12f786139eb45a3ff0f4',
}
MEMBERS = {'blind_source':'original-human-blind-policies.json',
           'blind_merge':'original-human-blind-policies.json',
           'score_source':'independent-original-human-e14-score.json',
           'score_merge':'independent-original-human-e14-score.json'}
OBS = '7e4a0dc4ff48688b1ace0640a3290ee90011487843384a30565b65d3d240e7a5'
MODEL = '1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17'
VAL = '5eb64893afc5af7828b2f3b41d6a4574eb7a82cbb17c86c75842f5f95f679ada'
ORIGINAL_SCORE = '3a3fd807585dd09ef4f089391dc68db4b008e87b69060f68f384a07daaa9f8e4'
POLICIES = ('conditioned','mean_pool_query_fused','no_evidence','no_query',
            'fixed_confidence','cheap_one_map','e12_full_tree')
FROZEN = POLICIES[:4]

class AuditDenied(ValueError):
    """Unqualified source / archive / scorer / performance premise."""


def require(ok, detail):
    if not ok:
        raise AuditDenied(detail)


def object_pairs(pairs):
    out={}
    for key,value in pairs:
        require(key not in out,'duplicate JSON member')
        out[key]=value
    return out


def load(path: Path, role: str):
    require(role in ARCHIVES and path.is_file() and not path.is_symlink() and
            0 < path.stat().st_size <= 100_000, 'incorrect role or unsafe archive')
    raw=path.read_bytes()
    require(sha256(raw).hexdigest()==ARCHIVES[role], 'archived original ZIP SHA mismatch')
    with ZipFile(path) as z:
        infos=z.infolist()
        require(1 <= len(infos) <= 30 and len({i.filename for i in infos})==len(infos)
                and MEMBERS[role] in {i.filename for i in infos}
                and all(not i.is_dir() and not i.filename.startswith('/')
                        and '..' not in i.filename.split('/') and
                        i.file_size <= 220_000 and i.compress_size <= 100_000 and
                        ((i.external_attr>>16)&0o170000) != 0o120000 for i in infos),
                'unsafe archive inventory')
        data=z.read(MEMBERS[role])
    require(0 < len(data) <= 220_000, 'unbounded original evidence bytes')
    return json.loads(data,object_pairs_hook=object_pairs,
        parse_constant=lambda v: (_ for _ in ()).throw(AuditDenied('nonfinite JSON '+v)))


def clean_row(r):
    c=json.loads(json.dumps(r,sort_keys=True,allow_nan=False))
    c.pop('cheap_cpu_ns')
    c['cert'].pop('cpu_ns')
    c['cert'].pop('wall_ns')
    return c


def inspect_blind(obs):
    require(type(obs) is dict and obs.get('schema') ==
            'hepta.e14.original-human-multirc-labelblind-fbsde.v1' and
            obs.get('archive_sha256')==MODEL and obs.get('prelabel_observation_id')==OBS and
            obs.get('original_labels_accessed') is False and
            obs.get('human_labels_present_in_prediction_rows') is False and
            obs.get('production_accepted') is False and
            obs.get('new_pretrained_forward_count') == 0 and
            obs.get('actual_live_routing') is False and
            obs.get('exploratory_cutoff') == '9/100' and
            obs.get('policies') == list(POLICIES), 'unqualified original E14 source')
    rows=obs.get('rows')
    require(type(rows) is list and len(rows)==33, 'original 33 answers missing')
    groups=defaultdict(list)
    task_ids=set()
    cheap=0;full=0
    for row in rows:
        require(type(row) is dict and set(row)=={
            'task_id','source_group','question_slot','candidate_id','original_v1_candidate',
            'policy_arms','probs','cheap_cpu_ns','cheap_root','law','cert'},
            'changed original one-row source schema')
        require(type(row['task_id']) is str and len(row['task_id'])==32 and
                type(row['source_group']) is str and len(row['source_group'])==32 and
                type(row['question_slot']) is int and row['question_slot'] in (0,1) and
                type(row['candidate_id']) is int and row['candidate_id']>=0 and
                type(row['original_v1_candidate']) is bool and
                row['task_id'] not in task_ids, 'wrong original question/answer IDs')
        task_ids.add(row['task_id'])
        probs=row['probs']
        require(type(probs) is dict and set(probs)==set(FROZEN) and
                all(type(p) in (float,int) and math.isfinite(p) and 0<p<1 for p in probs.values()),
                'invalid actual pretrained Reader outputs')
        choices=row['policy_arms']
        require(type(choices) is dict and set(choices)==set(POLICIES) and
                all(choice in FROZEN for choice in choices.values()) and
                all(choices[arm]==arm for arm in FROZEN),
                'invalid original source-bound routing')
        cert=row['cert']
        require(type(cert) is dict and cert.get('authority')=='DENY_ALL' and
                cert.get('production_accepted') is False and
                cert.get('qualified_discrete_bound') is True and
                cert.get('real_pretrained_forwards')==0 and
                type(cert.get('cpu_ns')) is int and cert['cpu_ns']>0 and
                type(row.get('cheap_cpu_ns')) is int and row['cheap_cpu_ns']>0 and
                cert.get('requested_tolerance')=='1/10000',
                'unqualified original exact FBSDE audit/CPU')
        for field in ('mapped_residual','fixed_point_error_bound'):
            x=Fraction(cert[field]);require(0<=x<=Fraction('1/10000'),
                                          'original rational residual beyond bound')
        groups[row['source_group'],row['question_slot']].append(row)
        cheap+=row['cheap_cpu_ns'];full+=cert['cpu_ns']
    require(len(groups)==8 and len({g for g,_ in groups})==4 and
            all(2<=len(group)<=8 and sum(r['original_v1_candidate'] for r in group)==1
                for group in groups.values()), 'wrong original question/group denominator')
    return {'rows':rows,'groups':groups,'cheap_ns':cheap,'full_ns':full}


def check_human_score(report,blinded):
    require(type(report) is dict and report.get('schema') ==
            'hepta.e14.independent-original-multirc-task-control.v1' and
            report.get('authority')=='DENY_ALL' and report.get('production_accepted') is False and
            report.get('original_archive_sha256')==MODEL and
            report.get('human_validation_sha256')==VAL and
            report.get('original_owner_score_sha256')==ORIGINAL_SCORE and
            report.get('original_human_annotation_candidate_count')==33 and
            report.get('passages')==4 and report.get('questions')==8 and
            report.get('all_questions_mixed_original_labels') is True and
            report.get('new_pretrained_model_calls')==0 and
            report.get('complete_online_cost_comparison') is False and
            report.get('incremental_e12_real_task_superiority_established') is False and
            report.get('online_routing_executed') is False and
            report.get('not_future_time_or_multi_family') is True,
            'unqualified independent original human score')
    arms=report.get('evaluation_arms')
    require(type(arms) is dict and set(arms)==set(POLICIES),'missing original scored arm')
    for name,score in arms.items():
        require(type(score) is dict and type(score.get('correct')) is int and
                score.get('total')==33 and 0<=score['correct']<=33 and
                type(score.get('brier')) in (float,int) and
                0<=score['brier']<=2 and
                math.isclose(score.get('accuracy',-1),score['correct']/33,
                             rel_tol=0,abs_tol=1e-15), 'wrong original human metric')
    cpu=report.get('self_observed_local_python_numerical_cpu_ns')
    require(type(cpu) is dict and cpu=={'cheap':blinded['cheap_ns'],
                                         'full_e12':blinded['full_ns']},
            'numerical costs not reconciled to actual archived per-case traces')
    difference=sum(row['policy_arms']['cheap_one_map']!=
                   row['policy_arms']['e12_full_tree'] for row in blinded['rows'])
    require(report.get('policy_switch_differences_cheap_vs_e12')==difference,
            'changed original E14 routing decisions')
    return difference


def independent_review(paths):
    records={role:load(Path(paths[role]),role) for role in ARCHIVES}
    a,b=(inspect_blind(records[name]) for name in ('blind_source','blind_merge'))
    require([clean_row(r) for r in a['rows']]==[clean_row(r) for r in b['rows']],
            'original source-head/merge numerical policy/route identity drift')
    c,d=(records[name] for name in ('score_source','score_merge'))
    for field in c:
        if field=='self_observed_local_python_numerical_cpu_ns':continue
        require(c[field]==d.get(field), 'original independent source/merge quality drift')
    require(check_human_score(c,a)==check_human_score(d,b)==6,
            'wrong original switched policy set')
    cheap=c['evaluation_arms']['cheap_one_map']
    full=c['evaluation_arms']['e12_full_tree']
    require(cheap['correct']==full['correct']==15 and
            full['brier']>cheap['brier'] and
            a['full_ns']>a['cheap_ns'] and b['full_ns']>b['cheap_ns'],
            'wrong observed original-human E14 negative comparison')
    windows=[]
    for tag,x in [('source_head',a),('synthetic_merge',b)]:
        group_cost=[]
        for group in sorted({g for g,_ in x['groups']}):
            rows=[r for (g,_), rs in x['groups'].items() if g==group for r in rs]
            cheap_ns=sum(r['cheap_cpu_ns'] for r in rows)
            full_ns=sum(r['cert']['cpu_ns'] for r in rows)
            require(cheap_ns>0 and full_ns>cheap_ns,'original source-group numeric cost wrong')
            group_cost.append({'source_group':group,'answer_candidates':len(rows),
                               'cheap_numeric_cpu_ns':cheap_ns,
                               'full_e12_numeric_cpu_ns':full_ns})
        windows.append({'profile':tag,'candidate_count':len(x['rows']),
                        'cheap_numeric_cpu_ns':x['cheap_ns'],
                        'full_e12_numeric_cpu_ns':x['full_ns'],
                        'observed_full_to_cheap_numeric_cpu_ratio':round(x['full_ns']/x['cheap_ns'],9),
                        'four_correlated_source_groups':group_cost})
    return {'schema':'hepta.p3.e14-original-archived-four-zip-independent-replay.v1',
            'authority_posture':'DENY_ALL','production_accepted':False,
            'original_source_head_and_merge_seals_verified':True,
            'original_model_archive_sha256':MODEL,
            'original_human_score_archive_sha256':ORIGINAL_SCORE,
            'actual_human_answer_candidates':33,
            'independent_human_passage_groups':4,'original_questions':8,
            'decisions_differ_between_two_routing_policies':6,
            'cheap_original_human_correct':cheap['correct'],
            'full_original_human_correct':full['correct'],
            'cheap_original_human_brier':cheap['brier'],
            'full_original_human_brier':full['brier'],
            'numeric_substage_descriptively_dominated_on_this_panel':True,
            'two_original_source_profiles':windows,
            'actual_new_pretrained_model_forwards':0,
            'full_serving_latency_or_energy_matched':False,
            'prospective_original_human_tasks':False,
            'online_NDU_controller_activated':False,
            'general_FBSDE_inferiority_proven':False,
            'statistical_superiority_certified':False,
            'model_or_NDU_promotion_permitted':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for role in ARCHIVES:parser.add_argument('--'+role.replace('_','-'),required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    require(not args.output.exists() and not args.output.is_symlink(),
            'original immutable report create-only destination required')
    result=independent_review({name:getattr(args,name) for name in ARCHIVES})
    with args.output.open('xb') as out:
        out.write((json.dumps(result,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode())
    print('ORIGINAL_E14_FOUR_ARCHIVE_NEGATIVE_REPLAY / NO_GO / DENY_ALL')


if __name__=='__main__':main()
