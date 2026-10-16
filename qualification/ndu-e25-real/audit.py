#!/usr/bin/env python3
"""Read-only independent recount of *original* E25 human/source/model artifacts.

This does not train or execute NDU; it refuses NDU-specific superiority claims.
All source inputs are immutable SHA-pinned GitHub Actions originals, not fixture JSON.
"""
import argparse
import hashlib
import json
import math
import pathlib
import zipfile
from collections import defaultdict

REPO = 'TrillionniumFoundation/hepta-private-ci'
SOURCE_RUN = 38727583089
SOURCE_HEAD = '1ab2615004fc524ca18d47aaa97f6dc59356d533'
SOURCES = {
    'public': (11991113170, 'b8ea439e3d3300d4c09e5fe1c568bcaa6403d0bda2a86dd42fd28c05e9c761b1'),
    'owner': (11991387730, '89fce74a76a5abe4a43ea9c28ea120b9b81b76cb63e3ade198a80077f8035b35'),
    'model': (12010699818, 'd1ff527ddb9ee32f3e258c9cdb206449f242ac5f9b7b21e6d4f163b6c88706d1'),
    'score': (12018967923, '469bb6ef89c70f9329564e794cad2dff4b4fe603e5255971078aaf9500eb6eb8'),
}
MEMBERS = {
    'public': ('blind_slate.json', 'source.json'),
    'owner': ('human-labels.json',),
    'model': ('sealed-new-six-blind-model-predictions.json',),
    'score': ('fixed-pretrained-new-six-original-human-question-score.json',),
}
# Member locks also cover CI artifact downloads that automatically extract ZIPs.
MEMBER_HASHES = {
    ('public', 'blind_slate.json'): 'f7b6e49ff0648e4136abda167439ed2f3d6eac44606413bd66871d971788b3d4',
    ('public', 'source.json'): '332fadb8d3f725051bba4249a6e98d4061275f22ddb79cea9c56b4d235f8c75b',
    ('model', 'sealed-new-six-blind-model-predictions.json'): 'd08baac0d440394943e4bf9c20ddb4f564aeedb736a6acfc82bb8e797530b0a3',
    ('owner', 'human-labels.json'): '0358715390c8b036405134fd2b5af1859e3ddeccdb1eabc51098009485ab1122',
    ('score', 'fixed-pretrained-new-six-original-human-question-score.json'): 'ec35b0e7c349798d365017efa11e91a57c183061edb647807b44924e3e817158',
}
ROOT_METHODS = frozenset(('no_evidence', 'mean_pool_query_fused', 'e16_scaled_brier_5',
                          'question_softworst_tau_001', 'conditioned', 'no_query'))


def digest(b):
    return hashlib.sha256(b).hexdigest()


def parse_json(raw):
    def no_duplicates(entries):
        out = {}
        for k, v in entries:
            if k in out:
                raise ValueError('duplicate JSON member ' + k)
            out[k] = v
        return out
    def invalid(v):
        raise ValueError('nonfinite numeric JSON ' + v)
    return json.loads(raw, object_pairs_hook=no_duplicates, parse_constant=invalid)


def zip_member(p, kind, name):
    if kind not in SOURCES or name not in MEMBERS[kind]:
        raise ValueError('unknown source/ZIP member')
    p = pathlib.Path(p)
    if p.stat().st_size > 150_000 or p.stat().st_size < 100:
        raise ValueError('invalid original artifact size')
    if digest(p.read_bytes()) != SOURCES[kind][1]:
        raise ValueError('original source zip digest mismatch: ' + kind)
    with zipfile.ZipFile(p) as z:
        info = z.getinfo(name)
        if info.file_size > 220_000 or info.compress_size > 150_000:
            raise ValueError('unsafe source archive member')
        raw = z.read(name)
    if (kind, name) in MEMBER_HASHES and digest(raw) != MEMBER_HASHES[kind, name]:
        raise ValueError('source member digest mismatch')
    return parse_json(raw)


def read_automatic_unzip(folder, kind, name):
    """Same immutable member locks after Actions download-artifact extracts ZIPs."""
    p = pathlib.Path(folder) / kind / name
    if p.is_symlink() or not p.is_file() or p.stat().st_size > 220_000:
        raise ValueError('missing, redirected or oversized Actions member')
    raw = p.read_bytes()
    # Each consumed member is SHA locked via the run's original source-head ZIP.
    expected = MEMBER_HASHES.get((kind, name))
    if expected is None:
        raise ValueError('missing exact trusted member digest')
    if digest(raw) != expected:
        raise ValueError('original artifact extracted member changed')
    return parse_json(raw)


def validate_scalar(x):
    if type(x) not in (float, int) or not math.isfinite(x) or x < 0.0 or x > 1.0:
        raise ValueError('invalid original probability')
    return float(x)


def recount(public, src, owner, model, score):
    # Scope and provenance must be negative/positive for exactly the registered claim.
    if (src['authority'] != 'DENY_ALL' or src['production_accepted'] is not False
        or src.get('source_issuer_independently_authenticated') is not False
        or owner.get('external_observer_authenticated') is not False
        or model.get('source_issuer_independently_authenticated') is not False):
        raise ValueError('wrong source authority or falsified external signature')
    if (src['original_source_head'] != '6f8cf0930a51bce97fc22a09e3c5923a082abae9'
        or src['exhausts_remaining_eligible_passages'] is not True
        or src['full_unused_source_census_before_model'] is not True
        or src['same_original_data_family'] is not True
        or src['future_time_or_independent_family'] is not False):
        raise ValueError('unsupported new-source identity claim')
    old, fresh = src['old_source_groups'], src['new_source_groups']
    if (len(old),len(fresh),len(set(old)),len(set(fresh))) != (4,6,4,6) or set(old)&set(fresh):
        raise ValueError('original/new group overlap or invalid census')
    if (src['new_question_count'],src['new_candidate_count']) != (12,51):
        raise ValueError('changed genuine slate census')
    if public['source_panel_id'] != model['source_panel_id'] or public['slate_id'] != model['slate_id']:
        raise ValueError('source/blind seal mismatch')
    if owner['slate_id'] != model['slate_id'] or owner['original_panel_id'] != model['source_panel_id']:
        raise ValueError('original owner/model identity mismatch')
    if (model['authority'],score['authority']) != ('DENY_ALL','DENY_ALL'):
        raise ValueError('wrong model/scoring authority')
    if (model['human_validation_labels_read_before_seal'] is not False
        or model['production_accepted'] is not False
        or score['production_accepted'] is not False
        or score['human_truth_read_only_after_seal'] is not True):
        raise ValueError('invalid held-label custody or authority')
    if (model['new_validation_passages'],model['new_validation_questions'],model['new_validation_candidates']) != (6,12,51):
        raise ValueError('incomplete actual original reader work')
    if (model['historical_reader_weights_reproduced'] is not True or model['new_original_candidate_reader_forward_calls'] <= 0
        or model['eligible_unused_group_set_sha256'] != src['eligible_unused_group_set_sha256']):
        raise ValueError('original Reader execution or passage census unverified')
    if score['blind_sha256'] != MEMBER_HASHES[('model','sealed-new-six-blind-model-predictions.json')]:
        raise ValueError('independent scorer reviewed different blind bytes')
    if not(score['independent_reference_recomputed'] and score['fourfold_ensemble_not_five_scalar_single_head']):
        raise ValueError('missing original reviewer/fold lineage')
    if score['new_holdout_passages'] != 6 or score['original_passages_in_new_holdout'] != 0:
        raise ValueError('false unseen-original-passage claim')
    if not all(score.get(k) is False for k in ('statistical_superiority_established','novel_source_family','prospective_time_window')):
        raise ValueError('false prospective or statistical authority')

    # Verify complete genuine original source/answer inventory rather than treating
    # any convenient prediction subset as a complete task.
    groups = {}
    original = {}
    ordered = []
    for row in public['rows']:
        g=row['source_group']
        if g not in fresh or g in groups:
            raise ValueError('source group duplicate, missing or extra')
        groups[g] = []
        if len(row['questions']) != 2:
            raise ValueError('incomplete original two-question passage')
        for q in row['questions']:
            key = (g,q['question_slot'])
            if key in original:
                raise ValueError('duplicate original question')
            ids=[]
            for c in q['candidates']:
                task = c['task_id'];cid=c['candidate_id']
                if type(cid) is not int or type(task) is not str or any(x['task_id']==task for x in ordered):
                    raise ValueError('invalid/duplicated original candidate identity')
                if not isinstance(c['answer'],str) or not c['answer']:
                    raise ValueError('unreadable native alternative')
                ids.append(task)
                ordered.append({'task_id':task,'candidate_id':cid,'source_group':g,'question_slot':q['question_slot']})
            if not 2 <= len(ids) <= 8:
                raise ValueError('invalid complete native answer slate')
            original[key] = ids
            groups[g].append(key)
    if set(groups) != set(fresh) or len(ordered)!=51 or len(original)!=12:
        raise ValueError('original source candidate/question census differs')
    names = set(owner['labels'])
    if names != {r['task_id'] for r in ordered}:
        raise ValueError('gold owner original-label census incomplete or extra')
    if any(type(v) is not int or v not in (0,1) for v in owner['labels'].values()):
        raise ValueError('invalid native human binary label')
    predictions={}
    for r in model['rows']:
        key=r['task_id']
        if key in predictions or type(r['candidate_id']) is not int:
            raise ValueError('duplicate/invalid model row')
        if set(r['probabilities']) != ROOT_METHODS:
            raise ValueError('missing/different original frozen Reader control')
        predictions[key]=r
    if set(predictions)!=names:
        raise ValueError('silent dropped/new predictions')
    for orig in ordered:
        pred=predictions[orig['task_id']]
        if any(pred[k] != orig[k] for k in ('candidate_id','source_group','question_slot')):
            raise ValueError('prediction origin/candidate order changed')

    out={};perq={}
    for method in sorted(ROOT_METHODS):
        correct=0;loss=0.0;success={};per_g_correct=defaultdict(int)
        for orig in ordered:
            y=owner['labels'][orig['task_id']]
            p=validate_scalar(predictions[orig['task_id']]['probabilities'][method])
            match=(p>=0.5)==bool(y)
            correct+=int(match)
            per_g_correct[orig['source_group']]+=int(match)
            loss+=2*(p-y)*(p-y)
        for q,ts in original.items():
            success[q]=int(all(((validate_scalar(predictions[t]['probabilities'][method])>=0.5)==bool(owner['labels'][t])) for t in ts))
        counts=defaultdict(int)
        for (g,_),v in success.items():counts[g]+=v
        r={'complete_questions':sum(success.values()), 'correct_candidates':correct,
           'brier':loss/len(ordered),'complete_passages':sum(v==2 for v in counts.values()),
           'total_questions':12,'total_candidates':51,'total_passages':6,
           'per_passage_candidate_correct':dict(sorted(per_g_correct.items())),
           'per_passage_complete_question':dict(sorted(counts.items()))}
        given=score['methods'][method]
        for k in r:
            if k=='brier':
                if not math.isclose(r[k],given[k],abs_tol=1e-12,rel_tol=0):
                    raise ValueError('independent Brier mismatch')
            elif r[k]!=given[k]:
                raise ValueError('independent original-human score mismatch: '+method+': '+k)
        out[method]=r
        perq[method]=success
    e24=perq['question_softworst_tau_001'];ref=perq['e16_scaled_brier_5']
    wins=sum(e24[k] > ref[k] for k in original)
    losses=sum(e24[k] < ref[k] for k in original)
    # Only per-question comparisons; source-level independence cannot be assumed.
    return {
      'schema':'hepta.ndu.original-e25-outside-old-four.v1',
      'status':'RESEARCH_DENY_ALL','e25_workflow_run_id':SOURCE_RUN,
      'e25_source_head':SOURCE_HEAD,'original_artifacts_sha256':{k:v[1] for k,v in SOURCES.items()},
      'unique_new_passage_groups':len(groups),'unique_new_questions':len(original),
      'original_human_candidate_alternatives':len(ordered),
      'original_four_passage_groups_reused':len(set(old)&set(fresh)),
      'all_original_prediction_labels_verified_after_seal':True,
      'methods':out,'e24_vs_e16_whole_question_paired':{'wins':wins,'losses':losses,'ties':len(original)-wins-losses},
      'independent_external_signer':False,'new_independent_dataset_family':False,
      'prospective_calendar_windows':0,'NDU_executed_on_new_six':False,
      'NDUspecific_task_improvement_verified':False,'total_matched_online_service_cost_verified':False,
      'production_accepted':False
    }


def run(input_dir,output,*,extracted=False):
    input_dir=pathlib.Path(input_dir)
    def get(kind,name):
        return read_automatic_unzip(input_dir,kind,name) if extracted else zip_member(input_dir/f'{kind}.zip',kind,name)
    pub=get('public','blind_slate.json')
    src=get('public','source.json')
    owner=get('owner','human-labels.json')
    model=get('model','sealed-new-six-blind-model-predictions.json')
    score=get('score','fixed-pretrained-new-six-original-human-question-score.json')
    answer=recount(pub,src,owner,model,score)
    out=pathlib.Path(output)
    with out.open('x') as f:
        json.dump(answer,f,sort_keys=True,separators=(',',':'))
        f.write('\n')
    return answer


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--inputs',required=True)
    ap.add_argument('--output',required=True)
    ap.add_argument('--extracted',action='store_true',help='Actions/download-artifact directories; member SHA locked')
    args=ap.parse_args()
    r=run(args.inputs,args.output,extracted=args.extracted)
    print(json.dumps({k:r[k] for k in ('unique_new_passage_groups','unique_new_questions','original_human_candidate_alternatives','e24_vs_e16_whole_question_paired','NDU_executed_on_new_six')},sort_keys=True))

if __name__=='__main__':main()
