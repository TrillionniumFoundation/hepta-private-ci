"""V20 pre-model source/Tokenizer admission for the original source-first Qwen reference.

Strictly analysis-only: model files are authenticated but NO pretrained forward is run;
no publisher gold, raw prompts, generated answers, or model weights enter its receipt.
The experiment remains DENY_ALL even when all static checks pass.
"""
import argparse
import json
from pathlib import Path

import source_first as v17
import v19_qwen_material as material
import v19_qwen_reference as qwen

SCHEMA = 'hepta.v20.original-locomo-qwen-reference.preflight.v1'
EXPECTED_LOGICAL = 120
EXPECTED_PHYSICAL = 96


def _require_unlabeled(paths, private_output, model_dir):
    files = tuple(Path(x) for x in paths)
    if len(files) != 5 or any(not x.is_file() or x.is_symlink() for x in files):
        raise ValueError('incomplete source-only request input')
    source_dir = files[0].parent
    if len({x.resolve().parent for x in files}) != 1:
        raise ValueError('source files are not in one frozen source directory')
    if any((source_dir / name).exists() or (source_dir / name).is_symlink()
           for name in ('hidden.json', 'locomo.json', 'original.zip', 'postseal-original.zip')):
        raise ValueError('publisher answer labels or original raw corpus present at model admission')
    private_output = Path(private_output)
    if private_output.exists() or private_output.is_symlink() or not private_output.parent.is_dir():
        raise ValueError('model preflight must use an absent create-only private receipt')
    model_dir = Path(model_dir)
    if not model_dir.is_dir() or model_dir.is_symlink():
        raise ValueError('model material source directory invalid')


def admit(paths, reference_plan, model_dir, model_spec, output, tokenizer=None):
    """Check source-first 30x4 plan and exact model-specific tokenizer input geometry.

    tokenizer may be injected only for offline *mechanism fixtures*, not the CLI.
    """
    _require_unlabeled(paths, output, model_dir)
    frozen = qwen.validate(paths, reference_plan)
    spec = v17.read(model_spec)
    model_digest = material.verify_snapshot(model_dir, spec)
    if tokenizer is None:
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True,
                                                   trust_remote_code=False, use_fast=True)
    if len(frozen['entries']) != EXPECTED_LOGICAL:
        raise ValueError('incomplete source-first model-input roster')
    token_by_message = {}
    message_by_token = {}
    tokens_by_request = {}
    source_groups = {}
    for request_id, entry in sorted(frozen['entries'].items()):
        if (type(entry) is not dict or entry['message_sha256'] != v17.digest(entry['messages'])
                or entry['arm'] not in qwen.ARMS):
            raise ValueError('original source/citation or model message changed')
        message_digest = entry['message_sha256']
        ids = tokenizer.apply_chat_template(entry['messages'], tokenize=True,
                                             add_generation_prompt=True, enable_thinking=False)
        if (type(ids) is not list or not 1 <= len(ids) <= qwen.INPUT_CAP
                or any(type(x) is not int or x < 0 for x in ids)):
            raise ValueError('Qwen native tokenizer input missing, truncated, or invalid')
        token_digest = v17.digest(ids)
        # A genuine tokenizer must neither split identical messages across physical
        # requests nor alias DIFFERENT source messages into the same model input.
        if message_digest in token_by_message and token_by_message[message_digest] != token_digest:
            raise ValueError('same original message tokenized differently')
        if token_digest in message_by_token and message_by_token[token_digest] != message_digest:
            raise ValueError('distinct source messages collapsed to an identical physical input')
        token_by_message[message_digest] = token_digest
        message_by_token[token_digest] = message_digest
        source_groups.setdefault(token_digest, []).append(request_id)
        tokens_by_request[request_id] = len(ids)
    if (len(token_by_message) != EXPECTED_PHYSICAL
            or len(message_by_token) != EXPECTED_PHYSICAL
            or sum(map(len, source_groups.values())) != EXPECTED_LOGICAL):
        raise ValueError('source-first 120 logical / 96 physical request contract mismatch')
    expected = {v17.digest(entry['messages']): entry['message_sha256']
                for entry in frozen['entries'].values()}
    if len(expected) != EXPECTED_PHYSICAL or any(k != v for k, v in expected.items()):
        raise ValueError('original content uniqueness or message provenance diverged')
    if material.verify_snapshot(model_dir, spec) != model_digest:
        raise ValueError('immutable Qwen source bytes drifted during tokenization')
    source_aliases = {key: sorted(value) for key, value in source_groups.items()}
    manifest = {
        'schema': SCHEMA,
        'original_v17_plan_sha256': frozen['v17_plan_sha256'],
        'original_v19_reference_plan_sha256': frozen['plan_sha256'],
        'qwen_model_material_sha256': model_digest,
        'original_source_roots': len(frozen['source_roots']),
        'original_source_cases': len(frozen['cases']),
        'logical_model_requests': len(frozen['entries']),
        'unique_physical_input_ids': len(source_aliases),
        'source_to_qwen_token_mapping_sha256': v17.digest(token_by_message),
        'token_alias_groups_sha256': v17.digest(source_aliases),
        'logical_input_tokens': sum(tokens_by_request.values()),
        'unique_input_tokens': sum(tokens_by_request[ids[0]] for ids in source_aliases.values()),
        'largest_input_tokens': max(tokens_by_request.values()),
        'model_input_tokens_matched_to_135m': False,
        'publisher_answer_labels_available_to_reader': False,
        'independent_human_sufficiency_review': False,
        'original_qwen_forward_executed': False,
        'original_135m_forward_executed_by_this_preflight': False,
        'model_quality_or_ndu_gain_verified': False,
        'production_authorized': False,
        'decision': 'HOLD_NO_GO',
    }
    v17.write_once(output, manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ('public', 'owner', 'v17-plan', 'annotation', 'v17-requests',
                  'reference-plan', 'model-dir', 'model-spec', 'output'):
        parser.add_argument('--' + field)
    parser.add_argument('--physical')
    parser.add_argument('--preflight')
    a = parser.parse_args()
    if a.physical is not None or a.preflight is not None:
        if a.physical is None or a.preflight is None:
            parser.error('both --physical and --preflight required for reconciliation')
        print(json.dumps(reconcile(a.preflight, a.physical), sort_keys=True))
        return
    if not all((a.public,a.owner,a.v17_plan,a.annotation,a.v17_requests,
                a.reference_plan,a.model_dir,a.model_spec,a.output)):
        parser.error('complete original source/material arguments required for initial preflight')
    result = admit((a.public, a.owner, a.v17_plan, a.annotation, a.v17_requests),
                   a.reference_plan, a.model_dir, a.model_spec, a.output)
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))



def reconcile(preflight_path, physical_path):
    """Independent cheap physical-alias check; no model execution or semantic claim.

    The private physical packet is only trusted as an input that must satisfy
    source-first immutability; actual model execution is still independently audited.
    """
    p = v17.read(preflight_path)
    original = v17.read(physical_path)
    if (type(p) is not dict or p.get('schema') != SCHEMA
            or p.get('original_qwen_forward_executed') is not False
            or p.get('publisher_answer_labels_available_to_reader') is not False
            or p.get('model_quality_or_ndu_gain_verified') is not False
            or p.get('production_authorized') is not False or p.get('decision') != 'HOLD_NO_GO'):
        raise ValueError('pre-model preflight identity or scientific posture corrupted')
    if (original.get('schema') != qwen.SCHEMA+'.physical-private'
            or original.get('plan_sha256') != p['original_v19_reference_plan_sha256']
            or original.get('model_spec_sha256') != p['qwen_model_material_sha256']
            or original.get('actual_unique_qwen_requests') != EXPECTED_PHYSICAL
            or original.get('logical_arm_requests') != EXPECTED_LOGICAL
            or original.get('authority') != 'DENY_ALL'
            or original.get('production_authorized') is not False
            or original.get('decision') != 'HOLD_NO_GO'):
        raise ValueError('physical reference output detached from preflight identity')
    mapping = original.get('requests_by_id')
    rows = original.get('physical_outputs')
    if (type(mapping) is not dict or len(mapping) != EXPECTED_LOGICAL
            or type(rows) is not dict or len(rows) != EXPECTED_PHYSICAL
            or set(mapping.values()) != set(rows)):
        raise ValueError('physical original reference incomplete')
    aliases = {}
    for rid, digest in sorted(mapping.items()):
        if type(rid) is not str or type(digest) is not str:
            raise ValueError('invalid physical source IDs')
        aliases.setdefault(digest, []).append(rid)
    aliases = {key: sorted(value) for key, value in aliases.items()}
    if v17.digest(aliases) != p['token_alias_groups_sha256']:
        raise ValueError('physical model aliases differ from originally admitted Qwen token groups')
    unique_tokens = logical_tokens = 0
    for digest, groups in aliases.items():
        row = rows[digest]
        if (type(row) is not dict or row.get('logical_ids') != groups
                or type(row.get('input_tokens')) is not int
                or not 1 <= row['input_tokens'] <= qwen.INPUT_CAP):
            raise ValueError('physical forward or token count changed')
        unique_tokens += row['input_tokens']
        logical_tokens += row['input_tokens'] * len(groups)
    if (unique_tokens != p['unique_input_tokens']
            or logical_tokens != p['logical_input_tokens']):
        raise ValueError('physical model input-token accounting differs from preflight')
    return {'schema':SCHEMA+'.postseal-alias-reconciliation',
            'model_reference_plan_sha256':p['original_v19_reference_plan_sha256'],
            'source_alias_mapping_sha256':p['token_alias_groups_sha256'],
            'unique_tokens_paid_once':unique_tokens,
            'logical_tokens_with_aliases':logical_tokens,
            'original_Qwen_semantic_correctness_verified':False,
            'physical_model_host_signature_verified':False,
            'production_authorized':False,'decision':'HOLD_NO_GO'}


if __name__ == '__main__':
    main()
