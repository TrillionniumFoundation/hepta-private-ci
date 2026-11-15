"""Read saved receipts only; no candidate/reference import or propagation."""
from pathlib import Path
from decimal import Decimal as D, localcontext
import hashlib
import json

ROOT = Path('/workspace/scratch/c06d659c1e72/currentstate-packets')
OUT = Path(__file__).resolve().parent
INPUTS = [ROOT/'evidence/currentstate-attempt001/SUMMARY.json',
          ROOT/'evidence/currentstate-attempt001/NEGATIVE_CONTROL.json',
          ROOT/'qualification/hcsn_currentstate/PLAN.json',
          ROOT/'qualification/hcsn_currentstate/audit.py',
          ROOT/'qualification/hcsn_currentstate/negative_control.py',
          ROOT/'qualification/hcsn_currentstate/packets.py',
          ROOT/'qualification/hcsn_currentstate/reference.py',
          ROOT/'qualification/hcsn_currentstate/SPEC.md']


def roster():
    return {str(p.relative_to(ROOT)): {'bytes': len(p.read_bytes()),
            'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in INPUTS}


def main():
    before = roster()
    s, negatives, plan = (json.loads(p.read_text()) for p in INPUTS[:3])
    candidate_calls = candidate_segments = reference_calls = gl_nodes = 0
    max_matrix = 0
    ledgers = []
    references = []
    for name, cost in s['cost'].items():
        for mode in ('fine', 'coarse', 'cold'):
            c = cost[mode]
            assert c['maximum'] == 500
            assert 0 <= c['expm_calls'] <= 500 and 0 <= c['segments'] <= 20
            assert 0 <= c['max_matrix'] <= 128
            candidate_calls += c['expm_calls']; candidate_segments += c['segments']
            max_matrix = max(max_matrix, c['max_matrix'])
            ledgers.append({'fixture': name, 'mode': mode, **c})
        assert [r['order'] for r in cost['reference']] == [32, 64]
        for r in cost['reference']:
            assert r['expm_calls'] <= 20000 and r['gl_nodes'] <= 2500
            reference_calls += r['expm_calls']; gl_nodes += r['gl_nodes']
            references.append({'fixture': name, **r})
    assert len(ledgers) == plan['fixed_max_ledgers'] == 6
    assert len(references) == 4
    assert 6*500 == plan['fixed_roster_hard_candidate_expm_upper_bound'] == 3000
    assert 6*20 == plan['fixed_roster_hard_segments_upper_bound'] == 120
    assert candidate_calls <= 3000 <= plan['max_candidate_expm_calls']
    assert candidate_segments <= 120 <= plan['max_candidate_segments']
    assert reference_calls <= 80000 <= plan['max_reference_expm_calls']
    assert gl_nodes <= 10000 == plan['max_reference_gl_nodes']
    cpu_hard = plan['parent_cpu_soft_hard_seconds'][1] + 2*plan['each_cold_cpu_soft_hard_seconds'][1]
    assert cpu_hard == 173 < plan['cpu_seconds'] == 180
    assert s['wall_seconds'] < plan['hard_wall_seconds'] == 190
    decimal_receipts = []
    for row in negatives:
        dps = row['dps']
        with localcontext() as ctx:
            ctx.prec = dps + 60
            q, low, mid, high, t, rate = (D(x) for x in ('.15','.05','.1','.15','.075','2.5'))
            w = ((q*(high-mid)).exp()-1)/((q*(high-low)).exp()-1)
            z = (-q*mid).exp()
            active = w*(-rate*(t-low)).exp()
            hit = w*(D(2)/rate)*(1-(-rate*(t-low)).exp())
            threshold = D(10) ** (1-dps)
            assert row['law_A'] == {'times':['0.1'],'weights':['1']}
            assert row['law_B']['times'] == ['0.05','0.15']
            b0, b1 = (D(x) for x in row['law_B']['weights'])
            current = row['current']
            assert all(current[k] == '0' for k in ['active','upper','M','H','A'])
            assert current['R'] == '1' and row['future_time'] == '0.075'
            assert row['future_active_A'] == row['future_first_hit_A'] == '0'
            errors = {'weight0': abs(b0-w), 'weight1': abs(b1-(1-w)),
                      'weights_sum':abs(b0+b1-1), 'current_Z':abs(D(current['Z'])-z),
                      'same_Z_from_saved_weights':abs(b0*(-q*low).exp()+b1*(-q*high).exp()-D(current['Z'])),
                      'future_active_B': abs(D(row['future_active_B'])-active),
                      'future_first_hit_B':abs(D(row['future_first_hit_B'])-hit)}
            assert all(e <= threshold for e in errors.values())
            assert D(row['equal_Z_residual']) <= threshold
            assert 0 < b0 < 1 and 0 < b1 < 1 and active > 0 and hit > 0
            assert row['admission'] == 'totals_only_restore_is_insufficient'
            decimal_receipts.append({'dps':dps, 'decimal_precision':ctx.prec,
                'input_convention':'exact decimal rationals; mathematical counterexample',
                'saved_scalar_errors':{k:str(v) for k,v in errors.items()},
                'comparison_absolute_limit':str(threshold),
                'saved_equal_Z_residual':row['equal_Z_residual'],
                'future_active_B':row['future_active_B'],
                'future_first_hit_B':row['future_first_hit_B']})
    assert [r['dps'] for r in decimal_receipts] == [80,120]
    after = roster()
    assert before == after
    result = {'review_identity':'currentstate-cost-negative-readonly-001',
      'artifact_commit':'a9a7fc48d6c27636fc3b5c71065c1a33b7111807',
      'source_freeze_commit':s['source_freeze_commit'],
      'reviewer_execution':{'candidate_imports':0,'reference_imports':0,'scipy_imports':0,
        'expm':0,'quadrature':0,'model_runs':0,'scalar_decimal_exp_only':True},
      'input_roster_before':before,'input_roster_after':after,'unchanged':True,
      'cost':{'ledgers':ledgers,'references':references,
        'candidate_expm_calls':candidate_calls,'candidate_segments':candidate_segments,
        'reference_expm_calls':reference_calls,'reference_gl_nodes':gl_nodes,
        'max_recorded_augmented_dimension':max_matrix,
        'fixed_roster_hard_candidate_expm_upper_bound':3000,
        'fixed_roster_hard_candidate_segments_upper_bound':120,
        'fixed_roster_hard_reference_expm_upper_bound':80000,
        'fixed_roster_hard_reference_gl_upper_bound':10000,
        'fixed_roster_cpu_hard_upper_bound_seconds':cpu_hard,
        'saved_wall_seconds':s['wall_seconds'],
        'saved_parent_cpu_seconds':s['parent_cpu_seconds'],
        'saved_children_cpu_seconds':s['child_cpu_seconds'],
        'saved_sum_cpu_seconds':s['parent_cpu_seconds']+s['child_cpu_seconds'],
        'saved_parent_max_rss_KiB':s['max_rss_KiB'],
        'saved_parent_max_rss_MiB':s['max_rss_KiB']/1024,
        'memory_limit_interpretation':'RLIMIT_AS=536870912 per process, not total RSS; saved ru_maxrss is parent only; child RSS not recorded'},
      'negative_control_checks':decimal_receipts,
      'scope':'Saved real-coefficient phase-law counterexample supports insufficiency of scalar totals for future continuation. It is not an exact binary64 serialized-state collision or arbitrary model restore certificate.',
      'verdict':'No arithmetic discrepancy found in reviewed saved cost and negative-control data.'}
    (OUT/'REVIEW.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'verdict':result['verdict'],'candidate_expm':candidate_calls,
       'segments':candidate_segments,'reference_expm':reference_calls,'GL_nodes':gl_nodes,
       'negative_precisions':[r['dps'] for r in decimal_receipts],
       'unchanged':True,'review_path':str(OUT/'REVIEW.json')},sort_keys=True))


if __name__ == '__main__':
    main()
