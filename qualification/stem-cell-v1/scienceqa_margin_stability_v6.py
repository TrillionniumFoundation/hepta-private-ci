"""Original-only label-blind multimodal decision-margin stability audit.

Reopens the exact immutable physically executed ScienceQA E3 prediction archive.
No source labels, model/forward, fit, model selection, or production authority.
The L-infinity probability perturbation radius epsilon gives a sufficient
certificate of unchanged top-1 class if original top1-top2 gap > 2*epsilon.
This is numerical output stability, NOT a causal intervention on image pixels.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
from statistics import median

from scienceqa_independent_rejudge_v5 import (
    ARMS, PRED_SHA, SOURCE_SHA, V5Error, canonical, need, parse, read_archive, sha,
)

EPSILONS = (0.0, 0.0001, 0.001, 0.005, 0.01)
SCHEMA = 'hepta.stem.original-e3-margin-certificate.v6'


def top_two(probabilities):
    need(type(probabilities) is list and len(probabilities) == 4,
         'requires four original output class probabilities')
    need(all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1
             for v in probabilities), 'invalid probability')
    need(abs(math.fsum(probabilities) - 1) < 1e-6,
         'original model output probability does not sum to one')
    order = sorted(range(4), key=lambda k: (-probabilities[k], k))
    return order[0], probabilities[order[0]] - probabilities[order[1]]


def audit(archive):
    need(type(archive) is dict and 'sealed-source-bound-predictions.json' in archive,
         'missing immutable original predictions')
    original_bytes = archive['sealed-source-bound-predictions.json']
    need(sha(original_bytes) == PRED_SHA, 'original predictions not SHA pinned')
    doc = parse(original_bytes)
    need(doc.get('source_sha256') == SOURCE_SHA and doc.get('arms') == list(ARMS) and
         doc.get('held_labels_visible_to_inference') is False and
         doc.get('production_accepted') is False,
         'source or arm lineage and no-authority contract drift')
    rows = doc.get('predictions')
    need(type(rows) is list and len(rows) == 64,
         'exact real pretrained heldout prediction count required')
    seen = set()
    measures = {arm: {'changes': 0, 'base_margin': [], 'arm_margin': [],
                      'certified': defaultdict(int), 'abstentions': defaultdict(int)}
                for arm in ARMS}
    for record in rows:
        need(type(record) is dict and set(record) == {
            'id', 'group', 'split', 'source_input_sha256', 'arms'
        } and record['split'] == 'test' and
             type(record['id']) is str and len(record['id']) == 64 and
             type(record['group']) is str and len(record['group']) == 64 and
             type(record['source_input_sha256']) is str and
             len(record['source_input_sha256']) == 64 and
             record['id'] not in seen and
             type(record['arms']) is dict and set(record['arms']) == set(ARMS),
             'altered source-bound original test case')
        seen.add(record['id'])
        outputs = record['arms']
        need(outputs['image_masked'] == outputs['text_only'],
             'original image-masked negative control differs from text')
        base_index, base_gap = top_two(outputs['text_only'])
        for arm, p in outputs.items():
            index, gap = top_two(p)
            m = measures[arm]
            changed = index != base_index
            m['changes'] += int(changed)
            m['base_margin'].append(base_gap)
            m['arm_margin'].append(gap)
            for epsilon in EPSILONS:
                key = format(epsilon, '.4f')
                # A strict > avoids claiming robust ties at eps=0.
                # Both outputs must independently have a stable argmax.
                certified = base_gap > 2 * epsilon and gap > 2 * epsilon
                m['certified'][key] += int(changed and certified)
                m['abstentions'][key] += int(not certified)
    need(len(seen) == 64, 'missing/duplicate original heldout IDs')
    report = {}
    for arm in ARMS:
        m = measures[arm]
        need(m['certified']['0.0000'] <= m['changes'],
             'invalid predicted robustness certificate')
        report[arm] = {
            'argmax_changes_vs_text': m['changes'],
            'mean_base_margin': math.fsum(m['base_margin']) / 64,
            'mean_arm_margin': math.fsum(m['arm_margin']) / 64,
            'median_arm_margin': median(m['arm_margin']),
            'certified_changed_at_epsilon': dict(m['certified']),
            'abstaining_cases_at_epsilon': dict(m['abstentions']),
        }
    need(report['text_only']['argmax_changes_vs_text'] == 0 and
         report['image_masked']['argmax_changes_vs_text'] == 0 and
         report['calibrated_fusion']['argmax_changes_vs_text'] == 0,
         'known text/masked negative control failed')
    return {
        'schema': SCHEMA,
        'original_pretrained_archive_sha256':
            'f421f20cdb5d35becf5e93ed63e58996d48701c2b27b979d608e2b05b6b61f30',
        'original_predictions_sha256': PRED_SHA,
        'source_sha256': SOURCE_SHA,
        'case_count': 64,
        'epsilon_linf_probabilities': list(EPSILONS),
        'arms': report,
        'heldout_labels_accessed': False,
        'original_model_forward_in_this_audit': False,
        'actual_image_intervention_performed': False,
        'visual_necessity_or_task_quality_proven': False,
        'independent_source_or_model_signer': False,
        'new_training_performed': False,
        'stem_winner_selected': False,
        'production_authorized': False,
        'authority': 'DENY_ALL',
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    result = audit(read_archive(args.archive))
    need(not args.out.exists() and not args.out.is_symlink(),
         'no overwriting prior original science evidence')
    with args.out.open('xb') as f:
        f.write(canonical(result))
        f.flush()
        os.fsync(f.fileno())
    print('SCIENCEQA_ORIGINAL_MARGIN_AUDIT_PASS: label blind DENY_ALL')


if __name__ == '__main__':
    main()
