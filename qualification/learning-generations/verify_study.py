#!/usr/bin/env python3
"""Replay raw material, signatures, arithmetic and exported native learned means.

This is an independent audit implementation of the bounded task, not an issuer.
It cannot establish external administrative independence or production authority.
"""
import hashlib
import itertools
import json
import math
from pathlib import Path
import struct
import sys
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ROLES = ('generator', 'evaluator', 'observer', 'selector', 'publisher', 'trust-root', 'future-custodian')
QUERIES = ('bootstrap', 'familyalpha', 'familybeta', 'familygamma')
OPERATIONS = {'add', 'subtract', 'multiply', 'xor'}
STRATA = {'generator': {'a_modulus':2, 'a_residue':1},
          'evaluator': {'a_modulus':4, 'a_residue':0},
          'future-custodian': {'a_modulus':4, 'a_residue':2}}
JSON_LIMIT = 8 * 1024 * 1024
RECORD_LIMIT = 16384


def need(condition, message):
    if not condition:
        raise ValueError(message)


def bounded(path, maximum=JSON_LIMIT):
    path = Path(path)
    need(path.is_file() and not path.is_symlink() and path.resolve() == path,
         'bounded canonical regular material required')
    with path.open('rb') as handle:
        raw = handle.read(maximum + 1)
    need(0 < len(raw) <= maximum, 'material byte bound')
    return raw


def load(path, maximum=JSON_LIMIT):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            need(key not in value, 'duplicate JSON field')
            value[key] = item
        return value
    return json.loads(bounded(path, maximum), object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON value')))


def integer(value, message, minimum=0):
    need(type(value) is int and minimum <= value < 2**64, message)
    return value


def hex_bytes(value, size):
    need(type(value) is str and len(value) == 2 * size
         and all(char in '0123456789abcdef' for char in value), 'canonical hex material')
    return bytes.fromhex(value)


def separated_roles(profile):
    rows = profile['keys']
    need(len(rows) == 7 and {row['role'] for row in rows} == set(ROLES), 'exact role set')
    need(len({row['role'] for row in rows}) == len({row['pid'] for row in rows})
         == len({row['public_key'] for row in rows}) == 7, 'role process/key separation')
    for row in rows:
        integer(row['pid'], 'role PID', 1)
        hex_bytes(row['public_key'], 32)
    return {row['role']: row for row in rows}


def window_interval(body, commitment):
    start = integer(body['starts_unix_micros'], 'future start', 1)
    end = integer(body['ends_unix_micros'], 'future end', 1)
    need(commitment['observed_unix_micros'] < start < end, 'future generation chronology')
    need(body['choices'] == commitment['body']['choices']
         and body['parent_choices'] == commitment['body']['parent_choices'], 'frozen prediction substitution')
    return start, end


def choice_table(cells, actions, queries):
    ordered = list(actions)
    value = {}
    for query in queries:
        sensor = 'query-' + sha(query.encode())
        present = [(cells[(sensor, action)][1], -index, actions[action])
                   for index, action in enumerate(ordered) if (sensor, action) in cells]
        need(not present or len(present) == len(ordered), 'partial native action grid')
        value[query] = max(present)[2] if present else actions[ordered[0]]
    return value


def durable_revoke(folder, owner, artifact, publisher):
    """Check explicit native v2 journal bytes; never manufacture a ledger receipt."""
    record = load(folder/'revocation.json')
    payload = bytes.fromhex(record['signed_current_bytes'])
    signature = hex_bytes(record['signature'], 64)
    publisher.verify(signature, payload)
    raw = bounded(owner/'transactions'/f'{sha(b"study-revoke")}-4.checkpoint', 16384)
    fields = raw.decode().splitlines()
    need(len(fields) == 18 and fields[0] == 'HEPTA-ARTIFACT-REVOCATION-CHECKPOINT-V2'
         and fields[1:3] == ['study-revoke', '4'] and fields[4] == '0'*64
         and fields[13:16] == ['study-revoke', artifact, 'publisher']
         and fields[17] == sha(payload + signature), 'actual acknowledged native Revoke required')
    unsigned = fields.copy(); unsigned[8] = '0'*64
    need(sha(b'hepta.learning-artifacts.revocation-state.v2' + ('\n'.join(unsigned)+'\n').encode()) == fields[8]
         and raw == ('\n'.join(fields)+'\n').encode(), 'native revocation journal changed')
    namespace = load(owner/'study-namespace.json')
    registry = fields[10].split(','); witness = fields[11].split(',')
    need(len(registry) == 5 and len(witness) == 4 and fields[5] == namespace['scope_digest'], 'revocation namespace')
    receipt = record['receipt']
    need(receipt == dict(operation_id='study-revoke', event_id='study-revoke', artifact_id=artifact,
         evaluator_id='publisher', reason_digest=fields[16], registry_head_digest=registry[1],
         witness_digest=witness[1], state_digest=fields[8], acknowledged_at=int(fields[12])),
         'structured native revocation receipt')
    snapshot = bounded(owner/'registries'/f'{registry[1]}-{registry[2]}.snapshot', 8*1024*1024)
    need(sha(snapshot) == registry[2] and len(snapshot) == int(registry[4]), 'revocation registry material')
    heads = list((owner/'heads').glob('*.head'))
    need(0 < len(heads) <= 1024, 'bounded revocation heads')
    matches = []
    for path in heads:
        values = bounded(path, 16384).decode().splitlines()
        if len(values) == 13 and values[12] == record['signature']:
            matches.append(values)
    need(len(matches) == 1, 'revocation signed CURRENT required')
    head = matches[0]
    push_id = lambda value: len(value.encode()).to_bytes(8, 'big') + value.encode()
    native = (b'hepta.learning-artifacts.current-head.v1' + hex_bytes(head[1], 32) + hex_bytes(head[2], 32)
              + push_id(head[3]) + int(head[4]).to_bytes(8, 'big') + hex_bytes(head[5], 32)
              + hex_bytes(head[6], 32) + int(head[7]).to_bytes(8, 'big') + push_id(head[8])
              + hex_bytes(head[9], 32) + int(head[10]).to_bytes(8, 'big') + int(head[11]).to_bytes(8, 'big'))
    need(head[0] == 'HEPTA-ARTIFACT-CURRENT-HEAD-V1' and head[3] == namespace['registry_id']
         and head[5] == registry[1] and head[6] == fields[7] and head[8] == 'publisher'
         and native == payload, 'revocation source/head binding')
    witness_raw = bounded(owner/'witnesses'/f'{head[4]}-{witness[1]}.witness', 16384)
    need(sha(witness_raw) == witness[2] and len(witness_raw) == int(witness[3]), 'revocation witness material')


def remap_material(root, original):
    original_root = Path(load(root/'artifact-owner/study-namespace.json')['root']).parent
    original = Path(original)
    need(original.is_absolute() and original.is_relative_to(original_root), 'product material outside evidence')
    return root/original.relative_to(original_root)


def sealed_holdout(root, folder, name, candidate, windows, commitments, materials, releases, native_signatures):
    raw = bounded(folder/f'{name}-holdout-material.json', 4*1024*1024)
    manifest = load(folder/f'{name}-holdout-material.json', 4*1024*1024)
    frozen = load(folder/f'{name}-frozen-plan.json')
    reservation = load(folder/f'{name}-holdout-anchor.json')
    anchor = reservation['anchor']
    need(manifest['schema'] == 'hepta.local-sealed-holdout-material.v1'
         and manifest['name'] == name and manifest['candidate'] == candidate
         and manifest['instances_per_family_per_custodian'] == 2048
         and len(manifest['materials']) == 2, 'exact sealed holdout manifest')
    need(frozen['candidate'] == candidate and frozen['holdout_material_digest'] == sha(raw)
         and anchor['holdout_digest'] == sha(raw) and anchor['plan_digest'] == frozen['digest'],
         'sealed holdout/native consumption binding')
    need(native_signatures['observer'].get(reservation['signature']) == canonical(anchor),
         'actual observer-signed native reservation required')
    for index, (entry, window) in enumerate(zip(manifest['materials'], windows), 1):
        who = 'evaluator' if index == 1 else 'future-custodian'
        window_name = f'{name}-window-{index}'
        body = entry['body']; rows = window['body']['tasks']
        commitment = commitments[window_name]
        need(entry == materials[window_name] and entry['role'] == who
             and body['name'] == window_name and body['candidate_sha256'] == candidate
             and body['generation'] == manifest['generation'] == window['body']['generation']
             and body['commitment'] == sha(canonical(commitment))
             and body['operand_stratum'] == STRATA[who], 'signed sealed material source')
        need(body['sealed_filename'] == window_name+'.sealed-tasks', 'sealed material filename')
        sealed_path = root/who/body['sealed_filename']
        sealed = bounded(sealed_path)
        need(sealed_path.stat().st_mode & 0o777 == 0o600
             and sealed == canonical(rows)+b'\n'
             and sha(sealed) == body['task_bytes_sha256'] and len(sealed) == body['task_bytes']
             and body['sample_count'] == len(rows) == 2048*(body['generation']+1)
             and body['task_ids'] == [row['id'] for row in rows], 'actual sealed task bytes/IDs')
        need(commitment['observed_unix_micros'] < entry['observed_unix_micros']
             < frozen['frozen_unix_micros'] < anchor['recorded_unix_micros']
             <= window['body']['starts_unix_micros'], 'sealed material freeze/reservation chronology')
        for record in (releases[window_name], window):
            need(record['body']['material_commitment'] == sha(canonical(entry))
                 and record['body']['reservation'] == reservation, 'release without exact durable reservation')
    return sha(raw)


def ips_interval(outputs, tasks, choices):
    """Independent fixed-2048 profile arithmetic, not a general OPE library."""
    count = len(tasks)
    matches = sum(row['logged_operation'] == choices[task['query']] for row, task in zip(outputs, tasks))
    rewards = sum(row['logged_correct'] and row['logged_operation'] == choices[task['query']]
                  for row, task in zip(outputs, tasks))
    need(count >= 4096 and matches >= 512, 'actual IPS row/ESS support')
    quotient, remainder = divmod(4*rewards*2**32, count)
    center = quotient + int(2*remainder > count or (2*remainder == count and quotient % 2))
    # Alpha=50000ppm, one comparison, one independently named task/cluster:
    # ceil(log2(ceil(6000000/50000)))=7. Integer sqrt/division round outward.
    numerator, denominator = (4*2**32)**2*7*count, 2*count*count
    squared = (numerator+denominator-1)//denominator
    floor = math.isqrt(squared)
    radius = floor+int(floor*floor < squared)+8
    return dict(lower=center-radius, upper=center+radius)


def product_decision(raw):
    """Decode public non-authorizing evidence bytes; never issue a runner seal."""
    need(0 < len(raw) <= 32768 and len(raw) >= 32, 'bounded actual product decision')
    body, checksum = raw[:-32], raw[-32:]
    need(checksum.hex() == sha(b'hepta.product-qualification-record.checksum.v1'+body),
         'product decision checksum')
    offset = 0
    def take(count):
        nonlocal offset
        chunk = body[offset:offset+count]
        need(len(chunk) == count, 'truncated product decision')
        offset += count
        return chunk
    def identifier():
        count = int.from_bytes(take(2), 'big')
        need(1 <= count <= 128, 'product decision ID bound')
        return take(count).decode()
    need(take(8) == b'HEPTQE01', 'native product decision format')
    digests = [take(32).hex() for _ in range(4)]
    need(all(value != '0'*64 for value in digests), 'native product decision digests')
    identities = [identifier() for _ in range(3)]
    disposition = take(1)[0]
    need(disposition in (0, 1, 2), 'native product disposition')
    count = int.from_bytes(take(2), 'big')
    need(count <= 128, 'native product failed metric bound')
    failed = [identifier() for _ in range(count)]
    need(failed == sorted(set(failed)) and take(1) == b'\0' and offset == len(body),
         'native product evidence cannot grant authority or hide trailing data')
    return dict(execution_digest=digests[0], evidence_digest=digests[1], trust_digest=digests[2],
                authentication_digest=digests[3], evaluation_id=identities[0], candidate_id=identities[1],
                baseline_id=identities[2], disposition=disposition, failed_metrics=failed)


def native_evidence_bytes(evidence):
    identifier = lambda value: len(value.encode()).to_bytes(8, 'big')+value.encode()
    return (b'hepta.learning-ledger.signed-evidence.v1'+identifier(evidence['evidence_id'])
        +identifier(evidence['principal_id'])+bytes([{'generator':0, 'observer':1, 'evaluator':2,
            'credit_allocator':3, 'unlearning_authority':4, 'selector':5}[evidence['role']]])
        +b''.join(hex_bytes(evidence[field], 32) for field in ('trust_digest', 'scope_digest', 'objective_digest'))
        +b''.join(integer(evidence[field], 'native signature epoch/time').to_bytes(8, 'big')
            for field in ('authority_epoch', 'issued_at', 'expires_at'))+hex_bytes(evidence['payload_digest'], 32))


def validate_signed_product_material(folder, name, material, decision, frozen_digest, native_signatures, expected_selection):
    """Bind the actual public bytes to role signatures; do not reconstruct tokens."""
    identifier = lambda value: len(value.encode()).to_bytes(4, 'big')+value.encode()
    ids = lambda values, size=4: len(values).to_bytes(size, 'big')+b''.join(identifier(value) for value in values)
    principal = lambda value: (identifier(value['principal_id'])
        +b''.join(hex_bytes(value[field], 32) for field in ('credential_chain_digest', 'signing_key_digest', 'scope_digest'))
        +b''.join(integer(value[field], 'native principal epoch/time').to_bytes(8, 'big')
            for field in ('authority_epoch', 'authenticated_at', 'expires_at')))
    bundle, timing, evidence = material['evaluation_bundle'], material['longitudinal_time'], material['evaluation_evidence']
    reservation = load(folder/f'{name}-holdout-anchor.json')['anchor']
    def bundle_digest(disposition, failed):
        raw = (b'hepta.intelligence-eval.independent-decision.v1'
            +b''.join(identifier(bundle[field]) for field in ('evaluation_id', 'candidate_id', 'baseline_id'))
            +b'\1'+principal(bundle['generator'])+principal(bundle['evaluator'])+hex_bytes(frozen_digest, 32)
            +hex_bytes(reservation['use_digest'], 32)+b''.join(hex_bytes(bundle[field], 32) for field in
                ('objective_digest', 'dataset_digest', 'estimand_digest', 'estimate_receipt_digest',
                 'support_audit_digest', 'confidence_receipt_digest'))
            +len(bundle['retention_receipt_digests']).to_bytes(4, 'big')
            +b''.join(hex_bytes(value, 32) for value in bundle['retention_receipt_digests'])
            +hex_bytes(bundle['unlearning_receipt_digest'], 32)+ids(bundle['snapshot_ids'])+ids(bundle['future_window_ids'])
            +bundle['family_alpha_ppm'].to_bytes(4, 'big')+bundle['simultaneous_comparisons'].to_bytes(4, 'big'))
        for metric in bundle['metrics']:
            raw += identifier(metric['metric_id'])+b'\0'
            raw += b''.join(metric[who][endpoint].to_bytes(8, 'big', signed=True)
                           for who in ('candidate', 'baseline') for endpoint in ('lower', 'upper'))
            raw += b'\0'+hex_bytes(metric['support_digest'], 32)
        return sha(raw+bytes([disposition])+ids(failed))
    need(bundle['claim_scope'] == 'system_longitudinal' and bundle['family_alpha_ppm'] == 50000
         and bundle['simultaneous_comparisons'] == 1
         and decision['evidence_digest'] == bundle_digest(decision['disposition'], decision['failed_metrics']),
         'public product decision differs from actual bundle')
    observer_payload = (b'hepta.intelligence-eval.observed-future-windows.unix-micros.v1\0'
        +hex_bytes(frozen_digest, 32)+hex_bytes(bundle['dataset_digest'], 32)+hex_bytes(bundle['objective_digest'], 32)
        +material['policy']['minimum_future_window_micros'].to_bytes(8, 'big')
        +timing['frozen_unix_micros'].to_bytes(8, 'big')+len(timing['windows']).to_bytes(8, 'big'))
    for window in timing['windows']:
        for field in ('window_id', 'snapshot_id'):
            raw = window[field].encode(); observer_payload += len(raw).to_bytes(2, 'big')+raw
        observer_payload += b''.join(window[field].to_bytes(8, 'big') for field in
                                    ('starts_unix_micros', 'ends_unix_micros', 'observation_count'))
        observer_payload += hex_bytes(window['observed_source_cut'], 32)
    need(timing['observer']['payload_digest'] == sha(observer_payload), 'actual signed observer material')
    metric_id = identifier('future-task-success')
    legacy = bytes.fromhex(sha(b'hepta.intelligence-eval.metric-contract.v1'+(1).to_bytes(4, 'big')+metric_id+b'\0\0'))
    role_digest = bytes.fromhex(sha(b'hepta.intelligence-eval.metric-contract.v2'+legacy+metric_id+b'\0'+bytes(8)))
    evaluator_payload = (b'hepta.intelligence-eval.signed-request.v3\0'
        +b'hepta.intelligence-eval.signed-request.v2'+b'hepta.intelligence-eval.signed-request.v1'
        +len(bundle['metrics']).to_bytes(8, 'big')+bytes.fromhex(bundle_digest(2, []))+role_digest
        +observer_payload+native_evidence_bytes(timing['observer'])+hex_bytes(timing['observer']['signature'], 64))
    need(evidence['evaluator_bundle']['payload_digest'] == sha(evaluator_payload), 'actual signed evaluator bundle')
    authenticated = b'hepta.intelligence-eval.authenticated-decision.v1'+hex_bytes(decision['trust_digest'], 32)
    for row in (evidence['generator_plan'], evidence['evaluator_bundle']):
        authenticated += bytes.fromhex(sha(native_evidence_bytes(row)))+hex_bytes(row['signature'], 64)
    need(decision['authentication_digest'] == sha(bytes.fromhex(sha(authenticated))+hex_bytes(timing['observer']['signature'], 64)),
         'actual native decision authentication')
    context = material['product']['context']
    need(context['generator'] == bundle['generator'] and context['evaluator'] == bundle['evaluator']
         and context['retention_receipt_digests'] == bundle['retention_receipt_digests']
         and context['unlearning_receipt_digest'] == bundle['unlearning_receipt_digest'], 'product qualification context')
    publication = material['product']['qualification_evidence']['digest']
    qualification_digest = sha(b'hepta.intelligence-eval.product-qualification.v3'
        +b''.join(hex_bytes(value, 32) for value in (decision['execution_digest'], bundle['objective_digest'],
            bundle['dataset_digest'], decision['evidence_digest'], decision['trust_digest'],
            decision['authentication_digest'], publication))+identifier(bundle['candidate_id'])
        +principal(bundle['evaluator'])+principal(bundle['generator'])+b'\1'+ids(bundle['snapshot_ids'], 8)+b'\0\0')
    request = material['selection_request']; binding = material['product_candidate_binding_evidence']
    binding_payload = (b'hepta.intelligence-eval.product-candidate-binding.v1\0'
        +b''.join(identifier(request[field]) for field in ('selection_id', 'predecessor_id', 'candidate_id'))
        +request['predecessor_generation'].to_bytes(8, 'big')+request['candidate_generation'].to_bytes(8, 'big')
        +b''.join(hex_bytes(value, 32) for value in (request['predecessor_artifact_digest'], request['candidate_artifact_digest'],
            qualification_digest, publication, decision['execution_digest'], bundle['dataset_digest'],
            bundle['objective_digest'], decision['trust_digest'], decision['authentication_digest'])))
    need(binding['principal_id'] == 'evaluator' and binding['role'] == 'evaluator'
         and binding['payload_digest'] == sha(binding_payload)
         and native_signatures['evaluator'].get(binding['signature']) == native_evidence_bytes(binding),
         'actual signed candidate/predecessor product byte binding')
    controls = load(folder/'canonical-qualification-controls.json')
    need(controls['qualification_evidence_digest'] == qualification_digest
         and controls['qualification_publication_digest'] == publication
         and controls['signed_metric_compatibility_eligible'] is True
         and controls['canonical_metric_substitution_error'] == 'BindingMismatch'
         and controls['compatibility_cannot_claim_product_qualification'] is True, 'actual canonical qualifier controls')
    need(len(controls['seal_denials']) == len(controls['byte_binding_denials']) == 2
         and {row['control'] for row in controls['seal_denials']} == {'publication', 'qualification-evidence'}
         and all('Integrity' in row['error'] for row in controls['seal_denials'])
         and {row['control'] for row in controls['byte_binding_denials']} == {'candidate', 'predecessor'}
         and all('PayloadMismatch' in row['error'] for row in controls['byte_binding_denials']), 'actual seal/byte controls')
    if name == 'no-update':
        need(expected_selection is None, 'no-update cannot acquire selector authority')
        return
    lifetime = controls['binding_lifetime']
    need(lifetime['prepared_during_binding_validity'] is True and lifetime['early_admission_succeeded'] is True
         and lifetime['delayed_verification_at'] == lifetime['binding_expires_at']+1
         and 'ValidityWindow' in lifetime['late_admission_error']
         and lifetime['early_token_revalidation_refused'] is True, 'actual short binding expiry control')
    need(load(folder/'compatibility-install-rejection.json')['error'] == 'CanonicalQualificationRequired',
         'raw compatibility token installed as published product')
    selected = load(folder/'evaluation-materials.json'); selector = selected['selector_evidence']
    need({key:value for key,value in selected.items() if key != 'selector_evidence'} == material,
         'selected native source differs from original evaluation')
    policy, dataset = material['policy'], material['dataset_receipt']['snapshot']
    payload = (b'hepta.intelligence-eval.self-evolution-selection.v2\0'
        +b''.join(identifier(value) for value in (request['selection_id'], request['predecessor_id'],
            request['candidate_id'], policy['no_change_baseline_id']))
        +request['predecessor_generation'].to_bytes(8, 'big')+request['candidate_generation'].to_bytes(8, 'big')
        +b''.join(hex_bytes(value, 32) for value in (bundle['objective_digest'], request['predecessor_artifact_digest'],
            request['candidate_artifact_digest'], policy['no_change_baseline_digest'], bundle['dataset_digest'],
            dataset['ledger_head_digest'], decision['evidence_digest'], decision['authentication_digest'], decision['trust_digest'], frozen_digest))
        +policy['minimum_dataset_records'].to_bytes(4, 'big')+policy['minimum_future_window_micros'].to_bytes(8, 'big')
        +b''.join(hex_bytes(value, 32) for value in (qualification_digest, publication, decision['execution_digest'],
            sha(native_evidence_bytes(binding)+hex_bytes(binding['signature'], 64)))))
    need(selector['principal_id'] == 'selector' and selector['role'] == 'selector'
         and selector['payload_digest'] == sha(payload)
         and native_signatures['selector'].get(selector['signature']) == native_evidence_bytes(selector), 'actual independent selector binding')
    need(expected_selection == sha(b'hepta.intelligence-eval.self-evolution-selection-receipt.v1\0'+payload
         +bytes.fromhex(sha(native_evidence_bytes(selector)))+hex_bytes(selector['signature'], 64)), 'actual selected receipt changed')


def frozen_product_digest(material):
    """Recompute the public native plan preimage for this one frozen metric."""
    def identifier(value):
        raw = value.encode()
        need(1 <= len(raw) <= 128, 'native plan ID bound')
        return len(raw).to_bytes(4, 'big')+raw
    def number(value, size=8, signed=False):
        need(type(value) is int, 'native plan integer')
        return value.to_bytes(size, 'big', signed=signed)
    def temporal(plan):
        fold, ope, confidence = plan['fold'], plan['ope'], plan['confidence']
        raw = (b'hepta.ope.temporal-evaluation-plan.v1'+identifier(plan['evaluation_id'])
            +hex_bytes(plan['objective_digest'], 32)+hex_bytes(fold['plan_digest'], 32)
            +identifier(fold['fold_id'])+b''.join(number(fold[field]) for field in
                ('training_watermark', 'evaluation_start', 'minimum_per_action'))
            +hex_bytes(ope['plan_digest'], 32)+number(ope['outcome_watermark'])+number(ope['minimum_rows'])
            +number(ope['minimum_ess'], signed=True)+number(ope['maximum_weight'], signed=True)
            +hex_bytes(confidence['plan_digest'], 32)+hex_bytes(confidence['assumptions_digest'], 32)
            +number(confidence['family_alpha_ppm'], 4)+number(confidence['simultaneous_comparisons'], 4)
            +number(confidence['minimum_clusters']))
        need(plan['plan_digest'] == sha(raw), 'native temporal plan digest')
        return hex_bytes(plan['plan_digest'], 32)
    plan, product = material['frozen_plan'], material['product']
    need(plan['claim_scope'] == 'system_longitudinal'
         and plan['metric_contracts'] == [dict(metric_id='future-task-success', direction='maximize', safety_floor=None)]
         and material['metric_roles'] == [dict(metric_id='future-task-success',
             role=dict(primary_superiority=dict(minimum_improvement=0)))], 'frozen primary metric contract')
    metric_id = identifier('future-task-success')
    legacy = bytes.fromhex(sha(b'hepta.intelligence-eval.metric-contract.v1'+number(1, 4)+metric_id+b'\0\0'))
    role_digest = bytes.fromhex(sha(b'hepta.intelligence-eval.metric-contract.v2'+legacy+metric_id+b'\0'+number(0, signed=True)))
    estimand = bytes.fromhex(sha(b'hepta.intelligence-eval.product-estimand.v1'
        +hex_bytes(plan['estimand_digest'], 32)+temporal(product['candidate_plan'])
        +temporal(product['baseline_plan'])+metric_id+b'\0'))
    raw = b'hepta.intelligence-eval.cross-fold-plan.v2'+b''.join(identifier(plan[field]) for field in
        ('plan_id', 'candidate_id', 'baseline_id', 'final_holdout_window_id'))+b'\1'
    raw += (hex_bytes(plan['objective_digest'], 32)+hex_bytes(plan['dataset_digest'], 32)
        +estimand+legacy+hex_bytes(plan['final_holdout_digest'], 32)
        +number(plan['family_alpha_ppm'], 4)+number(plan['simultaneous_comparisons'], 4)+number(len(plan['folds']), 4))
    for fold in sorted(plan['folds'], key=lambda value: value['fold_id']):
        raw += identifier(fold['fold_id'])
        for field in ('training_principals', 'training_episodes', 'training_windows',
                      'holdout_principals', 'holdout_episodes', 'holdout_windows'):
            values = sorted(fold[field])
            need(values and len(values) == len(set(values)), 'native frozen lineage census')
            raw += number(len(values), 4)+b''.join(identifier(value) for value in values)
        raw += hex_bytes(fold['model_digest'], 32)+hex_bytes(fold['predictions_digest'], 32)
    return sha(b'hepta.intelligence-eval.cross-fold-plan.v3'+bytes.fromhex(sha(raw))+role_digest)


def product_inputs(root, folder, name, material, final_window, training, predictions, parent_predictions, profile_operations):
    product = material['product']
    expected_paths = {'released_inputs': folder/'product-released-inputs.json',
                      'holdout_material': folder/f'{name}-holdout-material.json',
                      'qualification_evidence': folder/'product-qualification.evidence'}
    for field, path in expected_paths.items():
        need(remap_material(root, product[field]['path']) == path
             and sha(bounded(path, 32*1024*1024)) == product[field]['digest'], 'pinned product material bytes')
    inputs = load(expected_paths['released_inputs'], 32*1024*1024)
    tasks, outputs = final_window['body']['tasks'], final_window['body']['outputs']
    need(len(tasks) == len(outputs) and final_window['role'] == 'future-custodian', 'strict final custodian cohort')
    # This exact signed material is common to every row in this final cohort.
    # Hash it once; all per-row outcome/action/source comparisons remain exact.
    final_source_digest = sha(canonical(final_window))
    action = lambda query, operation: 'task-action-'+sha(f'{query}:{operation}'.encode())
    operations = ['add', 'multiply', 'xor', 'subtract']
    targets, assignments, candidate_rows, parent_rows = [], [], [], []
    for task, output in zip(tasks, outputs):
        need(output['task'] == task['id'], 'logged task/output order')
        decision, lineage = 'future-'+task['id'], 'synthetic-task-'+task['id']
        targets.append(dict(decision_id=decision, principal_lineage=lineage, episode_lineage=lineage,
                            window_id=f'{name}-window-2', decision_at=output['decision_at'],
                            actions=[action(task['query'], operation) for operation in operations]))
        assignments.append(dict(decision_id=decision, cluster_id=lineage))
        for choices, destination in ((predictions, candidate_rows), (parent_predictions, parent_rows)):
            destination.append(dict(decision_id=decision, chosen_action=action(task['query'], output['logged_operation']),
                complete_candidates=True, actions=[dict(action_id=action(task['query'], operation),
                behavior_probability=2**30, evaluation_probability=2**32 if choices[task['query']] == operation else 0,
                predicted_outcome=0) for operation in operations],
                finalized_outcome=int(output['logged_correct'])*2**32,
                outcome_observed_at=output['outcome_observed_at'], outcome_evidence=final_source_digest,
                outcome_model_evidence='0'*64))
    need(inputs['targets'] == targets and inputs['assignments'] == assignments
         and inputs['candidate_observations'] == candidate_rows
         and inputs['baseline_observations'] == parent_rows, 'raw product rows differ from actual logged final outcomes')
    need(inputs['snapshot_ids'] == [material['dataset_receipt']['snapshot']['snapshot_id'],
         f'{name}-snapshot-1', f'{name}-snapshot-2']
         and inputs['future_window_ids'] == [f'{name}-window-1', f'{name}-window-2'], 'product source census')
    generation = 4 if name == 'no-update' else int(name.split('-')[-1])
    native_training = inputs['training']
    need(len(native_training) == len(training)*4, 'actual product training census')
    source_events = set(material['dataset_receipt']['snapshot']['source_record_digests'])
    for task_index, task in enumerate(training):
        for action_index, operation in enumerate(profile_operations):
            row = native_training[task_index*4+action_index]
            episode = f'g{generation}-t{task_index}-a{action_index}'
            need(row['decision_id'] == episode+'-decision' and row['episode_lineage'] == episode
                 and row['principal_lineage'] == 'generator-training'
                 and row['window_id'] == f'generation-{generation}-training'
                 and row['action_id'] == action(task['query'], operation)
                 and row['outcome'] == int(calculate(operation, task['a'], task['b']) == task['expected'])*2**32
                 and row['evidence_digest'] in source_events, 'actual training outcome/source projection')
            integer(row['observed_at'], 'actual training clock', 1)
    for field in ('candidate_plan', 'baseline_plan'):
        plan = product[field]
        need(plan['fold']['minimum_per_action'] == 8
             and plan['fold']['training_watermark'] == max(row['observed_at'] for row in native_training)
             and plan['fold']['training_watermark'] < plan['fold']['evaluation_start']
             <= min(row['decision_at'] for row in outputs), 'actual temporal plan freeze')
        need(plan['ope']['minimum_rows'] == 4096 and plan['ope']['minimum_ess'] == 512*2**32
             and plan['ope']['maximum_weight'] == 4*2**32
             and plan['ope']['outcome_watermark'] == plan['fold']['evaluation_start']+600_000_000
             and max(row['outcome_observed_at'] for row in outputs) <= plan['ope']['outcome_watermark'], 'prespecified OPE support')
        need(plan['confidence']['family_alpha_ppm'] == 50000
             and plan['confidence']['simultaneous_comparisons'] == 1
             and plan['confidence']['minimum_clusters'] == 4096
             and plan['confidence']['assumptions_digest'] == sha(b'synthetic-CS-random-operands-generator-a-odd-evaluator-a-mod4-0-final-a-mod4-2-uniform-logged-four-action-fixed-2048-per-family-v1'),
             'prespecified statistical contract')
    need(material['frozen_plan']['estimand_digest'] == sha(b'final-future-custodian-a-mod4-equals2-uniform-family-correctness-v1'),
         'prespecified final population')
    frozen_digest = frozen_product_digest(material)
    frozen = load(folder/f'{name}-frozen-plan.json')
    need(frozen_digest == frozen['digest']
         and material['evaluation_evidence']['generator_plan']['payload_digest'] == sha(bytes.fromhex(frozen_digest)),
         'actual generator signature does not bind the frozen product plan')
    need(product['metric_sources'] == [dict(metric_id='future-task-success', source='ips')]
         and len(material['evaluation_bundle']['metrics']) == 1, 'exact product IPS metric source')
    metric = material['evaluation_bundle']['metrics'][0]
    need(metric['metric_id'] == 'future-task-success' and metric['direction'] == 'maximize'
         and metric['safety_floor'] is None
         and metric['candidate'] == ips_interval(outputs, tasks, predictions)
         and metric['baseline'] == ips_interval(outputs, tasks, parent_predictions), 'actual native IPS intervals')
    decision = product_decision(bounded(expected_paths['qualification_evidence'], 32768))
    selection = material['selection_request']
    need(decision['evaluation_id'] == f'{name}-plan'
         and decision['candidate_id'] == selection['candidate_id']
         and decision['baseline_id'] == selection['predecessor_id']
         and decision['trust_digest'] == material['evaluation_evidence']['evaluator_bundle']['trust_digest']
         and decision['disposition'] == (1 if name == 'no-update' else 0)
         and decision['failed_metrics'] == (['future-task-success'] if name == 'no-update' else []),
         'actual canonical product terminal outcome')
    return decision, frozen_digest


def material_bindings(root, folder, name, candidate, parent, predictions, parent_predictions, evaluations, observed,
                      roles, native_signatures, commitments, materials, releases, training, operations, expected_selection):
    material = load(folder/f'{name}-evaluation-inputs.json')
    bundle, timing = material['evaluation_bundle'], material['longitudinal_time']
    windows = [evaluations[f'{name}-window-{i}'] for i in (1, 2)]
    digest = sha(canonical(windows))
    need(bundle['retention_receipt_digests'] == [digest], 'actual retention material binding')
    for field in ('estimate_receipt_digest', 'support_audit_digest', 'confidence_receipt_digest'):
        need(bundle[field] != '0'*64, 'actual runner receipt digest required'); hex_bytes(bundle[field], 32)
    need(bundle['unlearning_receipt_digest'] == sha(bounded(folder/'withdrawal-control/observed.json')),
         'actual withdrawal material binding')
    selection = material['selection_request']
    need(selection['candidate_artifact_digest'] == candidate and selection['predecessor_artifact_digest'] == parent,
         'actual selection model binding')
    need(len(material['frozen_plan']['folds']) == 2 and len(timing['windows']) == 2, 'actual two folds required')
    holdout_digest = sealed_holdout(root, folder, name, candidate, windows, commitments, materials, releases, native_signatures)
    need(material['frozen_plan']['final_holdout_digest'] == holdout_digest
         and material['product']['holdout_material']['digest'] == holdout_digest, 'native holdout material differs')
    for i, window in enumerate(windows):
        receipt = observed[f'{name}-window-{i+1}']
        body = window['body']
        need(window['role'] == ('evaluator' if i == 0 else 'future-custodian')
             and body['choices'] == predictions and body['parent_choices'] == parent_predictions,
             'independent frozen future predictions')
        facts = receipt['record']['body']
        need(facts['source_sha256'] == sha(canonical(window)) and facts['custody_role'] == window['role']
             and facts['counts'] == body['counts'] and facts['sample_count'] == body['sample_count'], 'independent future observer binding')
        pinned = timing['windows'][i]
        need(pinned['starts_unix_micros'] == body['starts_unix_micros']
             and pinned['ends_unix_micros'] == body['ends_unix_micros']
             and timing['frozen_unix_micros'] < body['starts_unix_micros']
             and pinned['observed_source_cut'] == sha(canonical(receipt['record']))
             and pinned['observation_count'] == body['sample_count'], 'native future chronology/source binding')
        fold = material['frozen_plan']['folds'][i]
        need(fold['model_digest'] == candidate and fold['predictions_digest'] == sha(canonical(predictions)), 'native frozen model binding')
        lineages = ['synthetic-task-'+task['id'] for task in body['tasks']]
        need(fold['holdout_principals'] == lineages and fold['holdout_episodes'] == lineages
             and fold['holdout_windows'] == [body['name']], 'actual frozen holdout task lineages')
    signers = material['trust']['signers']
    need(len(signers) == 4 and {row['principal']['principal_id'] for row in signers} == set(ROLES[:4]), 'native four-role trust')
    for signer in signers:
        who = signer['principal']['principal_id']; profile = roles[who]
        need(signer['verifying_key'] == profile['public_key'] and signer['roles'] == [who]
             and signer['principal']['signing_key_digest'] == sha(hex_bytes(profile['public_key'], 32))
             and signer['principal']['credential_chain_digest'] == sha(f'local-process-credential-{profile["pid"]}'.encode())
             and signer['controller_id'] == f'local-role-process-{profile["pid"]}', 'native role/controller binding')
    for who, evidence in [('generator', material['evaluation_evidence']['generator_plan']),
                          ('evaluator', material['evaluation_evidence']['evaluator_bundle']),
                          ('observer', timing['observer'])]:
        need(evidence['principal_id'] == who and evidence['role'] == who
             and native_signatures[who].get(evidence['signature']) == native_evidence_bytes(evidence), 'native issued signature required')
    decision, frozen_digest = product_inputs(root, folder, name, material, windows[1], training, predictions, parent_predictions, operations)
    validate_signed_product_material(folder, name, material, decision, frozen_digest, native_signatures, expected_selection)
    return material


def cost_receipt(root, summary, completed, profile):
    receipt = load(root.with_suffix('.execution.json'))
    need(receipt['schema'] == 'hepta.local-learning-whole-process-cost.v1'
         and receipt['native_exit_code'] == 0 and receipt['binary_unchanged'] is True,
         'actual successful native execution required')
    hex_bytes(receipt['binary_sha256'], 32)
    frozen_source = root.with_suffix('.custodian.py')
    original_root = Path(load(root/'artifact-owner/study-namespace.json')['root']).parent
    need(Path(receipt['custodian_source']) == original_root.with_suffix('.custodian.py')
         and receipt['custodian_sha256'] == profile['custodian_sha256'] == sha(bounded(frozen_source)),
         'actual frozen custodian source required')
    need(receipt['command'][1:] == ['--exact',
         'cognitive_ranker::tests::three_generation_learning::three_actual_fits_installations_future_instances_no_update_and_revocation',
         '--ignored', '--nocapture', '--test-threads=1'], 'exact native selector required')
    need(receipt['compilation_included'] is False and receipt['energy_cost'] is None
         and receipt['monetary_cost'] is None, 'cost scope promotion')
    need(receipt['memory_scope'] == 'maximum waited process high-water; simultaneous whole-tree RSS not measured',
         'unmeasured simultaneous process tree memory promoted')
    for field in ('wall_ns', 'observer_cpu_ns', 'waited_child_peak_rss_bytes'):
        integer(receipt[field], 'whole execution cost', 1)
    if receipt['sampled_native_peak_rss_bytes'] is not None:
        correction = load(root.with_suffix('.measurement-correction.json'))
        need(correction['schema'] == 'hepta.local-learning-measurement-correction.v1'
             and correction['affected_field'] == 'sampled_native_peak_rss_bytes'
             and correction['original_value'] == receipt['sampled_native_peak_rss_bytes']
             and correction['valid'] is False and correction['original_evidence_preserved'] is True,
             'unvalidated PID RSS cannot be claimed')
    else:
        need(receipt.get('rss_sampling_status', '').startswith('unavailable'), 'unvalidated PID RSS cannot be claimed')
    for field in ('child_user_seconds', 'child_system_seconds'):
        need(type(receipt[field]) in (int, float) and math.isfinite(receipt[field])
             and receipt[field] >= 0, 'unknown child CPU cost')
    need(receipt['child_user_seconds'] + receipt['child_system_seconds'] > 0, 'unknown child CPU cost')
    need(sha(bounded(root.with_suffix('.native.log'), 32 * 1024 * 1024)) == receipt['log_sha256'],
         'native execution log changed')
    files = list(itertools.islice(root.rglob('*'), 32769))
    need(len(files) <= 32768 and all(not path.is_symlink() for path in files), 'retained file bound/alias')
    regular = [path for path in files if path.is_file()]
    need(len(regular) == receipt['retained_files']
         and sum(path.stat().st_size for path in regular) == receipt['retained_bytes'], 'retained cost material changed')
    need(len(summary['role_process_costs']) == 7 and {row['role'] for row in summary['role_process_costs']} == set(ROLES),
         'complete role process costs')
    for row in summary['role_process_costs']:
        need(row == completed[row['role']], 'role cost differs from signed completed transcript')
        integer(row['body']['wall_ns'], 'role wall cost', 1)
        integer(row['body']['peak_rss_bytes'], 'role memory cost', 1)
        for field in ('cpu_user_seconds', 'cpu_system_seconds'):
            number = row['body'][field]
            need(type(number) in (int, float) and math.isfinite(number) and number >= 0, 'role CPU cost')
    return receipt


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def calculate(op, a, b):
    return {'add': lambda: a+b, 'subtract': lambda: a-b,
            'multiply': lambda: a*b, 'xor': lambda: a^b}[op]()


def model(raw):
    if raw[:8] != b'HEPTTB01':
        raise ValueError('native tabular format required')
    offset = 8
    def take(size):
        nonlocal offset
        value = raw[offset:offset+size]
        if len(value) != size:
            raise ValueError('truncated native payload')
        offset += size
        return value
    def identifier():
        return take(int.from_bytes(take(2), 'big')).decode()
    artifact, producer = identifier(), identifier()
    generation = int.from_bytes(take(8), 'big')
    take(5*32)
    count = int.from_bytes(take(4), 'big')
    if count > 16384:
        raise ValueError('study cell bound')
    cells = {}
    for _ in range(count):
        sensor, action = identifier(), identifier()
        samples = int.from_bytes(take(4), 'big')
        mean, low, high = struct.unpack('>qqq', take(24))
        take(32)
        if (sensor, action) in cells:
            raise ValueError('duplicate model cell')
        cells[(sensor, action)] = samples, mean, low, high
    if offset != len(raw):
        raise ValueError('trailing model bytes')
    return artifact, producer, generation, cells


def verify(root):
    root = Path(root).resolve(strict=True)
    profile = load(root/'profile.json')
    summary = load(root/'summary.json')
    need(profile['schema'] == summary['schema'] == 'hepta.local-three-generation-study.v1', 'exact study schema')
    role_rows = separated_roles(profile)
    operations, queries = profile['operations'], profile['query_families']
    need(len(operations) == 4 and set(operations) == OPERATIONS and tuple(queries) == QUERIES, 'bounded task profile')
    need(profile['operand_strata'] == STRATA
         and profile['final_estimation_population'] == 'future-custodian a modulo4 equals2; uniform family, b in3..100002; distinct from training stratum',
         'prespecified disjoint operand strata/population')
    for value in (profile, summary):
        for field in ('organizational_independence', 'general_neural_model_efficacy', 'full_service_startup',
                      'parameter_unlearning_proven', 'data_erasure_proven'):
            need(value[field] is False, 'unsupported promotion')
    hex_bytes(profile['custodian_sha256'], 32)
    keys = {row['role']: Ed25519PublicKey.from_public_bytes(bytes.fromhex(row['public_key'])) for row in profile['keys']}
    material_seen, commitments, evaluations, training, releases = set(), {}, {}, {}, {}
    material_commitments, release_records = {}, {}
    evaluation_records, future_observers, completed, intervals = {}, {}, {}, []
    native_signatures = {role: {} for role in ROLES}
    training_observers = {}
    for role, key in keys.items():
        previous, sequence = '0'*64, 0
        paths = sorted(itertools.islice((root/role).glob('*.json'), RECORD_LIMIT+1))
        need(0 < len(paths) <= RECORD_LIMIT, 'role transcript bound')
        for path in paths:
            raw = load(path)
            integer(raw['sequence'], 'role transcript sequence', 1)
            integer(raw['pid'], 'role transcript PID', 1)
            integer(raw['observed_unix_micros'], 'role observed clock', 1)
            signature = raw['signature']
            unsigned = {k:v for k,v in raw.items() if k != 'signature'}
            key.verify(bytes.fromhex(signature), canonical(unsigned))
            sequence += 1
            if raw['sequence'] != sequence or raw['previous'] != previous or raw['role'] != role \
                    or raw['pid'] != role_rows[role]['pid'] or path.name != f'{sequence:06}.json':
                raise ValueError('role transcript chain')
            previous = sha(canonical(raw))
            body = raw['body']
            if raw['kind'] == 'native-signature':
                payload = bytes.fromhex(body['payload_hex'])
                if sha(payload) != body['payload_sha256']:
                    raise ValueError('native signing bytes')
                key.verify(bytes.fromhex(body['signature']), payload)
                native_signatures[role][body['signature']] = payload
            if raw['kind'] == 'task-profile':
                need(sequence == 1 and body['queries'] == queries and body['operations'] == operations
                     and body['operand_strata'] == STRATA, 'signed immutable task profile')
            if raw['kind'] == 'completed-process':
                need(sequence == len(paths), 'role completion must close transcript')
                completed[role] = raw
            if raw['kind'] == 'actual-training-observation':
                need(role == 'observer', 'training observer role')
                identity = (body['task'], body['operation'])
                need(identity not in training_observers, 'training observation duplicate')
                training_observers[identity] = body
            if raw['kind'] == 'actual-future-observation':
                need(role == 'observer' and body['name'] not in future_observers, 'future observer role/duplicate')
                future_observers[body['name']] = {'record': raw}
            if raw['kind'] == 'candidate-commitment':
                need(role in ('evaluator', 'future-custodian') and body['name'] not in commitments, 'candidate commitment role/duplicate')
                commitments[body['name']] = raw
            if raw['kind'] == 'material-commitment':
                need(role in ('evaluator', 'future-custodian') and body['name'] not in material_commitments,
                     'material commitment role/duplicate')
                material_commitments[body['name']] = raw
            if raw['kind'] in ('training-release', 'future-release'):
                need(0 < len(body['tasks']) <= 8192, 'raw task bound')
                generation = body['generation'] if raw['kind'] == 'training-release' else commitments[body['name']]['body']['generation']
                integer(generation, 'task material generation')
                need(generation <= 3 and role in STRATA, 'task material role/generation')
                per_family = 8 if raw['kind'] == 'training-release' or body['name'].endswith('installed-consumer') else 2048
                family_counts = {query:0 for query in queries[:generation+1]}
                for task in body['tasks']:
                    need(integer(task['a'], 'raw operand', 3) <= 100002
                         and integer(task['b'], 'raw operand', 3) <= 100002, 'raw operand range')
                    stratum = STRATA[role]
                    need(task['a'] % stratum['a_modulus'] == stratum['a_residue'], 'task outside signed operand stratum')
                    need(task['query'] in family_counts, 'task outside frozen family census')
                    family_counts[task['query']] += 1
                    need(task['partition'] == (f'training-{generation}' if raw['kind'] == 'training-release' else body['name']),
                         'task material partition')
                    hex_bytes(task['nonce'], 16)
                    semantic = task['query'], task['a'], task['b']
                    if semantic in material_seen:
                        raise ValueError('task instance overlap across training/future windows')
                    material_seen.add(semantic)
                    if task['id'] != sha(canonical({k:v for k,v in task.items() if k != 'id'})):
                        raise ValueError('task commitment')
                    expected = calculate(operations[queries.index(task['query'])], task['a'], task['b'])
                    if type(task['expected']) is not int or expected != task['expected']:
                        raise ValueError('independent task result')
                    need(len({calculate(operation, task['a'], task['b']) for operation in operations}) == 4,
                         'undeclared action equivalence')
                need(all(count == per_family for count in family_counts.values()), 'fixed task family denominator')
                if raw['kind'] == 'training-release':
                    need(role == 'generator' and body['operand_stratum'] == STRATA[role], 'training release role')
                    training.setdefault(body['generation'], []).append(body['tasks'])
                else:
                    need(role in ('evaluator', 'future-custodian') and body['name'] not in releases, 'future release role/duplicate')
                    releases[body['name']] = body['tasks']
                    release_records[body['name']] = raw
                    commitment = commitments[body['name']]
                    if body['commitment'] != sha(canonical(commitment)) or raw['sequence'] <= commitment['sequence']:
                        raise ValueError('future release before durable candidate commitment')
            if raw['kind'] == 'actual-evaluation':
                need(role in ('evaluator', 'future-custodian') and body['name'] not in evaluations, 'evaluation role/duplicate')
                commitment = commitments[body['name']]
                intervals.append(window_interval(body, commitment))
                if body['tasks'] != releases[body['name']] or body['commitment'] != sha(canonical(commitment)):
                    raise ValueError('evaluated task release substitution')
                outputs = {row['task']:row for row in body['outputs']}
                need(len(body['outputs']) == len(outputs) == len(body['tasks']), 'actual output denominator')
                if body['name'].endswith('installed-consumer'):
                    need(body['material_commitment'] is None and body['reservation'] is None,
                         'consumer inference cannot count as reserved holdout')
                counts = {'candidate':0, 'parent':0}
                for task in body['tasks']:
                    observed = outputs[task['id']]
                    need(observed['logged_operation'] in OPERATIONS
                         and type(observed['logged_correct']) is bool
                         and observed['behavior_probability_q32'] == 2**30
                         and observed['logged_actual'] == calculate(observed['logged_operation'], task['a'], task['b'])
                         and observed['logged_correct'] == (observed['logged_actual'] == task['expected']),
                         'actual uniformly logged action/outcome')
                    decision = integer(observed['decision_at'], 'logged decision time', 1)
                    outcome = integer(observed['outcome_observed_at'], 'logged outcome time', 1)
                    need(body['starts_unix_micros'] <= decision <= outcome <= body['ends_unix_micros'],
                         'actual logged decision/outcome chronology')
                    for participant, field in [('candidate','choices'), ('parent','parent_choices')]:
                        actual = calculate(commitment['body'][field][task['query']], task['a'], task['b'])
                        correct = actual == task['expected']
                        if observed[participant] != actual or observed[f'{participant}_correct'] != correct:
                            raise ValueError('replayed actual inference outcome')
                        counts[participant] += correct
                if counts != body['counts'] or len(outputs) != body['sample_count']:
                    raise ValueError('actual score/count')
                radius = math.sqrt(math.log(160)/(2*len(body['tasks'])))
                score_intervals = {who:[max(0, math.floor((count/len(body['tasks'])-radius)*2**32)),
                    min(2**32, math.ceil((count/len(body['tasks'])+radius)*2**32))] for who,count in counts.items()}
                if score_intervals != body['intervals']:
                    raise ValueError('confidence interval differs from actual counts')
                evaluations[body['name']] = body
                evaluation_records[body['name']] = raw
    need(set(completed) == set(ROLES), 'completed role processes required')
    for left, right in zip(sorted(intervals), sorted(intervals)[1:]):
        need(left[1] <= right[0], 'future windows overlap')
    actions = {}
    for row in profile['actions']:
        item = row['item']
        encoded = (len(item['memory_id'].encode()).to_bytes(8,'big') + item['memory_id'].encode() +
                   item['revision'].to_bytes(8,'big') + item['content_sha256'].encode())
        actions['memory-'+sha(encoded)] = row['operation']
    need(len(actions) == 4 and list(actions.values()) == operations, 'actual action census/order')
    need({key: len(value) for key, value in training.items()} == {0: 1, 1: 1, 2: 1, 3: 2}, 'five actual training releases')
    models, predictions = [], []
    for index in range(5):
        folder = root/f'generation-{index}' if index < 4 else root/'no-update'
        raw = bounded(folder/'payload', 1024*1024)
        artifact, producer, generation, cells = model(raw)
        if artifact != f'learned-generation-{index}' or producer != 'generator' \
                or generation != index+1 or len(cells) != (min(index, 3)+1)*4:
            raise ValueError('native model generation/grid')
        rows_for_model = training[min(index, 3)][1 if index == 4 else 0]
        for (sensor, action), values in cells.items():
            query = next(query for query in queries if sensor == 'query-'+sha(query.encode()))
            rows = [row for row in rows_for_model if row['query'] == query]
            need(len(rows) == 8 and action in actions, 'actual complete training grid')
            rewards = [int(calculate(actions[action], row['a'], row['b']) == row['expected'])*2**32 for row in rows]
            for row in rows:
                observation = training_observers[(row['id'], actions[action])]
                actual = calculate(actions[action], row['a'], row['b'])
                need(observation['actual'] == actual and observation['expected'] == row['expected']
                     and observation['correct'] == (actual == row['expected']), 'actual training observer outcome')
            if values != (len(rewards), sum(rewards)//len(rewards), min(rewards), max(rewards)):
                raise ValueError('native learned means differ from actual observations')
        models.append(sha(raw)); predictions.append(choice_table(cells, actions, queries))
        if index:
            withdrawal = load(folder/'withdrawal-control/observed.json')
            if withdrawal['candidate'] != sha(raw) or withdrawal['reopened_original_owner'] is not True:
                raise ValueError('separate candidate withdrawal control')
            need(type(withdrawal['native_error']) is str and withdrawal['native_error'], 'actual cached withdrawal denial')
            if sha(bounded(folder/'withdrawal-control/revocation.json')) != withdrawal['revocation_receipt_digest']:
                raise ValueError('withdrawal receipt changed')
            owner = load(root/'artifact-owner/study-namespace.json')
            probe = load(folder/'withdrawal-control/owner/study-namespace.json')
            if owner['registry_id'] == probe['registry_id'] or owner['scope_digest'] == probe['scope_digest']:
                raise ValueError('withdrawal control must use separate namespace')
            durable_revoke(folder/'withdrawal-control', folder/'withdrawal-control/owner', artifact, keys['publisher'])
        if index == 4:
            need(predictions[4] == predictions[3], 'no-update model behavior changed')
            break
        actual_choices = {}
        for query in queries:
            context = load(folder/f'installed-{query}-native-context.json')
            need(len(context['items']) == 1, 'actual installed context denominator')
            actual_choices[query] = context['items'][0]['content'].split()[-1]
        need(actual_choices == predictions[index], 'native model differs from installed choices')
        if index:
            commitment = commitments[f'generation-{index}-installed-consumer']['body']
            if commitment['choices'] != actual_choices or commitment['candidate_sha256'] != sha(raw):
                raise ValueError('installed native context differs from committed consumer')
            entry = summary['generations'][index-1]
            integer(entry['wall_ns'], 'actual generation cost', 1)
            if entry['candidate'] != sha(raw) or entry['launch_generation'] != 1+4*index \
                    or entry['parent'] != models[index-1] or entry['generation'] != index \
                    or entry['model_generation'] != generation:
                raise ValueError('actual installed source/launch binding')
            for window in (1,2):
                scores = evaluations[f'generation-{index}-window-{window}']['counts']
                if scores['candidate'] <= scores['parent']:
                    raise ValueError('no measured future improvement')
            if evaluations[f'generation-{index}-installed-consumer']['counts']['candidate'] != (index+1)*8:
                raise ValueError('actual installed consumer failed')
    for index in range(1, 5):
        name = f'generation-{index}' if index < 4 else 'no-update'
        folder = root/name
        training_rows = training[min(index, 3)][1 if index == 4 else 0]
        material_bindings(root, folder, name, models[index], models[index-1], predictions[index], predictions[index-1],
                          evaluation_records, future_observers, role_rows, native_signatures,
                          commitments, material_commitments, release_records, training_rows, operations,
                          summary['generations'][index-1]['selection'] if index < 4 else None)
    for query in queries:
        retained = load(root/'no-update'/f'retained-parent-{query}-native-context.json')
        need(retained['items'][0]['content'].split()[-1] == predictions[3][query], 'no-update changed installed parent')
    if summary['installed_generations'] != 3 or summary['no_update_error'] != 'EvaluationRejected' or summary['revoked_reads_refused'] != 2:
        raise ValueError('native terminal outcomes')
    for window in (1,2):
        body = evaluations[f'no-update-window-{window}']
        if body['counts']['candidate'] != body['counts']['parent']:
            raise ValueError('no-update did not measure an equal candidate')
    restarts = summary['process_descriptor_restarts']
    if len(restarts) != 2 or not summary['named_writer_durable_revocation']:
        raise ValueError('process restart or actual durable revocation absent')
    for restart in restarts:
        descriptor = Path(restart['descriptor'])
        original_root = Path(load(root/'artifact-owner/study-namespace.json')['root']).parent
        need(descriptor.is_absolute() and descriptor.is_relative_to(original_root), 'process descriptor outside evidence')
        descriptor = root/descriptor.relative_to(original_root)
        if sha(bounded(descriptor, 4*1024*1024)) != restart['digest']:
            raise ValueError('process descriptor changed')
        inputs = load(descriptor, 4*1024*1024)
        if inputs['schema'] != 'hepta.agentd.cognitive-bootstrap.v2' \
                or inputs['profile'] != 'published_product_qualification_v1' \
                or 'evaluation_bundle' in inputs \
                or inputs['holdout']['anchor'] != summary['holdout_anchor'] \
                or inputs['spawn_generation'] != restart['launch_generation'] \
                or inputs['model_pin']['payload_digest'] != models[3]:
            raise ValueError('process holdout differs from independently retained frontier')
        controls = load(root/f"process-{restart['launch_generation']}-replay-negative-controls.json")
        need(len(controls) == 2 and {control['control'] for control in controls} == {'new-fence', 'unrecorded-plan'},
             'actual product replay negative controls')
        for control in controls:
            need(control['cas_unchanged'] is True
                 and 'exact recorded plan and fence' in control['error']
                 and control['cas_sha256'] == sha(bounded(root/'holdouts', 16*1024*1024)),
                 'product replay control mutated holdout')
        for query in queries:
            context = load(root/f"process-{restart['launch_generation']}-{query}-native-context.json")
            if context['items'][0]['content'].split()[-1] != operations[queries.index(query)]:
                raise ValueError('restarted native inference changed')
    need(summary['production_qualification'] is False, 'unsupported promotion')
    durable_revoke(root, root/'artifact-owner', 'learned-generation-3', keys['publisher'])
    need(summary.get('live_process_reader_external_revoke') is True, 'live process reader revocation required')
    revoked = load(root/'revoke-observations.json')
    need(revoked['candidate'] == models[3] and revoked['consumer_kept_alive'] is True
         and revoked['launch_generation'] == restarts[-1]['launch_generation']
         and revoked['live_current_error'] and revoked['producer_recovered_error']
         and revoked['revocation_receipt_digest'] == sha(bounded(root/'revocation.json')), 'live reader withdrawal outcome')
    cost = cost_receipt(root, summary, completed, profile)
    return dict(verified_local_generations=3, distinct_material_instances=len(material_seen), evaluated_windows=len(evaluations),
                whole_child_cpu_seconds=cost['child_user_seconds']+cost['child_system_seconds'],
                waited_child_peak_rss_bytes=cost['waited_child_peak_rss_bytes'], simultaneous_process_tree_memory=None,
                production_qualification=False, organizational_independence=False)


if __name__ == '__main__':
    print(json.dumps(verify(Path(sys.argv[1]))))
