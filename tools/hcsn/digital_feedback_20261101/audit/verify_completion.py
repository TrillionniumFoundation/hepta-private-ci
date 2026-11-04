"""Check frozen primary intervals using direct scalar mean/variance formulas."""
import argparse
import gzip
import hashlib
import json
import math
import sys
from pathlib import Path
import numpy as np
import scipy
from scipy.stats import t


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    packed = args.inputs.read_bytes()
    data = json.loads(gzip.decompress(packed))
    analysis = json.loads((args.output / 'ANALYSIS.json').read_text())
    record = json.loads((args.output / 'CONFIRMATION_COMPLETION_AUDIT.json').read_text())
    rows = {(x['fit'], x['split'], x['candidate']): x['metrics']['utility'] for x in data['summary_rows']}
    checks = []
    for item in analysis['primary']:
        values = [sum(w * rows[fit, item['split'], arm] for arm, w in item['weights'].items()) for fit in data['protocol']['fits']]
        assert len(values) == 32
        mean = sum(values) / 32
        variance = sum((value - mean) ** 2 for value in values) / 31
        half_width = float(t.ppf(1 - .05 / 8, 31)) * math.sqrt(variance / 32)
        expected = [mean - half_width, mean + half_width]
        residual = max(abs(a - b) for a, b in zip(expected, item['inference']['confidence_interval']))
        assert residual < 1e-14
        checks.append(dict(split=item['split'], contrast=item['contrast'], independent_mean=mean, independent_interval=expected, maximum_difference=residual))
    assert analysis['acceptance'] is False
    assert analysis['required_candidate_fit_domain_passes'] == 0
    assert len(analysis['primary']) == 4 and len(analysis['secondary']) == 34
    assert record['verification']['passed'] and record['verification']['violation_count'] == 0
    assert len(record['archives']) == 37
    assert sum(x['members'] for x in record['archives']) == 30735
    assert sum(x['archive_bytes'] for x in record['archives']) == 179515856
    assert abs(sum(x['known_measured_cpu_seconds'] for x in record['phase_costs']) - 8326.229650133) < 1e-9
    assert [x['phase'] for x in record['phase_costs'] if x['controller_self_cpu_seconds'] is None] == ['development_001', 'development_002', 'training_001']
    result = dict(source_commit=analysis['source_commit'], input_transport_sha256=hashlib.sha256(packed).hexdigest(), passed=True, independent_primary_checks=checks, asserted_report_counts=True, python=sys.version.split()[0], numpy=np.__version__, scipy=scipy.__version__, scope='Direct scalar mean/sample-variance/Student-t computation from all256 primary summary rows; no project statistics implementation invoked in this check. Raw collection is separate.')
    (args.output / 'COMPLETION_FINALIZATION_CHECK.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(passed=True, maximum_interval_difference=max(x['maximum_difference'] for x in checks))))


if __name__ == '__main__':
    main()
