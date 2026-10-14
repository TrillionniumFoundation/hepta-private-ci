#!/usr/bin/env python3
"""Real-weight, separately witnessed shadow forecast: seal before outcome access.

A signed claim is not a trusted host attestation, and comparisons here cannot
approve NDU, a Cell split or production use. The seal command has no labels input.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any

from a0_deployment_evidence import load_public_key, verify_signed
from matched_train import CAPS, ARMS, H, Q, sha_bytes, sha_file, unique_json, utc, require, make_model

FORECAST_SCHEMA = 'hepta.neuron.unlabelled-future-q24.v1'
BASELINE_SCHEMA = 'hepta.neuron.owner-v1-frozen-predictions.v1'
SEAL_SCHEMA = 'hepta.neuron.five-arm-research-forecast-seal.v1'
WITNESS_SCHEMA = 'hepta.neuron.five-arm-precommit-witness.v1'
OUTCOME_SCHEMA = 'hepta.neuron.five-arm-independent-outcomes.v1'


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def exact(value: Any, keys: set[str], label: str) -> dict:
    require(type(value) is dict and set(value) == keys, label + ': wrong fields')
    return value


def future_data(data: Any, receipt: dict) -> tuple[int, list[list[dict]]]:
    exact(data, {'schema', 'encoder_digest', 'cell_id', 'samples'}, 'future dataset')
    require(data['schema'] == FORECAST_SCHEMA, 'wrong future dataset schema')
    require(data['encoder_digest'] == receipt['encoder_digest_claimed'] and
            data['cell_id'] == receipt['cell_id'], 'future encoder/cell drift')
    samples = data['samples']
    require(type(samples) is list and 2 <= len(samples) <= 8192, 'bad future case count')
    cutoff = utc(receipt['training_cutoff_utc'])
    groups = defaultdict(list)
    seen = set()
    width = receipt['models'][0]['width']
    groups_frozen = set(receipt['train_source_group_hashes'])
    partitions = set()
    for row in samples:
        exact(row, {'case_id','source_group','sequence','event_time_utc',
                    'feature_q24','partition'}, 'unlabelled future row (no labels allowed)')
        case, group = row['case_id'], row['source_group']
        require(type(case) is str and 0 < len(case) <= 128 and case not in seen, 'duplicate/bad future case')
        require(type(group) is str and 0 < len(group) <= 128, 'invalid source group')
        require(sha_bytes(group.encode()) not in groups_frozen, 'source group crossed training/future')
        require(type(row['sequence']) is int and row['sequence'] > 0, 'future sequence invalid')
        require(utc(row['event_time_utc']) > cutoff, 'future event precedes cutoff')
        require(row['partition'] in ('future','ood'), 'missing OOD/future partition')
        seq = row['feature_q24']
        require(type(seq) is list and len(seq) == width and
                all(type(v) is int and -H <= v <= H for v in seq), 'future Q24 feature invalid')
        partitions.add(row['partition'])
        seen.add(case)
        groups[group].append(row)
    require(partitions == {'future','ood'}, 'future and OOD cases both required')
    require(len(groups) <= 128, 'too many future groups')
    for group in groups.values():
        require(len(group) <= 256, 'unbounded future sequence')
        group.sort(key=lambda r:r['sequence'])
        require(all(group[i]['sequence'] < group[i+1]['sequence'] and
                    utc(group[i]['event_time_utc']) < utc(group[i+1]['event_time_utc'])
                    for i in range(len(group)-1)), 'future clock or sequence regression')
    return width, [groups[k] for k in sorted(groups)]


def physical_models(root: Path, receipt: dict) -> dict[tuple[int,str],dict]:
    entries = receipt['models']
    require(type(entries) is list and len(entries) == len(ARMS)*len(CAPS), 'incomplete trained arms')
    seen = {}
    for row in entries:
        cap, arm = row['cap'], row['arm']
        require(type(cap) is int and cap in CAPS and arm in ARMS and (cap,arm) not in seen,
                'duplicate/unknown trained model')
        filename = f'{cap}/{arm}.safetensors'
        require(row['weight_file'] == filename, 'trained artifact relative path mismatch')
        sha_file(root / filename, row['weight_sha256'])
        require(type(row['parameter_count']) is int and row['parameter_count'] <= cap and
                row['optimizer_steps'] == receipt['candidate_optimizer_steps'], 'budget/train steps drift')
        seen[(cap,arm)] = row
    return seen


def seal(args: argparse.Namespace) -> dict:
    root = Path(args.trained_root).resolve(strict=True)
    receipt_file = root/'training-receipt.json'
    sha_file(receipt_file,args.receipt_sha256)
    receipt = unique_json(receipt_file.read_bytes())
    require(receipt['schema'] == 'hepta.neuron.five-arm-differentiable-shadow-train.v1' and
            receipt['no_change_optimizer_steps'] == 0 and
            receipt['production_qualification'] is False, 'unsupported training receipt')
    models = physical_models(root, receipt)
    future_path = Path(args.future_features)
    future_sha = sha_file(future_path, args.future_sha256)
    future = unique_json(future_path.read_bytes())
    width, groups = future_data(future, receipt)
    base_path = Path(args.frozen_v1_predictions)
    base_sha = sha_file(base_path, args.frozen_v1_predictions_sha256)
    base = unique_json(base_path.read_bytes())
    exact(base, {'schema','selected_v1_sha256','cell_id','predictions'}, 'selected V1 owner predictions')
    require(base['schema'] == BASELINE_SCHEMA and
            base['selected_v1_sha256'] == receipt['no_change_v1_selected_sha256'] and
            base['cell_id'] == receipt['cell_id'], 'unmatched native frozen baseline')
    predictions = {}
    for x in base['predictions']:
        exact(x, {'case_id','probability_ppm','model_invocation_digest'}, 'owner baseline row')
        ident = x['case_id']
        require(type(ident) is str and ident not in predictions, 'baseline row duplicate')
        prob, inv = x['probability_ppm'], x['model_invocation_digest']
        require(type(prob) is int and 0 <= prob <= 1000000 and
                type(inv) is str and len(inv) == 64 and
                all(c in '0123456789abcdef' for c in inv) and inv != '0'*64,
                'invalid owner frozen prediction')
        predictions[ident] = x
    require(set(predictions) == {r['case_id'] for g in groups for r in g},
            'owner baseline missing/extra future case')
    import torch
    from safetensors.torch import load_file
    torch.set_num_threads(1)
    out = {r['case_id']:{'case_id':r['case_id'], 'source_group_sha256':sha_bytes(r['source_group'].encode()),
                         'event_time_utc':r['event_time_utc'], 'partition':r['partition'],
                         'input_sha256':sha_bytes(json.dumps(r['feature_q24'],separators=(',',':')).encode()),
                         'owner_v1_probability_ppm':predictions[r['case_id']]['probability_ppm'],
                         'owner_v1_invocation_digest':predictions[r['case_id']]['model_invocation_digest'],
                         'candidates':{}} for g in groups for r in g}
    for cap in CAPS:
        for arm in ARMS:
            model_info = models[(cap,arm)]
            model = make_model(arm, width, model_info['rank'] or 0, torch)
            weights = load_file(str(root/model_info['weight_file']), device='cpu')
            require(type(weights) is dict and set(weights) ==
                    {'structure.projection','head.weight','head.bias'} |
                    ({'temporal.gate_bias','temporal.input_gain','temporal.change_gain'} if arm=='v3' else
                     {'temporal.decay_per_step','temporal.input_gain'} if arm=='ssm' else
                     {'temporal.gate_input','temporal.gate_output','temporal.candidate_input',
                      'temporal.candidate_output','temporal.gate_bias','temporal.candidate_bias'} if arm=='min_gru' else set()),
                    'unexpected/missing trained tensors')
            require(weights['structure.projection'].dtype == torch.int64 and
                    bool((weights['structure.projection'] == Q).all()), 'native projection not identity')
            with torch.no_grad():
                for name,p in model.named_parameters():
                    key = 'head.'+name.split('.',1)[1] if name.startswith('head.') else 'temporal.'+name
                    raw = weights[key]
                    require(raw.shape == p.shape and
                            raw.dtype == (torch.float32 if name.startswith('head.') else torch.int64),
                            'trained tensor geometry/dtype mismatch')
                    p.copy_((raw if name.startswith('head.') else raw.float()/Q))
                model.eval()
                for group in groups:
                    x = torch.tensor([r['feature_q24'] for r in group],dtype=torch.float32)/Q
                    tm = [int(utc(r['event_time_utc']).timestamp()*1000000) for r in group]
                    logits = model(x,tm)
                    require(bool(torch.isfinite(logits).all()), 'nonfinite model prediction')
                    p = torch.sigmoid(logits)
                    for r,value in zip(group,p):
                        out[r['case_id']]['candidates'][f'{cap}:{arm}'] = int(round(float(value)*1000000))
    result = {'schema':SEAL_SCHEMA, 'train_receipt_sha256':args.receipt_sha256,
              'future_source_sha256':future_sha,'owner_predictions_sha256':base_sha,
              'encoder_digest_claimed':receipt['encoder_digest_claimed'],
              'cell_id':receipt['cell_id'],'training_cutoff_utc':receipt['training_cutoff_utc'],
              'model_sha256':{f'{cap}:{arm}':models[(cap,arm)]['weight_sha256']
                              for cap in CAPS for arm in ARMS},
              'frozen_v1_artifact_sha256':receipt['no_change_v1_selected_sha256'],
              'sealed_at_utc_untrusted_local_clock':now_utc(),
              'rows':[out[k] for k in sorted(out)],
              'native_q24_parity_verified':False,'trusted_owner_precommit_verified':False,
              'production_qualification':False, 'ndu_eligible':False, 'decision':'NO_PROMOTION'}
    path = Path(args.seal_output)
    payload = (json.dumps(result,sort_keys=True,indent=2)+'\n').encode()
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os,'O_NOFOLLOW',0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd,'wb') as dest:
        dest.write(payload)
        dest.flush()
        os.fsync(dest.fileno())
    return {'seal_sha256':sha_bytes(payload),'case_count':len(out),
            'verified_owner_signature':False,'production_qualification':False,'ndu_eligible':False}


def binary_metrics(pairs: list[tuple[int,int]]) -> dict:
    require(bool(pairs), 'empty metric cohort')
    error = sum((p-y*1000000)**2 for p,y in pairs)
    bins = [[0,0] for _ in range(10)]
    for p,y in pairs:
        k = min(9,p//100000)
        bins[k][0] += p
        bins[k][1] += y*1000000
    return {'brier_ppm':error/(len(pairs)*1000000),
            'ece_ppm':sum(abs(a-b) for a,b in bins)/len(pairs),
            'count':len(pairs)}


def score(args: argparse.Namespace) -> dict:
    seal_path = Path(args.seal_file)
    seal_sha = sha_file(seal_path,args.seal_sha256)
    seal_data = unique_json(seal_path.read_bytes())
    require(seal_data['schema'] == SEAL_SCHEMA and
            seal_data['ndu_eligible'] is False and
            seal_data['production_qualification'] is False, 'untrusted seal schema/authority')
    witness_key, fp = load_public_key(Path(args.witness_pubkey))
    witness = verify_signed(Path(args.signed_witness),witness_key,fp,WITNESS_SCHEMA)
    exact(witness, {'schema','seal_sha256','committed_at_utc','host_id','operation_id'}, 'witness')
    require(witness['seal_sha256'] == seal_sha and isinstance(witness['host_id'],str) and
            witness['host_id'] and isinstance(witness['operation_id'],str) and
            witness['operation_id'], 'witness does not bind forecast file/host')
    committed = utc(witness['committed_at_utc'])
    # A newly signed assertion cannot establish historical trusted time; the
    # independently provisioned witness must own the actual precommit timestamp.
    require(committed >= utc(seal_data['sealed_at_utc_untrusted_local_clock']),
            'witness time predates actual local seal')
    outcome_key, outcome_fp = load_public_key(Path(args.outcome_pubkey))
    require(fp != outcome_fp, 'same key used for witness and outcome evaluator')
    outcome = verify_signed(Path(args.signed_outcomes),outcome_key,outcome_fp,OUTCOME_SCHEMA)
    exact(outcome, {'schema','cell_id','input_seal_sha256','rows'}, 'signed outcomes')
    require(outcome['cell_id'] == seal_data['cell_id'] and
            outcome['input_seal_sha256'] == seal_sha, 'wrong Cell/outcome seal')
    by_id = {}
    for row in outcome['rows']:
        exact(row, {'case_id','label','label_available_at_utc','source_group_sha256','partition'}, 'outcome row')
        ident = row['case_id']
        require(ident not in by_id and type(row['label']) is int and row['label'] in (0,1),
                'duplicate case or invalid observed binary outcome')
        require(utc(row['label_available_at_utc']) > committed,
                'post-outcome seal/label leakage')
        by_id[ident] = row
    sealed_cases = {x['case_id']:x for x in seal_data['rows']}
    require(len(sealed_cases) == len(seal_data['rows']) and set(by_id) == set(sealed_cases),
            'incomplete/duplicate paired outcome cohort')
    by_part = defaultdict(list)
    for ident,row in sealed_cases.items():
        truth = by_id[ident]
        require(truth['source_group_sha256'] == row['source_group_sha256'] and
                truth['partition'] == row['partition'], 'outcome provenance/split drift')
        require(utc(row['event_time_utc']) > utc(seal_data['training_cutoff_utc']) and
                utc(row['event_time_utc']) <= committed, 'impossible event/commit chronology')
        require(set(row['candidates']) == set(seal_data['model_sha256']), 'missing candidate probability')
        require(all(type(p) is int and 0 <= p <= 1000000 for p in row['candidates'].values()),
                'invalid candidate probability')
        by_part[row['partition']].append((row,truth['label']))
    require(set(by_part) == {'future','ood'}, 'missing future or OOD')
    results = {}
    for part, cases in sorted(by_part.items()):
        base = binary_metrics([(r['owner_v1_probability_ppm'],y) for r,y in cases])
        candidates = {}
        for model in sorted(seal_data['model_sha256']):
            cohort = [(r['candidates'][model],y) for r,y in cases]
            s = binary_metrics(cohort)
            s['brier_improvement_ppm'] = base['brier_ppm']-s['brier_ppm']
            s['false_acceptance_at_confidence_85pct'] = sum(
                (p>=850000 and not y) or (p<=150000 and bool(y)) for p,y in cohort)/len(cohort)
            candidates[model] = s
        results[part] = {'owner_v1':base,'candidates':candidates}
    return {'schema':'hepta.neuron.paired-sealed-future-diagnostics.v1',
            'seal_sha256':seal_sha,'witness_public_key_fingerprint':fp,
            'outcome_public_key_fingerprint':outcome_fp,
            'chronology_consistent_with_signed_claims':True,
            'trusted_host_time_independently_proven':False,
            'native_q24_parity_verified':False,'negative_transfer_causal_verified':False,
            'ndu_eligible':False,'production_qualification':False,
            'decision':'NO_PRODUCTION_PROMOTION','partitions':results}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='cmd',required=True)
    a = sub.add_parser('seal')
    for x in ('trained-root','receipt-sha256','future-features','future-sha256',
              'frozen-v1-predictions','frozen-v1-predictions-sha256','seal-output'):
        a.add_argument('--'+x,required=True)
    b = sub.add_parser('score')
    for x in ('seal-file','seal-sha256','signed-witness','witness-pubkey',
              'signed-outcomes','outcome-pubkey'):
        b.add_argument('--'+x,required=True)
    b.add_argument('--report',required=True)
    args = p.parse_args()
    try:
        result = seal(args) if args.cmd == 'seal' else score(args)
        if args.cmd == 'score':
            dest = Path(args.report)
            with dest.open('x',encoding='utf-8') as handle:
                json.dump(result,handle,indent=2,sort_keys=True)
                handle.write('\n')
                handle.flush()
                os.fsync(handle.fileno())
        print(json.dumps(result,sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, ImportError, RuntimeError) as exc:
        print(json.dumps({'status':'BLOCKED_SEALED_FUTURE','error':str(exc)}),file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
