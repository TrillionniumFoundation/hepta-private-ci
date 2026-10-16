"""Torch-free E27 material contract shared across source owner and Cell trainer.

Importing this module must not load Torch, Transformers, model weights, or
held-out truth. Exact versioned fields remain unchanged by the separation.
"""

import hashlib
import json

AUTHORITY = 'DENY_ALL'
SCHEMA = 'hepta.e27.answer-token-cell-shadow.v1'
MAX_TOKENS = 256

def canonical_sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False, ensure_ascii=False).encode()).hexdigest()


def _check_text(s, bound):
    if type(s) is not str or not s.strip() or len(s.encode()) > bound:
        raise ValueError('bad/oversized source text')
    return s


def validate_material(material, *, mode):
    """Never infer train/held role from filenames or model-provided prose."""
    if (type(material) is not dict or set(material) != {
        'schema', 'role', 'source_sha256', 'source_revision', 'groups',
        'selection_uses_labels', 'production_accepted', 'authority'
    } or material['schema'] != SCHEMA + '.material' or
        material['role'] != mode or material['authority'] != AUTHORITY or
        material['selection_uses_labels'] is not False or
        material['production_accepted'] is not False or
        type(material['source_sha256']) is not str or
        len(material['source_sha256']) != 64 or
        type(material['source_revision']) is not str or
        not material['source_revision'] or
        type(material['groups']) is not list or
        not 1 <= len(material['groups']) <= 96):
        raise ValueError('wrong source material contract')
    group_ids = set()
    n_cases = 0
    n_q = 0
    positives = 0
    mixed_questions = 0
    for group in material['groups']:
        if (type(group) is not dict or set(group) != {'group_id', 'evidence', 'questions'} or
            type(group['group_id']) is not str or
            len(group['group_id']) != 64 or group['group_id'] in group_ids or
            type(group['questions']) is not list or
            not 1 <= len(group['questions']) <= 16):
            raise ValueError('missing/conflicting source group')
        group_ids.add(group['group_id'])
        _check_text(group['evidence'], 32000)
        seen_q = set()
        for q in group['questions']:
            if (type(q) is not dict or set(q) != {'question_id', 'text', 'candidates'} or
                type(q['question_id']) is not str or len(q['question_id']) != 64 or
                q['question_id'] in seen_q or type(q['candidates']) is not list or
                not 2 <= len(q['candidates']) <= 8):
                raise ValueError('unqualified original whole question')
            seen_q.add(q['question_id'])
            _check_text(q['text'], 4096)
            n_q += 1
            aids = set()
            labels = []
            for c in q['candidates']:
                expected = {'candidate_id', 'text', 'label'} if mode == 'train' else {'candidate_id', 'text'}
                if (type(c) is not dict or set(c) != expected or
                    type(c['candidate_id']) is not str or len(c['candidate_id']) != 64 or
                    c['candidate_id'] in aids):
                    raise ValueError('held labels, duplicate ID, or incomplete candidate')
                _check_text(c['text'], 4096)
                aids.add(c['candidate_id'])
                if mode == 'train':
                    if type(c['label']) is not int or c['label'] not in (0, 1):
                        raise ValueError('invalid TRAIN label')
                    labels.append(c['label'])
                    positives += c['label']
                n_cases += 1
            if mode == 'train' and 0 in labels and 1 in labels:
                mixed_questions += 1
    if (mode == 'train' and (positives == 0 or mixed_questions == 0)) or n_cases > 1200 or n_q > 288:
        raise ValueError('insufficient/oversized original source support')
    return group_ids, n_q, n_cases
