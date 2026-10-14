"""Small public-model execution diagnostic, NOT an efficacy qualification.

Initial AND revised answers come from one shared local causal LM. The reviewer
requests one revision without asserting correctness. A separate exact-integer
scorer runs only after all pairs seal. Four public arithmetic cases do not establish
independent cohorts or validate a learned critic. Missing costs still block fitting.
"""
from __future__ import annotations

import argparse
import copy
import json
import time
from dataclasses import asdict
from pathlib import Path

from hf_causal_generator import DecodeLimits, LocalCausalProposer
from hf_encoder_kernel import snapshot_digest
from matrix_materials import file_sha256
from matrix_runtime import write_json_exclusive
from next_round_matrix import _digest
from paired_execution import PHASES
from public_encoder_probe import acquire_public

MODEL_ID = 'HuggingFaceTB/SmolLM2-135M-Instruct'
CASES = (('sum-1','2 + 3',5), ('sum-2','7 + 8',15),
         ('difference','9 - 4',5), ('product','6 * 3',18))
REVIEW = 'Give a direct answer containing only the integer result. Recheck your response.'


def request_revision(task, candidate):
    from system2_execution import Verification
    # A review REQUEST, deliberately not an independent correctness verifier.
    return Verification(False, REVIEW)


def probe(snapshot, root):
    import torch
    from execution_meter import WorkLedger, TRANSFORMER_POLICY_SCHEMA
    from transformer_work import PROFILE
    from system2_execution import PublicTask
    from empirical_continuation import case_fingerprint
    from paired_capture import freeze_capture, create_capture, PairCollector
    from paired_capture_export import OBSERVER_SCHEMA, read_pair, assemble_pairs, fit_collected
    from paired_critic import freeze_protocol
    torch.set_num_threads(1)
    limits = DecodeLimits(prompt_tokens=256, new_tokens=16)
    proposer = LocalCausalProposer(snapshot, expected_snapshot_sha256=snapshot_digest(snapshot), limits=limits)
    callback_id = _digest({'generator':proposer.receipt, 'reviewer':'always_request_one_revision_not_truth',
                          'reviewer_source_sha256':file_sha256(__file__)})
    policy = dict(schema=TRANSFORMER_POLICY_SCHEMA, arithmetic_profile=PROFILE, mode='observe',
        wall_time_ns=600_000_000_000, max_process_rss_bytes=None, rapl_zone=None, rapl_max_power_watts=None)
    caps = dict.fromkeys(PHASES, 10**13)
    initial, pairs, boundaries = [], [], []
    for i, (name, expression, _) in enumerate(CASES):
        task = PublicTask('Calculate ' + expression + '. Answer with only the integer result.', time.time_ns())
        meter = WorkLedger(policy, caps)
        with meter.scope('inference','proposer'):
            answer = proposer(task, None, None)
        check = request_revision(task, answer)
        record = dict(task=asdict(task), candidate=answer, verification=asdict(check),
            generation=copy.deepcopy(proposer.last_observation), work_observation=meter.report())
        write_json_exclusive(root / f'initial-{i}.json', record)
        initial.append(record)
        pairs.append(dict(pair_id=name, group_id=name,
            case_sha256=case_fingerprint(task,answer,check.feedback),
            candidate_bytes=len(answer.encode()),feedback_bytes=len(check.feedback.encode())))
        boundaries.append(dict(pair_id=name,task=json.loads(json.dumps(asdict(task))),candidate=answer,
            feedback=check.feedback,initial_verifier_accepted=False,available_at_ns=time.time_ns(),
            origin_receipt_sha256=file_sha256(root / f'initial-{i}.json')))
    now = time.time_ns()
    protocol = freeze_protocol(objective_sha256=_digest('exact-stripped-integer-from-fixed-public-expression.v1'),
        subject_id='episode:public-causal-diagnostic', callback_profile_sha256=callback_id,
        observer_sha256=_digest('same-process-public-arithmetic-oracle-not-independent'),
        registered_at_ns=now, cutoff_ns=now+600_000_000_000, expires_at_ns=now+3_600_000_000_000,
        fit_groups=sorted([c[0] for c in CASES[:2]]), calibration_groups=sorted([c[0] for c in CASES[2:]]),
        pairs=pairs,candidate_edges=[4096],feedback_edges=[4096],alpha=.05,minimum_groups=2,
        max_calibration_gap=1.,duration_upper_ns=120_000_000_000,formula_work_upper=10**12,
        coefficients=dict(discount_rate_per_second=0.,cost_per_formula_flop=0.,cost_per_latency_ns=0.))
    registration=freeze_capture(protocol,expected_protocol_id=protocol['protocol_id'],boundaries=boundaries,
        meter_policy=policy,phase_caps=caps)
    target=root/'capture';create_capture(target,registration)
    collector=PairCollector(target,expected_capture_id=registration['capture_id'],
        callback_profile_sha256=callback_id,propose=proposer,verify=request_revision)
    terminals, outputs=[],[]
    for pair in pairs:
        terminals.append(collector.run_pair(pair['pair_id']))
        outputs.append(copy.deepcopy(proposer.last_observation))
    proposer.reverify()
    # Exactly repeat the first initial request after all intervening calls.
    repeat_meter=WorkLedger(policy,caps)
    with repeat_meter.scope('inference','proposer'):
        repeated=proposer(PublicTask(**{**initial[0]['task'],'observations':tuple(initial[0]['task']['observations'])}),None,None)
    if repeated != initial[0]['candidate']:
        raise ValueError('shared model repeated input changed across independent calls')
    write_json_exclusive(root/'repeat.json',dict(candidate=repeated,work_observation=repeat_meter.report()))
    proposer.reverify()
    records=[read_pair(target,registration,i,t['terminal_id'])[0] for i,t in enumerate(terminals)]
    observed=time.time_ns()
    labels=[]
    for (_,_,answer), record in zip(CASES,records,strict=True):
        labels.append(dict(pair_id=record['pair_id'], stop_candidate_sha256=_digest(record['stop_candidate']),
            continue_candidate_sha256=_digest(record['continue_candidate']),
            stop_utility=int(record['stop_candidate'].strip()==str(answer)),
            continue_utility=int(record['continue_candidate'] is not None and record['continue_candidate'].strip()==str(answer)),
            observed_at_ns=observed))
    observer=dict(schema=OBSERVER_SCHEMA,capture_id=registration['capture_id'],protocol_id=protocol['protocol_id'],
        objective_sha256=protocol['objective_sha256'],observer_sha256=protocol['observer_sha256'],
        created_at_ns=time.time_ns(),terminal_ids=[t['terminal_id'] for t in terminals],rows=labels)
    op=root/'objective-scores.json';write_json_exclusive(op,observer)
    p,rows,lineage=assemble_pairs(target,expected_capture_id=registration['capture_id'],observer_path=op,
        expected_observer_sha256=file_sha256(op))
    write_json_exclusive(root/'paired-rows.json',rows);write_json_exclusive(root/'lineage.json',lineage)
    try:
        critic, work=fit_collected(p,rows,lineage)
        write_json_exclusive(root/'critic.json',critic);write_json_exclusive(root/'fit-work.json',work)
        fit_status='fitted_small_diagnostic_not_validated'
    except ValueError as exc:
        # Preserve all costs/rows; incomplete HF operator coverage commonly
        # blocks fit. Never filter pairs or substitute a partial numeric total.
        write_json_exclusive(root/'FIT_BLOCKED.json',{'reason':str(exc),'qualified':False})
        fit_status='blocked'
    return dict(schema='hepta.public-causal-paired-probe.v1',public_source_target=MODEL_ID,generator=proposer.receipt,
        initial_generations=len(initial),captured_pairs=len(records),repeat_input_exact=True,
        initial_outputs=[r['candidate'] for r in initial],revised_outputs=[r['continue_candidate'] for r in records],
        initial_generation_records=[r['generation'] for r in initial],revision_generation_records=outputs,
        pair_statuses=[r['status'] for r in records],scores=labels,fit_status=fit_status,
        reviewer_is_correctness_verifier=False,observer_independently_authenticated=False,
        initial_and_repeat_work_retained=True,efficacy_established=False,
        cost_matched_comparison_completed=False,production_authorized=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--acquire-public',action='store_true');mode.add_argument('--snapshot')
    parser.add_argument('--output',required=True);args=parser.parse_args()
    root=Path(args.output);root.mkdir(parents=True,exist_ok=False)
    try:
        snapshot=acquire_public(root,model_id=MODEL_ID) if args.acquire_public else Path(args.snapshot)
        result=probe(snapshot,root)
        result['source_kind']='pinned_public_Hub_checkpoint' if args.acquire_public else 'operator_local_snapshot'
        result['model_id']=MODEL_ID if args.acquire_public else None
        write_json_exclusive(root/'probe.json',result)
        print(json.dumps(result,sort_keys=True,allow_nan=False))
    except Exception as exc:
        write_json_exclusive(root/'FAILED.json',{'error_type':type(exc).__name__,'message':str(exc),'completed':False})
        raise


if __name__=='__main__':
    main()
