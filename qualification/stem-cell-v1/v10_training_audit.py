"""Independent V10 real-Granite nine-fit source/optimizer-trace audit.

Standard-library only, no shared trainer sampling function, no model weights and no
labels from the restricted heldout cohort. Counts actual receipts, not SGD work.
"""
from collections import defaultdict
import math
import random

from v9_typed_graph import digest

SEEDS = (41, 47, 53)
ARMS = ('base', 'bridge', 'endpoint')
UPDATES = 256


def verify_trace(public, source_seal, receipt, schedule, *, seed, arm):
    if seed not in SEEDS or arm not in ARMS or type(seed) is not int:
        raise ValueError('predeclared seed and model variant required')
    if (type(public) is not list or len(public) != 1248
            or type(source_seal) is not dict
            or source_seal.get('schema') != 'hepta.v10.real-granite-source.v1'
            or source_seal.get('public_sha256') != digest(public)
            or source_seal.get('train_rows') != 288
            or source_seal.get('held_rows') != 960
            or source_seal.get('source_groups') != 312
            or type(source_seal.get('train_label_sha256')) is not str
            or type(receipt) is not dict
            or receipt.get('schema') != 'hepta.v10.real-granite-training.v1'
            or receipt.get('seed') != seed or receipt.get('arm') != arm
            or receipt.get('input_public_sha256') != source_seal['public_sha256']
            or receipt.get('training_labels_sha256') != source_seal['train_label_sha256']
            or receipt.get('model_parameters') != (38466 if arm == 'base' else 42562)
            or receipt.get('actual_updates') != UPDATES
            or receipt.get('batch_size') != 16
            or receipt.get('total_optimizer_case_exposures') != UPDATES * 16
            or receipt.get('source_groups') != 72
            or receipt.get('optimizer') != 'Adam_foreach_false'
            or receipt.get('learning_rate') != .001
            or receipt.get('depth') != 3
            or receipt.get('pair_weight') != .5
            or receipt.get('held_labels_seen') is not False
            or receipt.get('held_predictions_scored') is not False
            or receipt.get('model_selected') is not False
            or receipt.get('production_accepted') is not False
            or receipt.get('authority') != 'DENY_ALL'
            or type(schedule) is not list or len(schedule) != UPDATES):
        raise ValueError('complete real-training source, sealed labels and optimizer contract required')
    groups = defaultdict(list)
    for row in public:
        if (type(row) is not dict or set(row) != {
                'case_id', 'source_group', 'facts', 'question', 'candidate'}):
            raise ValueError('public sample includes forbidden or missing fields')
        if row['case_id'].startswith('train/'):
            groups[row['source_group']].append(row['case_id'])
    if len(groups) != 72 or any(len(rows) != 4 for rows in groups.values()):
        raise ValueError('72 complete paired train source groups required')
    keys = sorted(groups)
    rng = random.Random(f'hepta/v10/granite/fixed-batches/{seed}')
    seen_rows = 0
    for index, record in enumerate(schedule, 1):
        expected_groups = rng.sample(keys, 4)
        expected_ids = [case_id for group in expected_groups for case_id in groups[group]]
        if (type(record) is not dict or set(record) != {
                'update', 'groups', 'source_sha256', 'ce', 'pair', 'total'}
                or type(record['update']) is not int or record['update'] != index
                or record['groups'] != expected_groups
                or record['source_sha256'] != digest(expected_ids)):
            raise ValueError('actual recorded minibatch not from preregistered source schedule')
        ce, pair, total = (record[key] for key in ('ce', 'pair', 'total'))
        if (any(type(n) not in (float, int) or not math.isfinite(n) or n < 0
                for n in (ce, pair, total))
                or abs(total - (ce + .5 * pair)) > 1e-4):
            raise ValueError('nonfinite or inconsistent actual SGD loss accounting')
        seen_rows += len(expected_ids)
    return {'schema': 'hepta.v10.independent-training-trace.v1',
            'seed': seed, 'arm': arm, 'updates': UPDATES,
            'real_recorded_optimizer_exposures': seen_rows,
            'source_groups': len(groups), 'source_sha256': digest(public),
            'train_labels_sha256': source_seal['train_label_sha256'],
            'recorded_schedule_sha256': digest(schedule),
            'original_receipt_verified': True,
            'externally_verified_SGD': False,
            'production_accepted': False, 'authority': 'DENY_ALL'}
