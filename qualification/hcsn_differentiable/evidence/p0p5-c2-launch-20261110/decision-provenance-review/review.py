"""Close the existing decision's finite-case count from retained evidence only."""
import hashlib
import json
import math
from pathlib import Path
import zipfile

BASE = Path('/workspace/scratch/c385a7439f8e')
OUT = Path(__file__).resolve().parent
archive = BASE / 'terminal-finite-first14-provenance-v1.zip'
digest = lambda raw: hashlib.sha256(raw).hexdigest()
assert digest(archive.read_bytes()) == '43c1529d054a89b9ad353cc429c326624bae8e707ff8e66bb1e12052d9797b0b'
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None and len(z.namelist()) == len(set(z.namelist()))
    manifest = json.loads(z.read('MANIFEST.json'))
    for entry in manifest:
        raw = z.read(entry['path'])
        assert len(raw) == entry['bytes'] and digest(raw) == entry['sha256']
    addendum_raw = z.read('addendum/RESULT.json')
    addendum = json.loads(addendum_raw)
    observer = json.loads(z.read('originals/00-RESULT.json'))
    plan = json.loads(z.read('originals/04-PLAN.json'))
    assert digest(z.read('originals/00-RESULT.json')) == addendum['original_observer_sha256']
    assert digest(z.read('originals/03-observe_terminal_audit_v1.py')) == observer['source_sha256']
    assert digest(z.read('originals/04-PLAN.json')) == addendum['plan_sha256'] == observer['plan_sha256']
    rows = {}
    for row in observer['rows']:
        if row['stage'].startswith('finite-') and row['status'] == 'completed':
            key = (row['name'], row['stage'])
            assert key not in rows
            rows[key] = (row['numerical'], row['result_sha256'], row['outer_sha256'],
                         row['wall_seconds'], row['CPU_seconds'], 'retained_original_observer_fields')
    assert len(rows) == 9
    for item in addendum['rows'][9:]:
        suffix = item['name'] + '__' + item['stage'] + '.json'
        member = next(n for n in z.namelist() if n.endswith(suffix))
        outer_suffix = item['name'] + '__' + item['stage'] + '-outer.json'
        outer_member = next(n for n in z.namelist() if n.endswith(outer_suffix))
        raw, outer_raw = z.read(member), z.read(outer_member)
        payload, outer = json.loads(raw), json.loads(outer_raw)
        assert digest(raw) == item['original_result_sha256'] == outer['result_sha256']
        assert digest(outer_raw) == item['original_outer_sha256']
        assert outer['returncode'] == 0 and outer['execution_status'] == 'completed' and outer['stop_cause'] is None
        assert payload['stage'] == item['stage'] and payload['execution_status'] == 'completed'
        assert payload['original_inputs_unchanged'] and payload['auditor_source_unchanged']
        assert payload['plan_sha256'] == payload['fixed_plan_sha256_after'] == addendum['plan_sha256']
        assert payload['input_receipt_sha256'] == payload['input_receipt_sha256_after']
        key = (item['name'], item['stage'])
        assert key not in rows
        rows[key] = (payload['result'], digest(raw), digest(outer_raw),
                     outer['whole_process_wall_seconds'], outer['waited_child_CPU_seconds'], 'complete_original_result_and_outer')
    expected = [(name, f'finite-best-{i}') for i in (0, 1) for name in plan['fit_roster']]
    expected += [(name, 'finite-best-2') for name in plan['fit_roster'][:2]]
    assert list(rows) == expected and len(rows) == 14
    for item in addendum['rows']:
        value, result_sha, outer_sha, wall, cpu, scope = rows[(item['name'], item['stage'])]
        assert value['status'] == item['original_numerical_status_value'] == 'passed_fixture'
        assert item['original_result_sha256'] == result_sha and item['original_outer_sha256'] == outer_sha
        assert item['original_outer_wall_seconds'] == wall and item['original_waited_stage_CPU_seconds'] == cpu
        assert item['primary_scaled_pass_is_derived_alias'] and item['original_numerical_status_field'] == 'result.status'
        a, b, errors = value['projected'], value['reference'], value['scaled_errors']
        assert len(a) == len(b) == len(errors) == 4
        assert all(math.isfinite(x) for x in a + b + errors)
        assert all(0 <= e <= .01 and abs(abs(x-y)/max(1,abs(y))-e) <= 1e-15 for x,y,e in zip(a,b,errors))
        assert 0 <= value['reference_refinement_delta'] <= 2e-8 and abs(value['mass_residual']) <= 5e-11
    wall = sum(r[3] for r in rows.values()); cpu = sum(r[4] for r in rows.values())
    assert wall == addendum['original_14_stage_outer_wall_seconds_nested_not_additional']
    assert cpu == addendum['original_14_waited_stage_CPU_seconds_nested_not_additional']
decision = BASE / 'c2-execution-decision-v1/DECISION.json'
assert digest(decision.read_bytes()) == 'bee192193f0f12599f783f348b6dea8c10b2a18df359487c3cc0c0c44d071370'
result = {'schema': 'independent-first14-decision-provenance-closure-v1',
          'archive_sha256': digest(archive.read_bytes()), 'archive_members': len(manifest) + 1,
          'addendum_RESULT_sha256': digest(addendum_raw),
          'verified_unique_original_passed_fixture_count': len(rows),
          'scope_counts': {'first9_retained_original_observer_fields': 9, 'later5_complete_original_result_outer': 5},
          'scope': 'Rechecked exact stored fields, per-case identities and scalar gate; no model/function/oracle/FD execution and no new full-original reads for the first nine cases.',
          'original_status_field': 'result.status', 'primary_scaled_pass_is_derived_alias': True,
          'nested_original_stage_cost_not_new_audit_cost': {'wall_seconds': wall, 'waited_CPU_seconds': cpu},
          'decision_count_provenance_open_item_closed': True,
          'decision_and_original_review_unchanged': True,
          'scientific_admission': 'HOLD', 'whole_training_domain_admission': 'HOLD'}
(OUT / 'RESULT.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
print(json.dumps(result, indent=2))
