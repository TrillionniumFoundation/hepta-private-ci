"""Lossless *routing* projection for original ScienceQA V27 frozen decision policy.

The historic V27 plan contains *precomputed image-class predictions* that must
never become an input to V29's physical on-demand image Encoder. The previous
research experiment did not receive TEST labels, but those class fields were
still an avoidable counterfactual oracle. This module strips them at a sealed
boundary; no learned scores, labels, or model invocation occur here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import v28_physical_lazy_vision as v28

SCHEMA = 'hepta.stem.v29.source-only-vision-route.v1'
MINIMAL_SHA256 = 'd8a555bef8f95680cd35a16cf3dbe7f8e9ab717fe626e4dc82e6fd61538773a6'
POLICY = 'original_text_only_margin_lt_0.005'
ROUTE_COLUMNS = frozenset(('id', 'group', 'trigger_vision'))


def exact_doc(raw: bytes):
    value = v28.strict_json(raw)
    v28.require(type(value) is dict and raw == v28.canonical(value),
                'noncanonical route bytes')
    return value


def project_original(raw: bytes) -> dict:
    """Accept ONLY the exact frozen full original plan, no synthetic replacement."""
    v28.require(v28.sha(raw) == v28.PLAN_SHA, 'not the frozen original V27 plan')
    full = exact_doc(raw)
    rows = v28.validate_plan(full)
    model_rows = [{'id': row['id'], 'group': row['group'],
                   'trigger_vision': row['trigger_vision']} for row in rows]
    out = {'schema': SCHEMA, 'v27_plan_sha256': v28.PLAN_SHA,
           'source_sha256': v28.STEM_SOURCE, 'policy': POLICY,
           'threshold': 0.005, 'rows': model_rows, 'prelabel_only': True,
           'no_precomputed_vision_outputs': True,
           'actual_encoder_executed': False, 'production_authorized': False}
    validate_model_plan(v28.canonical(out))
    return out


def validate_model_plan(raw: bytes) -> list[dict]:
    """Only allowed V29 physical model-facing plan: three row fields, no scores."""
    v28.require(v28.sha(raw) == MINIMAL_SHA256, 'unexpected model-visible route bytes')
    doc = exact_doc(raw)
    v28.require(set(doc) == {'schema','v27_plan_sha256','source_sha256',
                 'policy','threshold','rows','prelabel_only',
                 'no_precomputed_vision_outputs','actual_encoder_executed',
                 'production_authorized'}, 'unreviewed model route envelope')
    v28.require(doc['schema'] == SCHEMA and doc['v27_plan_sha256'] == v28.PLAN_SHA
                and doc['source_sha256'] == v28.STEM_SOURCE
                and doc['policy'] == POLICY and type(doc['threshold']) is float
                and doc['threshold'] == 0.005, 'wrong source or frozen text routing')
    v28.require(doc['prelabel_only'] is True
                and doc['no_precomputed_vision_outputs'] is True
                and doc['actual_encoder_executed'] is False
                and doc['production_authorized'] is False,
                'untrusted learned result or unauthorized flag')
    rows = doc['rows']
    v28.require(type(rows) is list and len(rows) == v28.N_CASES,
                'missing original source cases')
    ids, groups = set(), set()
    for row in rows:
        v28.require(type(row) is dict and set(row) == ROUTE_COLUMNS,
                    'precomputed class, score, label or unauthorized field in route')
        v28.require(v28.h64(row['id']) and v28.h64(row['group'])
                    and type(row['trigger_vision']) is bool
                    and row['id'] not in ids and row['group'] not in groups,
                    'invalid source group, trigger or duplicate')
        ids.add(row['id']);groups.add(row['group'])
    v28.require(sum(r['trigger_vision'] for r in rows) == v28.N_TRIGGER,
                'image schedule drift')
    return rows


def create_minimal(full_path: Path, output_path: Path) -> dict:
    original = v28.protected_read(full_path)
    new_plan = project_original(original)
    v28.safe_write(output_path, new_plan)
    v28.require(v28.sha(v28.protected_read(output_path)) == MINIMAL_SHA256,
                'failed immutable sealed V29 readback')
    return new_plan


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full-plan',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    plan=create_minimal(args.full_plan,args.output)
    print(json.dumps({'schema':SCHEMA,'source_rows':len(plan['rows']),
         'physical_forward_executed':False,'production_authorized':False,
         'model_route_sha256':MINIMAL_SHA256},sort_keys=True))
