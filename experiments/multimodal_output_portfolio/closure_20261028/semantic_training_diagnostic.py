"""Training-only provenance, label-set and exact cached-input diagnostics.

No estimator is fitted. No development or held-out prepared file is accessed.
Exact-row agreement bounds describe this finite training table, not population
accuracy or a ceiling on a future model with a different representation.
"""
import argparse
import ast
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import struct
import time
import zipfile


def sha(path):
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


def numpy_rows(payload):
    if payload[:6] != b'\x93NUMPY':
        raise ValueError('Unexpected cached-array format')
    major = payload[6]
    if major == 1:
        length = struct.unpack('<H', payload[8:10])[0]
        start = 10
    elif major == 2:
        length = struct.unpack('<I', payload[8:12])[0]
        start = 12
    else:
        raise ValueError('Unsupported array header version')
    header = ast.literal_eval(payload[start:start + length].decode('latin1'))
    shape = header['shape']
    if header['descr'] != '<f4' or header['fortran_order'] or len(shape) != 2:
        raise ValueError('Expected fixed little-endian float32 feature rows')
    body = payload[start + length:]
    width = 4 * shape[1]
    if len(body) != shape[0] * width:
        raise ValueError('Feature payload shape mismatch')
    return [hashlib.sha256(body[i * width:(i + 1) * width]).hexdigest()
            for i in range(shape[0])], shape[1]


def finite_agreement(records, key, kind):
    groups = defaultdict(Counter)
    counts = Counter()
    for row in records:
        groups[row[key]][row[kind]['selected']] += row['weight']
        counts[row[key]] += 1
    conflicting = {identity: values for identity, values in groups.items() if len(values) > 1}
    return {'unique_input_groups': len(groups),
            'repeated_groups': sum(value > 1 for value in counts.values()),
            'conflicting_label_groups': len(conflicting),
            'source_uniform_weight_in_conflicting_groups': sum(sum(v.values()) for v in conflicting.values()),
            'maximum_agreement_on_this_finite_table': sum(max(v.values()) for v in groups.values()),
            'scope': 'Best deterministic label per exact inspected input identity on this finite weighted training table; not a population accuracy limit or a claim about new representations.'}


def set_metrics(predicted, target):
    overlap = len(predicted & target)
    precision = overlap / len(predicted) if predicted else 0.0
    recall = overlap / len(target) if target else 0.0
    f1 = 2 * overlap / (len(predicted) + len(target)) if predicted or target else 0.0
    return precision, recall, f1


def inspect_training(assets, output):
    source_path = assets / 'SOURCE_PROTOCOL.json'
    source = json.loads(source_path.read_text())
    if source['protocol_sha256'] != 'ad58bf5529af473f722c8e48a44f34ae07e364356b664a3a79458fecf1405b9d':
        raise ValueError('This post-study diagnostic is bound to the unchanged v3 allocation')
    annotations, pins = {}, {}
    for kind in ('action', 'sound'):
        name = f'{kind}_localisation_train_annotations.zip'
        path = assets / name
        pins[kind] = sha(path)
        if pins[kind] != source['annotation_archives']['train_' + kind]['sha256']:
            raise ValueError('Official training annotation archive changed')
        with zipfile.ZipFile(path) as archive:
            annotations[kind] = json.loads(archive.read(f'{kind}_localisation_train.json'))
        if any(row['metadata']['split'] != 'train' for row in annotations[kind].values()):
            raise ValueError('Only official training annotations are eligible for this diagnostic')
    roles = {}
    feature_receipts = []
    for role in ('generator_train', 'observer_train'):
        allocated = [row for row in source['selected'] if row['role'] == role]
        records, feature_cpu = [], []
        for row in allocated:
            events = row['events'][:row['retained_event_count']]
            feature_hashes = {}
            if role == 'observer_train':
                directory = assets / 'prepared' / role / row['source_id']
                receipt_path = directory / 'RECEIPT.json'
                receipt = json.loads(receipt_path.read_text())
                feature_path = directory / 'FEATURES.npz'
                actual = sha(feature_path)
                if actual != receipt['retained_files']['FEATURES.npz']:
                    raise ValueError('Frozen training features changed')
                if receipt['source_id'] != row['source_id'] or receipt['role'] != role:
                    raise ValueError('Training source identity changed')
                feature_receipts.append({'source_id': row['source_id'], 'receipt_sha256': sha(receipt_path),
                                         'feature_sha256': actual})
                feature_cpu.append(float(receipt.get('feature_cpu_seconds', 0)))
                with zipfile.ZipFile(feature_path) as archive:
                    for family, name in [('s3d', 'video'), ('tsm', 'video_tsm'), ('pann', 'audio')]:
                        hashes, width = numpy_rows(archive.read(name + '.npy'))
                        if len(hashes) != len(events):
                            raise ValueError('Feature/event count mismatch')
                        feature_hashes[family] = hashes
            for index, event in enumerate(events):
                begin, end = event['target_start_seconds'], event['target_end_seconds']
                if not all(math.isfinite(value) for value in (begin, end)) or end <= begin:
                    raise ValueError('Invalid frozen target interval')
                item = {'source_id': row['source_id'], 'event_index': index,
                        'window_identity': row['source_id'] + ':' + float(event['window_start_seconds']).hex(),
                        'target_interval': [begin, end], 'weight': 1 / (len(allocated) * len(events))}
                for family, hashes in feature_hashes.items():
                    item[family + '_input_identity'] = hashes[index]
                parents = {}
                for kind in ('action', 'sound'):
                    entries = annotations[kind][row['source_id']][kind + '_localisation']
                    by_class = {}
                    for entry in entries:
                        overlap = max(0.0, min(end, entry['timestamps'][1] / 1e6)
                                      - max(begin, entry['timestamps'][0] / 1e6))
                        if overlap >= 0.15 - 1e-9:
                            by_class[entry['label_id']] = max(by_class.get(entry['label_id'], 0.0), overlap)
                    selected = event[kind + '_id']
                    if selected not in by_class:
                        raise ValueError('Frozen selected label absent from the target')
                    annotation = [v for v in entries if v['id'] == event[kind + '_annotation_id']]
                    if len(annotation) != 1 or annotation[0]['label_id'] != selected:
                        raise ValueError('Selected annotation identity mismatch')
                    parents[kind] = {value for value in annotation[0]['parent_objects'] if value >= 0}
                    item[kind] = {'selected': selected, 'all_labels': sorted(by_class),
                                  'selected_overlap_seconds': by_class[selected],
                                  'another_class_has_strictly_longer_overlap': by_class[selected] + 1e-9 < max(by_class.values())}
                    if kind == 'sound':
                        item['selected_sound_source_visible'] = bool(annotation[0].get('is_visible', False))
                item['both_selected_annotations_have_known_parent_objects'] = bool(parents['action'] and parents['sound'])
                item['selected_annotations_share_known_parent_object'] = bool(parents['action'] & parents['sound'])
                records.append(item)
        report = {'sources': len(allocated), 'events': len(records), 'records': records}
        for kind in ('action', 'sound'):
            selected_mass, all_mass = Counter(), Counter()
            selected_sources, all_sources = defaultdict(set), defaultdict(set)
            for row in records:
                value = row[kind]
                selected_mass[value['selected']] += row['weight']
                selected_sources[value['selected']].add(row['source_id'])
                for label in value['all_labels']:
                    all_mass[label] += row['weight']
                    all_sources[label].add(row['source_id'])
            labels = sorted(map(int, source['ontology'][kind]))
            ordered = sorted(labels, key=lambda label: (-all_mass[label], label))
            constants = []
            for count in range(len(labels) + 1):
                selected_set = set(ordered[:count])
                metrics = [0.0, 0.0, 0.0]
                for row in records:
                    values = set_metrics(selected_set, set(row[kind]['all_labels']))
                    for i, value in enumerate(values): metrics[i] += row['weight'] * value
                constants.append({'label_count': count, 'labels': sorted(selected_set),
                                  'source_uniform_precision': metrics[0], 'source_uniform_recall': metrics[1],
                                  'source_uniform_f1': metrics[2]})
            best = max(constants, key=lambda value: value['source_uniform_f1'])
            report[kind] = {'selected_class_coverage': len(selected_sources), 'full_window_class_coverage': len(all_sources),
                'published_classes': len(labels),
                'full_window_class_support': {str(label): {'name': source['ontology'][kind][str(label)],
                     'original_videos': len(all_sources[label]), 'source_uniform_prevalence': all_mass[label],
                     'selected_original_videos': len(selected_sources[label]), 'selected_source_uniform_mass': selected_mass[label]}
                     for label in labels},
                'source_uniform_multiple_label_fraction': sum(row['weight'] for row in records if len(row[kind]['all_labels']) > 1),
                'source_uniform_nonlongest_selected_label_fraction': sum(row['weight'] for row in records if row[kind]['another_class_has_strictly_longer_overlap']),
                'constant_set_prefix_baseline_best_training_f1': best,
                'constant_set_prefix_baseline_grid': constants,
                'same_source_exact_window_agreement': finite_agreement(records, 'window_identity', kind)}
        if role == 'observer_train':
            for family, kind in [('s3d', 'action'), ('tsm', 'action'), ('pann', 'sound')]:
                report[family + '_exact_cached_row_agreement'] = finite_agreement(records, family + '_input_identity', kind)
            report['recorded_feature_cpu_seconds'] = {'sources': len(feature_cpu), 'sum': sum(feature_cpu),
                                                      'mean': sum(feature_cpu) / len(feature_cpu),
                                                      'scope': 'Per-source values recorded by historical extraction; excludes costs outside that measurement and is not a total end-to-end preparation bill.'}
        report['source_uniform_selected_sound_visible_fraction'] = sum(row['weight'] for row in records if row['selected_sound_source_visible'])
        report['source_uniform_both_selected_annotations_known_parent_fraction'] = sum(row['weight'] for row in records if row['both_selected_annotations_have_known_parent_objects'])
        report['source_uniform_selected_annotations_shared_known_parent_fraction'] = sum(row['weight'] for row in records if row['selected_annotations_share_known_parent_object'])
        roles[role] = report
    census = {}
    excluded = {row['source_id'] for row in source['selected']} | set(source['excluded_prior_video_ids'])
    register = Path(__file__).parent / 'data_source_usage_register.json'
    usage = json.loads(register.read_text())
    excluded.update(usage['host16_source_ids'])
    for kind in ('action', 'sound'):
        full, fresh = defaultdict(set), defaultdict(set)
        for source_id, row in annotations[kind].items():
            for entry in row[kind + '_localisation']:
                full[entry['label_id']].add(source_id)
                if source_id not in excluded: fresh[entry['label_id']].add(source_id)
        census[kind] = {'official_training_videos': len(annotations[kind]),
                        'official_training_class_coverage': len(full),
                        'unallocated_annotated_training_videos': len(set(annotations[kind]) - excluded),
                        'unallocated_training_class_coverage': len(fresh),
                        'class_original_video_counts': {str(label): {'all_training': len(full[label]),
                            'unallocated_training': len(fresh[label])} for label in sorted(map(int, source['ontology'][kind]))},
                        'scope': 'Annotation inventory only; no duration, maximum-source-byte, joint-window eligibility or media availability claim.'}
    result = {'schema': 'hepta.closure.training-only-observer-next-study-diagnostic.v1',
              'created_at_unix': time.time(), 'implementation_sha256': sha(Path(__file__)),
              'source_protocol_sha256': source['protocol_sha256'], 'source_protocol_file_sha256': sha(source_path),
              'training_annotation_sha256': pins, 'source_register_sha256': sha(register),
              'prepared_roles_read': ['observer_train'], 'annotation_splits_read': ['train'],
              'source_allocation_manifest_read_for_roles_and_exclusions': True,
              'new_training_updates': 0, 'development_or_holdout_media_or_predictions_read': False,
              'existing_study_file_modified': False, 'roles': roles, 'training_annotation_inventory': census,
              'training_feature_receipts': feature_receipts,
              'limits': ['Exact repeated-input agreement concerns only the inspected finite training table.',
                         'No label-multiplicity percentage proves a population top-one accuracy ceiling.',
                         'Shared annotation parent IDs do not establish acoustic causation.',
                         'Full-window sets and their training-only constant baselines describe a different proposed task; they do not replace the failed original top-one gate.',
                         'No candidate, threshold, source role, task or run is registered by this diagnostic.']}
    with output.open('x') as stream: stream.write(json.dumps(result, indent=2, sort_keys=True) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--assets', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = inspect_training(args.assets, args.output)
    summary = {role: {key: value for key, value in report.items() if key != 'records'}
               for role, report in result['roles'].items()}
    print(json.dumps({'output': str(args.output), 'bytes': args.output.stat().st_size,
                      'sha256': sha(args.output), 'roles': {role: {'sources': value['sources'],
                       'events': value['events'], 'action_classes': value['action']['full_window_class_coverage'],
                       'sound_classes': value['sound']['full_window_class_coverage']}
                      for role, value in summary.items()}}))
