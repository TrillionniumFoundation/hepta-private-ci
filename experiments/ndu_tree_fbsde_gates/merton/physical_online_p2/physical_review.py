"""Postseal original publisher-label review. Never imported by model worker.

Validates actual seven-policy generation logs; reports real *self-metered* inference
rather than attributing historical precomputed traces as online savings.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from portfolio import Invalid, POLICIES, digest as p1_digest, manifest, run
from physical_online import SCHEMA, ACTION_MAX, strict, validate_source, make_prompt, parse_answer, prompt_seed, READER_PROFILE
from public_source import SCHEMA as SOURCE_SCHEMA, encoded, new_json, sha


def quantile(rows, q):
    if not rows:raise Invalid('empty latency cohort')
    s=sorted(rows)
    return s[max(0,math.ceil(len(s)*q)-1)]


def journal(path: Path, plan_sha: str, train_rows: list, served: list, contrasts: list) -> None:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 4_000_000:
        raise Invalid('original durable inference journal missing')
    # JSONL strict parsing, no duplicate keys, reject extra lines and out-of-order events.
    def parse_line(raw):
        def pairs(items):
            d={}
            for k,v in items:
                if k in d:raise Invalid('duplicate original journal field')
                d[k]=v
            return d
        try:
            return json.loads(raw,object_pairs_hook=pairs,
              parse_constant=lambda v: (_ for _ in ()).throw(Invalid('nonfinite journal')))
        except (ValueError,UnicodeError) as exc:
            raise Invalid('invalid original journal') from exc
    rows=path.read_text().splitlines()
    expected=[]
    for rec in train_rows:
        eid={'stage':'train','task_id':rec['task_id'],'action':rec['action']}
        expected.extend([{'event':'start',**eid},
                         {'event':'done',**eid,'output_sha256':sha(encoded(rec))}])
    expected.append({'event':'plan_frozen','sha256':plan_sha})
    for ix, rec in enumerate(served):
        eid={'stage':'held','policy':rec['policy'],'task_id':rec['task_id'],
             'action':rec['action'],'plan_sha256':plan_sha}
        expected.extend([{'event':'start',**eid},
                         {'event':'done',**eid,'output_sha256':sha(encoded(rec))}])
        if (ix + 1) % len(POLICIES) == 0:
            task_index = ix // len(POLICIES)
            for pair in contrasts[2*task_index:2*task_index+2]:
                ceid={'stage':'contrast','policy':pair['policy'],
                      'task_id':pair['task_id'], 'action':pair['action'],
                      'plan_sha256':plan_sha}
                expected.extend([{'event':'start',**ceid},
                                 {'event':'done',**ceid,'output_sha256':sha(encoded(pair))}])
    if len(rows) != len(expected) or any(parse_line(raw) != exp for raw,exp in zip(rows,expected)):
        raise Invalid('missing/misordered/preplanted original physical attempts')


def review(manifest_doc: Any, train: Any, held_public: Any, gold: Any,
           plan: Any, completed: Any, journal_path: Path) -> dict[str,Any]:
    acts,_,_,tariff=manifest(manifest_doc)
    public=validate_source(train,held_public)
    if type(gold) is not dict or set(gold) != {'schema','source','rows'} or gold['schema'] != SOURCE_SCHEMA+'.held-private-labels':
        raise Invalid('missing original publisher gold')
    if gold['source'] != held_public['source'] or type(gold['rows']) is not list or len(gold['rows']) != len(held_public['rows']):
        raise Invalid('original source/label mismatch')
    labels={}
    for row in gold['rows']:
        if type(row) is not dict or set(row) != {'task_id','label','text_sha256'}:
            raise Invalid('private publisher labels malformed')
        tid=row['task_id']
        if type(tid) is not str or tid in labels or type(row['label']) is not int or row['label'] not in range(4):
            raise Invalid('duplicate/invalid gold label')
        labels[tid]=row
    if set(labels) != {r['task_id'] for r in held_public['rows']} or any(
            labels[r['task_id']]['text_sha256'] != r['text_sha256'] for r in held_public['rows']):
        raise Invalid('gold/source text lineage is not original')
    if len(labels) != 16 or Counter(row['label'] for row in labels.values()) != Counter({k:4 for k in range(4)}):
        raise Invalid('P5 publisher held truth is not predeclared four-class balanced')
    if type(plan) is not dict or set(plan) != {'schema','manifest_sha256','train_source_sha256',
            'held_public_sha256','train_original_calls','train_original_outputs_sha256',
            'train_record','public_record','portfolio_attempt','selected_request_schedule',
            'paired_equalcap_schedule',
            'reader','research_only_deny_all'}:
        raise Invalid('frozen plan structural drift')
    if plan['schema'] != SCHEMA+'.frozen-plan' or plan['research_only_deny_all'] is not True:
        raise Invalid('invalid frozen plan authority')
    if (plan['manifest_sha256'] != p1_digest(manifest_doc) or
        plan['train_source_sha256'] != sha(encoded(train)) or
        plan['held_public_sha256'] != sha(encoded(held_public)) or
        plan['public_record'] != public or
        plan['portfolio_attempt'] != run(manifest_doc,plan['train_record'],public)):
        raise Invalid('frozen plan consumed changed TRAIN or PUBLIC material')
    # Independent derivation from the frozen P1 policy assignments; do not
    # accept an execution worker's preferred order even with a matching seal.
    arms = plan['portfolio_attempt']['attempt']['policies']
    if [p['policy'] for p in arms] != list(POLICIES):
        raise Invalid('frozen policy arms changed')
    expected_schedule = []
    for i, case in enumerate(sorted(public['cases'], key=lambda x: x['task_id'])):
        tid = case['task_id']
        for j in range(len(arms)):
            arm = arms[(i+j) % len(arms)]
            expected_schedule.append({'policy': arm['policy'], 'task_id': tid,
                                      'action': arm['assignments'][tid]})
    if plan['selected_request_schedule'] != expected_schedule:
        raise Invalid('frozen physical policy schedule substitution')
    # Independent equal-cap contrast: no training outcomes may choose the
    # comparison arms or their timing. Both must always run on every held case.
    expected_pairs = []
    for i, case in enumerate(sorted(public['cases'], key=lambda x: x['task_id'])):
        ordered = ('reason','reason_equalcap') if i % 2 == 0 else ('reason_equalcap','reason')
        for action in ordered:
            expected_pairs.append({'task_id':case['task_id'],
                                   'policy':'equal_cap','action':action})
    if plan['paired_equalcap_schedule'] != expected_pairs:
        raise Invalid('unfrozen or tampered 96-token matched contrast schedule')
    frozen_sha=sha(encoded(plan))
    if type(completed) is not dict or set(completed) != {
        'schema','frozen_plan_sha256','manifest_sha256','train_original_sha256',
        'plan_frozen_before_held_requests','original_pretrained_reader_execution',
        'physical_model_identity','actual_training_requests','actual_online_policy_requests',
        'total_generation_invocations','original_train_trace','actual_policy_trace',
        'actual_equalcap_contrast_requests','paired_equalcap_trace',
        'model_load_cpu_seconds','model_load_wall_seconds','execution_cpu_seconds',
        'execution_wall_seconds','actual_model_savings_verified',
        'independent_model_execution_attestation','independent_human_task_scoring',
        'prospective_source_windows','authority'}:
        raise Invalid('original model completed record modified')
    if (completed['schema'] != SCHEMA+'.completed-original' or
        completed['frozen_plan_sha256'] != frozen_sha or
        completed['manifest_sha256'] != p1_digest(manifest_doc) or
        completed['original_pretrained_reader_execution'] is not True or
        completed['plan_frozen_before_held_requests'] is not True or
        completed['model_load_cpu_seconds'] < 0 or
        completed['model_load_wall_seconds'] < 0 or
        completed['actual_model_savings_verified'] is not False or
        completed['independent_model_execution_attestation'] is not False or
        completed['independent_human_task_scoring'] is not False or
        completed['prospective_source_windows'] != 0 or
        completed['authority'] != 'RESEARCH_ONLY_DENY_ALL' or
        completed['physical_model_identity'] != plan['reader']):
        raise Invalid('false physics, immutable identity or authority claim')
    from physical_online import MODEL_REPO, MODEL_REV, assert_original_checkpoint_hashes
    identity=completed['physical_model_identity']
    if type(identity) is not dict or identity.get('repo') != MODEL_REPO or identity.get('revision') != MODEL_REV or identity.get('actual_pretrained_model_loaded') is not True:
        raise Invalid('unregistered pretrained Reader identity')
    if identity.get('runtime') != READER_PROFILE:
        raise Invalid('wrong frozen thinking/decoding research profile')
    if any(type(identity.get(k)) is not str or len(identity[k]) != 64 or
           any(ch not in '0123456789abcdef' for ch in identity[k])
           for k in ('weights_sha256','tokenizer_sha256')):
        raise Invalid('unbound original model file bytes')
    assert_original_checkpoint_hashes(identity['weights_sha256'], identity['tokenizer_sha256'])
    for metric_name in ('model_load_cpu_seconds','model_load_wall_seconds',
                        'execution_cpu_seconds','execution_wall_seconds'):
        metric = completed[metric_name]
        if type(metric) not in (float,int) or not math.isfinite(metric) or not 0 <= metric < 86400:
            raise Invalid('invalid original full-lifecycle CPU/wall meter: '+metric_name)
    train_log=completed['original_train_trace']; served=completed['actual_policy_trace']
    contrasts=completed['paired_equalcap_trace']
    if type(train_log) is not list or type(served) is not list or type(contrasts) is not list or (
        len(train_log) != len(train['rows'])*len(acts) or len(served) != len(held_public['rows'])*len(POLICIES) or
        len(contrasts) != 2*len(held_public['rows']) or
        completed['actual_training_requests'] != len(train_log) or
        completed['actual_online_policy_requests'] != len(served) or
        completed['actual_equalcap_contrast_requests'] != len(contrasts) or
        completed['total_generation_invocations'] != len(train_log)+len(served)+len(contrasts) or
        plan['train_original_calls'] != len(train_log) or
        plan['train_original_outputs_sha256'] != sha(encoded(train_log)) or
        completed['train_original_sha256'] != sha(encoded(train_log))):
        raise Invalid('missing actual physical model requests')
    names={r['task_id']:r for r in held_public['rows']}
    expected_train=[(r['task_id'],action.name) for r in sorted(train['rows'],key=lambda x:x['task_id']) for action in acts]
    if [(r['task_id'],r['action']) for r in train_log] != expected_train:
        raise Invalid('original training model request order substituted')
    recalculated=[]
    train_by_id={r['task_id']:r for r in train['rows']}
    train_gold={r['task_id']:r['label'] for r in train['rows']}
    for r in train_log:
        check_output(r)
        if r['source_kind'] != 'original_physical' or r['policy'] != 'train':
            raise Invalid('synthetic training Reader output')
        original_prompt = make_prompt(train_by_id[r['task_id']]['text'], r['action'])
        if r['prompt_sha256'] != sha(encoded(original_prompt)) or r['sampling_seed'] != prompt_seed(original_prompt):
            raise Invalid('original TRAIN model prompt/sampling seed was substituted')
        recalculated.append({'task_id':r['task_id'],
          'bucket':next(x['bucket'] for x in train['rows'] if x['task_id']==r['task_id']),
          'group':next(x['group'] for x in train['rows'] if x['task_id']==r['task_id']),
          'action':r['action'], 'success':int(r['predicted_class']==train_gold[r['task_id']])})
    if {'schema':'hepta.p1.train.v1','rows':recalculated} != plan['train_record']:
        raise Invalid('original TRAIN success was not independently recounted')
    if [(r['policy'],r['task_id'],r['action']) for r in served] != [
        (r['policy'],r['task_id'],r['action']) for r in expected_schedule]:
        raise Invalid('non-precommitted on-policy model request(s)')
    for r in served:
        check_output(r)
        if r['source_kind'] != 'original_physical' or r['task_id'] not in names:
            raise Invalid('replayed/synthetic/unknown physical Reader')
        original_prompt = make_prompt(names[r['task_id']]['text'], r['action'])
        if r['prompt_sha256'] != sha(encoded(original_prompt)) or r['sampling_seed'] != prompt_seed(original_prompt):
            raise Invalid('original held model prompt/sampling seed was substituted')
    if [(r['policy'],r['task_id'],r['action']) for r in contrasts] != [
            (p['policy'],p['task_id'],p['action']) for p in expected_pairs]:
        raise Invalid('matched 96-token physical contrast order was substituted')
    for r in contrasts:
        check_output(r)
        if r['source_kind'] != 'original_physical' or r['policy'] != 'equal_cap' or r['task_id'] not in names:
            raise Invalid('unqualified original matched-contrast Reader output')
        original_prompt = make_prompt(names[r['task_id']]['text'], r['action'])
        if r['prompt_sha256'] != sha(encoded(original_prompt)) or r['sampling_seed'] != prompt_seed(original_prompt):
            raise Invalid('matched contrast prompt or seed did not originate from public task')
    journal(journal_path,frozen_sha,train_log,served,contrasts)
    training_tokens=sum(x['input_tokens']+x['output_tokens'] for x in train_log)
    training_cpu=sum(x['measured_cpu_seconds'] for x in train_log)
    by_policy={}
    for row in served:
        by_policy.setdefault(row['policy'],[]).append(row)
    direct={r['task_id']:r for r in by_policy['direct']}
    scores=[]
    for policy in POLICIES:
        rows=by_policy[policy]
        correct=sum(int(r['predicted_class']==labels[r['task_id']]['label']) for r in rows)
        counted=sum(r['input_tokens']+r['output_tokens'] for r in rows)
        cpu=sum(r['measured_cpu_seconds'] for r in rows)
        wall=sum(r['measured_wall_seconds'] for r in rows)
        direct_delta=sum((r['input_tokens']+r['output_tokens']) -
           (direct[r['task_id']]['input_tokens']+direct[r['task_id']]['output_tokens']) for r in rows)
        wins=sum(int(r['predicted_class']==labels[r['task_id']]['label']) and
                not int(direct[r['task_id']]['predicted_class']==labels[r['task_id']]['label']) for r in rows)
        losses=sum(not int(r['predicted_class']==labels[r['task_id']]['label']) and
                int(direct[r['task_id']]['predicted_class']==labels[r['task_id']]['label']) for r in rows)
        scores.append({'policy':policy,'correct':correct,'of':len(rows),
            'thinking_segment_tokens':sum(r['thinking_segment_tokens'] for r in rows),
            'thinking_mode_requests':sum(r['thinking_mode'] for r in rows),
            'unfinished_thinking_requests':sum(r['thinking_mode'] and not r['thinking_complete'] for r in rows),
            'actual_full_input_and_output_tokens':counted,
            'actual_token_difference_vs_independently_executed_direct':direct_delta,
            'actual_cpu_seconds':round(cpu,9), 'actual_wall_seconds':round(wall,9),
            'request_wall_p95_ms':round(1000*quantile([r['measured_wall_seconds'] for r in rows],.95),3),
            'request_wall_p99_ms':round(1000*quantile([r['measured_wall_seconds'] for r in rows],.99),3),
            'task_rescues_against_direct':wins,'task_losses_against_direct':losses,
            'external_correct_minus_FULL_serving_token_tariff':str(correct - tariff*counted),
            'illustrative_single_arm_cold_start_net_tokens_only':str(correct - tariff*(counted+training_tokens)),
            'cold_start_calibration_fee_shared_not_summable':True})
    # Paid paired contrast uses *only* original public task-specific prompts
    # and a 96-token generation maximum in both Qwen3 modes. The observed
    # generated-token counts need not be equal: early EOS is valid behavior.
    matched={r['task_id']: {} for r in contrasts}
    for r in contrasts:
        if r['action'] in matched[r['task_id']]:
            raise Invalid('duplicate equal-cap arm for task')
        matched[r['task_id']][r['action']]=r
    if set(matched) != set(names) or any(set(v) != {'reason','reason_equalcap'} for v in matched.values()):
        raise Invalid('matched contrast paired-task support missing')
    paired_gain=paired_loss=paired_both=paired_neither=0
    for tid, sides in matched.items():
        truth=labels[tid]['label']
        think = sides['reason']['predicted_class'] == truth
        plain = sides['reason_equalcap']['predicted_class'] == truth
        paired_gain += int(think and not plain)
        paired_loss += int(plain and not think)
        paired_both += int(think and plain)
        paired_neither += int(not think and not plain)
    paired_profile=[]
    for action in ('reason','reason_equalcap'):
        rows=[matched[tid][action] for tid in sorted(matched)]
        paired_profile.append({
          'action':action, 'max_generated_token_ceiling':96,
          'actual_independent_model_invocations':len(rows),
          'correct':sum(r['predicted_class'] == labels[r['task_id']]['label'] for r in rows),
          'total_input_tokens':sum(r['input_tokens'] for r in rows),
          'total_generated_tokens':sum(r['output_tokens'] for r in rows),
          'total_thinking_tokens':sum(r['thinking_segment_tokens'] for r in rows),
          'incomplete_thinking':sum(r['thinking_mode'] and not r['thinking_complete'] for r in rows),
          'cpu_seconds':round(sum(r['measured_cpu_seconds'] for r in rows),9),
          'wall_seconds':round(sum(r['measured_wall_seconds'] for r in rows),9),
          'p95_request_wall_ms':round(1000*quantile([r['measured_wall_seconds'] for r in rows],.95),3),
          'p99_request_wall_ms':round(1000*quantile([r['measured_wall_seconds'] for r in rows],.99),3),
        })
    paired_contrast={
       'schema':SCHEMA+'.matched-equal-cap', 'same_user_prompt_and_sampling_seed':True,
       'thinking_mode_vs_equalcap_nonthinking':paired_profile,
       'taskwise_thinking_wins':paired_gain, 'taskwise_thinking_losses':paired_loss,
       'taskwise_both_correct':paired_both, 'taskwise_neither_correct':paired_neither,
       'paired_tasks':len(matched), 'observed_saved_compute_claim':False,
       'science_boundary':'HISTORICAL_PUBLIC_8_TASKS_NOT_PROSPECTIVE_NO_CAUSAL_GENERALIZATION',
    }
    # Same objective has same frozen decisions; physically executed copies may still differ.
    if (plan['portfolio_attempt']['attempt']['policies'][-2]['assignments'] !=
        plan['portfolio_attempt']['attempt']['policies'][-1]['assignments']):
        raise Invalid('ordinary same-profile parity broken')
    return {'schema':SCHEMA+'.postseal-review',
       'original_publisher_gold_sha256':sha(encoded(gold)),
       'frozen_plan_sha256':frozen_sha,
       'completed_original_sha256':sha(encoded(completed)),
       'model_identity':identity,
       'physical_on_policy_generation_invocations_self_reported':len(train_log)+len(served)+len(contrasts),
       'additional_paid_equalcap_invocations':len(contrasts),
       'actual_training_input_output_tokens':training_tokens,
       'actual_training_cpu_seconds':round(training_cpu,9),
       'actual_model_load_cpu_seconds':completed['model_load_cpu_seconds'],
       'actual_model_load_wall_seconds':completed['model_load_wall_seconds'],
       'original_total_execution_cpu_seconds':completed['execution_cpu_seconds'],
       'original_total_execution_wall_seconds':completed['execution_wall_seconds'],
       'seven_policy_results':scores,
       'paired_equalcap_96_token_contrast':paired_contrast,
       'historical_public_test_set_not_future_window':True,
       'original_publisher_label_balance':{str(i):4 for i in range(4)},
       'publisher_labels_available_to_source_owner_only_before_seal':True,
       'independent_hardware_attestation':False,
       'actual_model_savings_proven':False,
       'no_training_cost_double_charge':True,
       'claim':'ORIGINAL_PRETRAINED_ONLINE_MODEL_INVOCATIONS_SELF_METERED_NO_GO',
       'authority':'RESEARCH_ONLY_DENY_ALL'}


def check_output(r: Any) -> None:
    allowed={'task_id','policy','action','prompt_sha256','input_token_ids_sha256',
       'output_token_ids_sha256','input_tokens','output_tokens','answer','answer_sha256',
       'predicted_class','measured_cpu_seconds','measured_wall_seconds','source_kind',
       'thinking_mode','thinking_segment_tokens','thinking_complete','sampling_seed'}
    if type(r) is not dict or set(r) != allowed or r['action'] not in ACTION_MAX:
        raise Invalid('original physical output schema invalid')
    if (type(r['input_tokens']) is not int or not 1 <= r['input_tokens'] <= 768 or
        type(r['output_tokens']) is not int or not 1 <= r['output_tokens'] <= ACTION_MAX[r['action']]):
        raise Invalid('source token counts invalid')
    if (type(r['answer']) is not str or
        (r['predicted_class'] is not None and (type(r['predicted_class']) is not int or r['predicted_class'] not in range(4))) or
        r['predicted_class'] != parse_answer(r['answer']) or
        r['answer_sha256'] != sha(r['answer'].encode())):
        raise Invalid('tampered physical model answer')
    if (type(r['thinking_mode']) is not bool or r['thinking_mode'] != (r['action'] == 'reason') or
        type(r['thinking_complete']) is not bool or
        type(r['thinking_segment_tokens']) is not int or
        not 0 <= r['thinking_segment_tokens'] <= r['output_tokens'] or
        type(r['sampling_seed']) is not int or not 0 <= r['sampling_seed'] <= 2**32-1):
        raise Invalid('invalid Qwen3 thinking token/seed record')
    if r['action'] == 'reason':
        if r['thinking_segment_tokens'] < 1 or (not r['thinking_complete'] and
             (r['answer'] or r['predicted_class'] is not None)):
            raise Invalid('truncated thinking presented as final prediction')
    elif r['thinking_complete'] or r['thinking_segment_tokens'] != 0:
        raise Invalid('nonthinking action carries fake thought')
    for k in ('prompt_sha256','input_token_ids_sha256','output_token_ids_sha256'):
        if type(r[k]) is not str or len(r[k]) != 64 or any(ch not in '0123456789abcdef' for ch in r[k]):
            raise Invalid('tampered model token digest')
    for k in ('measured_cpu_seconds','measured_wall_seconds'):
        if type(r[k]) not in (float,int) or not math.isfinite(r[k]) or not 0 <= r[k] < 3600:
            raise Invalid('invalid physical CPU or wall meter')


def main():
    p=argparse.ArgumentParser()
    for name in ('manifest','train-public','held-public','held-private-labels','frozen-plan',
                 'original','journal','output'):
        p.add_argument('--'+name,required=True)
    args=p.parse_args()
    result=review(strict(args.manifest),strict(args.train_public),strict(args.held_public),
        strict(args.held_private_labels),strict(args.frozen_plan),strict(args.original),Path(args.journal))
    new_json(Path(args.output),result)
    print(json.dumps({'physical_invocations':result['physical_on_policy_generation_invocations_self_reported'],
      'original_gold_reviewed':True,'promoted':False,'authority':'DENY_ALL'}))

if __name__=='__main__':
    main()
