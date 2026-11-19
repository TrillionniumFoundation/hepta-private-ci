"""Score saved logits only; this script never fits, calibrates or runs a model."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scores(logits, labels):
    if len(logits) != 64 or len(labels) != 64 or any(len(row) != 11 for row in logits):
        raise ValueError('expected the unchanged 64-event, 11-class development fixture')
    bins = [{'count': 0, 'correct': 0, 'confidence_sum': 0.} for _ in range(15)]
    total_nll, total_brier, correct = 0., 0., 0
    for row, label in zip(logits, labels):
        if not all(math.isfinite(z) for z in row) or not 0 <= label < 11:
            raise ValueError('invalid logit or target')
        maximum = max(row)
        exponents = [math.exp(z - maximum) for z in row]
        normalizer = math.fsum(exponents)
        probabilities = [value / normalizer for value in exponents]
        prediction = max(range(11), key=lambda k: row[k])
        confidence = probabilities[prediction]
        hit = int(prediction == label)
        correct += hit
        total_nll += maximum + math.log(normalizer) - row[label]
        total_brier += math.fsum((p - int(k == label)) ** 2 for k, p in enumerate(probabilities))
        bucket = min(int(confidence * 15), 14)
        bins[bucket]['count'] += 1
        bins[bucket]['correct'] += hit
        bins[bucket]['confidence_sum'] += confidence
    ece = sum(abs(b['correct'] - b['confidence_sum']) for b in bins) / 64
    return {'accuracy': correct / 64, 'negative_log_likelihood': total_nll / 64,
            'multiclass_brier_sum': total_brier / 64,
            'brier_normalized_zero_one': total_brier / 128,
            'top_label_ece_15_equal_width': ece, 'ece_bin_sufficient_statistics': bins}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run = args.evidence / 'interface-001'
    data = json.loads((run / 'data/features.json').read_text())
    manifest = json.loads((run / 'data/data-manifest.json').read_text())
    suite = json.loads((run / 'suite.json').read_text())
    audit = json.loads((args.evidence / 'interface-001-audit/native-audit.json').read_text())
    if digest(run / 'data/features.json') != manifest['features_sha256'] or audit['failures']:
        raise ValueError('input identity or native audit failed')
    records = []
    for row in suite['attempts']:
        path = run / f"{row['arm']}-{row['seed']}" / 'development-logits.json'
        if digest(path) != row['dev_logits_sha256']:
            raise ValueError('saved development logits changed')
        score = scores(json.loads(path.read_text()), data['dev']['y'])
        residual = abs(score['negative_log_likelihood'] - row['development_cross_entropy'])
        if residual > 1e-12 or not all(0 <= score[k] <= 1 for k in
                    ('accuracy', 'brier_normalized_zero_one', 'top_label_ece_15_equal_width')):
            raise ValueError('metric identity/range validation failed')
        records.append({'arm': row['arm'], 'seed': row['seed'], 'scores': score,
            'logits_sha256': digest(path), 'nll_vs_native_cross_entropy_residual': residual,
            'trainable_parameters': row['trainable_parameters'],
            'training_interface_wall_seconds': row['wall_seconds'],
            'process_cpu_seconds': row['process_cpu_seconds'], 'peak_ram_bytes': row['peak_rss_bytes'],
            'missing_metrics': {
                'persistent_state_bytes': {'value': None, 'reason': 'No common retained-state instrumentation; official S4D FFT adapter exposes no streaming state.'},
                'p99_latency_seconds': {'value': None, 'reason': 'No warmed repeated latency benchmark was run.'},
                'inference_throughput_events_per_second': {'value': None, 'reason': 'Interface wall time includes imports, optimization, table builds and checkpoint I/O.'},
                'peak_vram_bytes': {'value': None, 'reason': 'GPU execution was prohibited; no VRAM peak counter was sampled.'},
                'complete_energy_joules': {'value': None, 'reason': 'No complete-system energy meter was available.'}}})
    report = {'schema': 'hcsn-localization-v2-metric-pipeline-check-v1',
        'status': 'passed_saved_logit_metric_check', 'training_or_model_forwards_in_this_check': 0,
        'formal_fits_started': 0, 'development_events': 64, 'class_count': 11,
        'train_event_label_counts': dict(Counter(data['train']['y'])),
        'development_event_label_counts': dict(Counter(data['dev']['y'])),
        'features_sha256': manifest['features_sha256'], 'frontend_sha256': manifest['frontend_sha256'],
        'suite_sha256': digest(run / 'suite.json'), 'scoring_script_sha256': digest(Path(__file__)),
        'definitions': {
            'accuracy': 'mean(argmax(logit)==label); first-index tie breaking',
            'negative_log_likelihood': 'mean(logsumexp(logits)-true_class_logit), natural-log nats',
            'multiclass_brier_sum': 'mean(sum over 11 classes of (probability-onehot_target)^2), range [0,2]',
            'brier_normalized_zero_one': 'multiclass_brier_sum / 2; not divided by class count',
            'top_label_ece_15_equal_width': 'sum count/N * abs(bin accuracy - mean top probability); [i/15,(i+1)/15), final bin includes 1',
            'calibration': 'raw softmax; no temperature or other calibration was fitted'},
        'claim_boundary': '64 development events, unequal tiny capacities and four updates per model only validate interfaces/metric arithmetic. No model ranking, SNN adequacy, generalization, statistical significance or performance conclusion.',
        'native_tensor_audit_status': audit['status'], 'records': records}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n')
    print(json.dumps({'status': report['status'], 'records': len(records),
                      'maximum_nll_residual': max(r['nll_vs_native_cross_entropy_residual'] for r in records),
                      'development_label_counts': report['development_event_label_counts']}))


if __name__ == '__main__':
    main()
