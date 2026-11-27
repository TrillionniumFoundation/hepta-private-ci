"""Independent scalar/identity review of saved JSON; no numerical functions run."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

BASE = Path('/workspace/scratch/c385a7439f8e')
OUT = Path(__file__).resolve().parent
inputs = {}


def read(relative):
    data = (BASE / relative).read_bytes()
    inputs[relative] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    return data


original = json.loads(read('final-logrisk-original-v1/hcsn-s101-lr0.001-logrisk.json'))
summary = json.loads(read('six-logrisk-query-confirmation-v1/RESULT.json'))
r = original['result']
derivatives = [d for q in r['queries'] for d in q['derivatives']]
assert len(r['queries']) == 30 and len(derivatives) == 135
dispositions = Counter()
max_error = {'AD': 0.0, 'reference_FD': 0.0}
for d in derivatives:
    scale = max(1.0, abs(d['reference_derivative']))
    for field in ('AD', 'reference_FD', 'FP64_FD'):
        error = abs(d[field] - d['reference_derivative']) / scale
        assert math.isclose(error, d[field + '_scaled_error'], rel_tol=1e-12, abs_tol=1e-25)
        if field in max_error:
            max_error[field] = max(max_error[field], error)
    disposition = ('roundoff_limited_not_a_FD_pass'
                   if d['FP64_FD_roundoff_resolution_estimate'] > 3e-10
                   else 'disagrees_above_resolution' if d['FP64_FD_scaled_error'] > 3e-10
                   else 'passed_at_declared_resolution')
    assert d['FP64_FD_disposition'] == disposition
    dispositions[disposition] += 1
assert max(max_error.values()) <= 3e-10
assert dispositions['roundoff_limited_not_a_FD_pass'] == 96
assert dispositions['disagrees_above_resolution'] == 1
assert r['primary_passed'] is False
query = r['queries'][5]
failure = query['derivatives'][4]
assert failure['parameter_index'] == 4 and failure['primary_derivative_passed'] is False
verified_fragments = []
for fit in summary['fits']:
    if fit['read_scope'] == 'complete_original':
        assert fit['full_original_sha256'] == inputs['final-logrisk-original-v1/hcsn-s101-lr0.001-logrisk.json']['sha256']
        continue
    path = 'six-logrisk-query-confirmation-v1/' + fit['name'] + '-query.json'
    raw = read(path)
    assert inputs[path]['sha256'] == fit['query_raw_sha256']
    fragment = read('final-logrisk-six-originals-recovery-v1/' + fit['name'] + '/16384.bin')
    assert hashlib.sha256(fragment).hexdigest() == fit['fragment_sha256']
    start, end = fit['query_original_byte_range']
    assert fragment[start - 16384:end - 16384] == raw
    assert json.loads(raw) == query
    assert fit['original_summary_fields']['primary_passed'] is False
    verified_fragments.append(fit['name'])
assert len(verified_fragments) == 5
result = {
    'schema': 'independent-logrisk-stored-JSON-review-v1',
    'scope': 'One complete original 30-query/135-derivative report and five exact complete-query fragments. No new model, log-risk function, oracle, or finite differences executed.',
    'inputs': inputs,
    'derivative_count': len(derivatives),
    'ordinary_FP64_FD_dispositions_recomputed': dict(dispositions),
    'max_recomputed_scaled_errors': max_error,
    'all_recorded_AD_and_high_precision_FD_meet_original_gate': True,
    'original_primary_passed_preserved': False,
    'same_failure_query_verified_in_five_fragments': verified_fragments,
    'failing_query': query,
    'failure_AD_absolute_error': abs(failure['AD'] - failure['reference_derivative']),
    'failure_ordinary_FD_absolute_error': abs(failure['FP64_FD'] - failure['reference_derivative']),
    'center_log_error_ULPs': abs(query['log_probability'] - query['reference_log_probability']) / math.ulp(query['reference_log_probability']),
    'interpretation': 'The ordinary-FP64 finite-difference confirmation gate failed at the saved query. The ULP-based resolution estimate is not a total function-evaluation/truncation error bound. Center-point ULP error does not bound either finite-difference endpoint. AD and the saved 80-digit derivative references agree at this point; this result does not establish a wrong training gradient.',
    'five_full_original_reports_independently_read': False,
    'new_qualification_credit': False,
}
(OUT / 'RESULT.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
print(json.dumps({k: v for k, v in result.items() if k not in ('inputs', 'failing_query')}, indent=2))
