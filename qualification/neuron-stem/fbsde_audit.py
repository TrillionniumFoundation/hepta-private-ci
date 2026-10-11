"""Read-only arithmetic audit for saved Encoder-study outputs, not an acceptance gate.

Deliberately imports neither the learned models nor either BSDE/formula solver.
Checks rendered answers, original labels, conditional-belief enumeration, matched
cases and once-only CPU sums. These checks do not authenticate physical execution.
"""
import hashlib
import itertools
import json
import math
import struct
from pathlib import Path
from four_gate_common import require, strict_loads


def _read(root, name):
    path = Path(root)/name
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 32*1024*1024,
            'bounded regular observation file required')
    return strict_loads(path.read_bytes())


def _digest(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,ensure_ascii=False,
        separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _truth(f, bits):
    if type(f) is int:
        require(0 <= f < len(bits), 'leaf index')
        return bits[f]
    require(type(f) is list and len(f)==3 and f[0] in ('and','or'), 'Boolean syntax')
    a,b=_truth(f[1],bits),_truth(f[2],bits)
    return a and b if f[0]=='and' else a or b


def _probability(q):
    require(type(q) in (float,int) and math.isfinite(q) and 0 <= q <= 1, 'invalid probability')
    return q


def _ns(value):
    require(type(value) is int and value >= 0, 'nonnegative integer CPU record')
    return value



def _cell_value(formula, probabilities, tables):
    if type(formula) is int:
        return probabilities[formula], 0., 0, 0
    left, el, dl, nl = _cell_value(formula[1], probabilities, tables)
    right, er, dr, nr = _cell_value(formula[2], probabilities, tables)
    op = int(formula[0]=='or')
    value = sum(tables[op][2*a+b]*(left if a else 1-left)*(right if b else 1-right)
                for a,b in itertools.product((0,1),repeat=2))
    exact_local = left+right-left*right if op else left*right
    return value, min(1., el+er+abs(value-exact_local)), 1+max(dl,dr), 1+nl+nr


def recompute_comparison(root, partitions):
    """Partitions are unchanged publisher rows (or explicitly labelled test fixtures)."""
    public=_read(root,'public-cases.json'); design=_read(root,'design.json')
    comparison=_read(root,'comparison.json'); beliefs=_read(root,'belief-inputs.json')
    require(set(public)=={'train','validation','calibration','test'}, 'complete splits')
    require(design['public_input_digests']=={k:_digest(v) for k,v in public.items()}, 'public input digest mismatch')
    require(design['question_profile']==comparison['question_profile'], 'question profile drift')
    require(comparison['question_profile'] in ('label_balanced_v1','independent_targets_v2','independent_targets_composition_v3'), 'unknown profile')
    labels={r['id']:r['intent'] for r in partitions['test']}
    test=public['test']; truth={}; source_sets={}
    require(len({r['case_id'] for r in test})==len(test), 'duplicate test case')
    source_hashes={r['id']:r.get('source_sha256',_digest(r['id'])) for r in partitions['test']}
    for row in test:
        require(len(row['utterance_ids'])==len(row['target_intents'])<=4, 'case dimensions')
        require(len(set(row['utterance_ids']))==len(row['utterance_ids']), 'dependent leaf input')
        require(all(type(t) is int and 0<=t<4 for t in row['target_intents']), 'target index')
        truth[row['case_id']]=bool(_truth(row['formula'],[labels[u]==t for u,t in
                                                      zip(row['utterance_ids'],row['target_intents'])]))
        source_sets[row['case_id']]={source_hashes[u] for u in row['utterance_ids']}
    require(truth==_read(root,'private-test-truths.json'), 'saved truth differs from publisher labels')
    require(set(beliefs)==set(truth), 'belief coverage')
    selection=_read(root,'selection.json')
    semantic_job=next(j for j in comparison['jobs_once'] if j['job_id']=='common_semantic')
    require(selection['common_semantic_sha256']==semantic_job['weights_sha256'], 'semantic model identity drift')
    expected={}; prior_expected={}
    for row in test:
        entry=beliefs[row['case_id']]; qs=entry['leaf_probabilities']
        require(entry['semantic_sha256']==selection['common_semantic_sha256'], 'belief semantic identity drift')
        require(entry['public_input_sha256']==_digest(row), 'belief input mismatch')
        require(len(qs)==len(row['utterance_ids']), 'belief dimensions')
        for p in qs: _probability(p)
        value=0.; prior=0.
        for world in itertools.product((False,True),repeat=len(qs)):
            weight=math.prod(q if bit else 1-q for bit,q in zip(world,qs))
            value+=weight*bool(_truth(row['formula'],world))
            prior+=math.prod(.25 if bit else .75 for bit in world)*bool(_truth(row['formula'],world))
        expected[row['case_id']]=value
        prior_expected[row['case_id']]=prior
    arms=set(comparison['metrics'])
    required={'light_head','recurrent_1','recurrent_4','recurrent_12','best_fixed',
              'simple_stop','fbsde_tree','exact_formula'}
    expected_arms = required | ({'syntax_prior'} if comparison['question_profile'] != 'label_balanced_v1' else set())
    learned = None
    if comparison['question_profile'] == 'independent_targets_composition_v3':
        expected_arms |= {'composition_frozen','composition_cell','composition_guarded'}
        learned = _read(root,'composition-corners.json')
        job = next(j for j in comparison['jobs_once'] if j['job_id']=='composition_cell')
        require(learned['weights_sha256']==job['weights_sha256'] and learned['parameters']==job['parameters']==8,
                'composition artifact identity drift')
        require(learned['initial']==[[.5]*4,[.5]*4], 'informative unregistered cell initialization')
        for table in (learned['initial'],learned['fitted']):
            require(len(table)==2 and all(len(row)==4 for row in table), 'corner dimensions')
            for row in table:
                for value in row: _probability(value)
        require(learned['corner_dtype']=='torch.float32' and learned['corner_byte_order'] in ('little','big'),
                'corner numeric profile')
        raw=struct.pack(('<' if learned['corner_byte_order']=='little' else '>')+'8f',
                        *(p for row in learned['fitted'] for p in row))
        th=hashlib.sha256(str(('torch.float32',(2,4))).encode('ascii')+raw).hexdigest()
        require(_digest({'corners':th})==learned['weights_sha256'], 'composition tensor bytes drift')
    require(arms==expected_arms, 'missing or extra comparison arm')
    result={}; inference={}
    for arm in sorted(arms):
        rows=_read(root,arm+'-predictions.json'); by_id={r['case_id']:r for r in rows}
        require(len(by_id)==len(rows)==len(truth) and set(by_id)==set(truth), 'unpaired predictions')
        correct=0; brier=0.
        for public_row in test:
            cid=public_row['case_id']; row=by_id[cid]; p=_probability(row['probability'])
            require(row['public_input_sha256']==_digest(public_row),'prediction input mismatch')
            text=('Yes, the stated condition is satisfied.' if p>=.5 else
                  'No, the stated condition is not satisfied.')
            require(row['text']==text,'decoded answer is not faithful')
            correct+=int((p>=.5)==truth[cid]); brier+=(p-truth[cid])**2
            if arm.startswith('composition_'):
                table = learned['initial'] if arm=='composition_frozen' else learned['fitted']
                value,error,depth,nodes = _cell_value(public_row['formula'],beliefs[cid]['leaf_probabilities'],table)
                meta = row['composition']
                require(meta['float_roundoff_rigorously_enclosed'] is False and
                        meta['semantic_truth_certified'] is False, 'unsupported composition certification')
                require(abs(meta['proposal_probability']-value)<1e-12, 'composition proposal differs from frozen cells')
                require(row['selected_depth']==depth and meta['learned_operator_calls']==nodes
                        and row['actual_recurrent_steps']==0, 'composition compute/depth mismatch')
                target = value
                if arm=='composition_guarded':
                    require(abs(meta['root_error_bound_exact_arithmetic']-error)<1e-12
                            and abs(value-expected[cid]) <= error+1e-12, 'original-law error bound mismatch')
                    stable = value-error > .5+1e-12 or value+error < .5-1e-12
                    require(meta['decision_stable_under_model']==stable and meta['exact_fallback']==(not stable),
                            'original-law fallback omitted or fabricated')
                    target = value if stable else expected[cid]
                    require(meta['guard_operator_calls']==nodes and
                            meta['fallback_operator_calls']==(0 if stable else nodes), 'hidden guard/fallback work')
                    require((p>=.5)==(expected[cid]>=.5), 'guard changed original-law decision')
                else:
                    require(meta['root_error_bound_exact_arithmetic'] is None and not meta['exact_fallback'],
                            'unguarded cell claiming correction')
                require(abs(p-target)<1e-12, 'composition output not reproduced')
            if arm == 'syntax_prior':
                require(abs(p-prior_expected[cid])<1e-12, 'syntax prior differs from no-text law')
            if arm in ('fbsde_tree','exact_formula'):
                require(abs(p-expected[cid])<1e-12,'solver output differs from belief enumeration')
        metrics={'count':len(rows),'decoded_exact_accuracy':correct/len(rows),'binary_brier':brier/len(rows)}
        require(metrics==comparison['metrics'][arm], 'reported metrics differ from original predictions')
        inference[arm]=sum(_ns(r['cpu_ns']) for r in rows)
        require(inference[arm]==comparison['inference_cpu_ns'][arm], 'inference CPU mismatch')
        result[arm]=metrics
    jobs=comparison['jobs_once']
    require(len({j['job_id'] for j in jobs})==len(jobs), 'duplicate physical preparation job')
    classified=sum(_ns(j['cpu_ns']) for j in jobs)+sum(inference.values())+\
               _ns(comparison['semantic_annotation_cpu_ns'])+_ns(comparison['evaluation_and_recording_cpu_ns'])
    require(classified==comparison['classified_jobs_once_cpu_ns'], 'classified CPU mismatch')
    require(classified+_ns(comparison['unattributed_preparation_and_reporting_cpu_ns'])==
            comparison['study_cpu_envelope_ns'], 'CPU envelope mismatch')
    # Independent case-component construction. Do not treat cases sharing sources as IID.
    components=[]
    for cid, sources in source_sets.items():
        ids={cid}; merged=set(sources); survivors=[]
        for old_ids,old_sources in components:
            if merged & old_sources: ids |= old_ids; merged |= old_sources
            else: survivors.append((old_ids,old_sources))
        components=survivors+[(ids,merged)]
    require(sorted([len(x[0]) for x in components],reverse=True)==
            comparison['source_census']['component_case_counts'], 'source component mismatch')
    return {'schema':'hepta.fbsde.encoder-arithmetic-audit.v1','question_profile':comparison['question_profile'],
            'metrics':result,'inference_cpu_ns':inference,'source_components':len(components),
            'cases':len(test),'belief_enumeration_matches':True,'cpu_envelope_reconciled':True,
            'same_source_dependence_reconciled':True,'physical_execution_authenticated':False,
            'scientific_superiority_established':False,'production_promotion_permitted':False}
