"""Metadata-only counterexamples, without model or numerical-function calls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from metadata_summary import classify_payload

root = Path(__file__).resolve().parent
payload = json.loads((root / 'fixture.json').read_bytes())
outer = json.loads((root / 'outer.json').read_bytes())
receipt = payload['input_receipt_sha256']
cases = [('unchanged_control', {})]
cases += [('actual_wall_exceeds_stage_grant', {'whole_process_wall_seconds': 901.0}),
          ('sampled_RSS_exceeds_fixed_cap', {'sampled_peak_RSS_bytes': 2147483649}),
          ('reported_outer_RSS_exceeds_fixed_cap', {'reported_child_peak_RSS_sample_bytes': 2147483649}),
          ('declared_outer_RSS_cap_changed', {'RSS_limit_bytes': 3221225472})]
rows = []
for name, change in cases:
    altered = deepcopy(outer)
    altered.update(change)
    result = classify_payload(payload, altered, receipt, True)
    rows.append({'case': name, 'outer_changes': change,
                 'qualified_named_finite_fixture': result['qualified_named_finite_fixture'],
                 'outer_gate': result['outer_completion_and_budget_gate_passed']})
assert rows[0]['qualified_named_finite_fixture'] is True
value = {'schema': 'postmortem-outer-budget-metadata-counterexample-v1',
         'scope': 'Copies of already saved JSON; no model, stage, oracle, or training execution.',
         'captured_sources': {p.name: {'bytes': p.stat().st_size,
             'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
             for p in sorted(root.iterdir()) if p.is_file() and p.name.endswith(('.py', '.json'))},
         'cases': rows,
         'invalid_outer_records_admitted': sum(r['qualified_named_finite_fixture'] for r in rows[1:])}
(root / 'RESULT.json').write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
print(json.dumps(rows, indent=2))
