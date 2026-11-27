"""Standard-library hash, shape, conservation and arithmetic review of actual originals."""

from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import struct


HERE = Path(__file__).parent
EVIDENCE = HERE/'evidence/erlang-compression-20261119/attempt001'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def count(value):
    return sum(count(x) for x in value) if isinstance(value,list) else 1


def review():
    campaign = json.loads((EVIDENCE/'REPORT.json').read_text())
    config = campaign['config']
    frozen = json.loads((HERE/'ERLANG_FREEZE.json').read_text())['files']
    assert campaign['source_sha256_before'] == campaign['source_sha256_after'] == frozen
    assert frozen == {name:sha(HERE/name) for name in frozen}
    assert campaign['total_cpu_seconds'] < config['limits']['total_cpu_seconds']
    assert campaign['wall_seconds'] < config['limits']['total_wall_seconds']
    identities = [(t,k) for t in config['times'] for k in config['stages']]
    assert len(campaign['cases']) == len(identities) == 20
    rows, files = [], {'REPORT.json':sha(EVIDENCE/'REPORT.json')}
    for item,(target,stages) in zip(campaign['cases'],identities):
        assert (item['target'],item['stages']) == (target,stages)
        path = EVIDENCE/item['child_result']
        files[path.name] = sha(path)
        assert files[path.name] == item['child_result_sha256']
        actual = json.loads(path.read_text())
        assert actual['source_sha256_before'] == actual['source_sha256_after'] == frozen
        assert item['status'] == actual['status'] == 'completed' and item['returncode'] == 0
        assert item['full_process_wall_seconds'] < config['limits']['case_wall_seconds']
        assert actual['rlimit_as'] == [config['limits']['address_space_bytes']]*2
        assert set(actual['thread_environment'].values()) == {'1'}
        assert actual['torch_threads'] == actual['torch_interop_threads'] == 1
        assert actual['all_values_and_gradients_finite'] and not actual['original_complete_kernel_imported']
        n = stages+1
        matrix = [[0.]*n for _ in range(n)]
        for i,j,value in actual['structure']['generator_nonzero_entries']:
            assert matrix[i][j] == 0
            matrix[i][j] = value
        lam,nu = config['rate'],float(Fraction(stages)/Fraction(config['delay_mean']))
        assert matrix[0][:2] == [-lam,lam] and math.fsum(matrix[0]) == 0
        for i in range(1,n):
            assert matrix[i][i] == -nu and matrix[i][0 if i==stages else i+1] == nu
            assert math.fsum(matrix[i]) == 0
        assert hashlib.sha256(struct.pack('<'+'d'*(n*n),*(x for row in matrix for x in row))).hexdigest() == actual['structure']['generator_fp64_sha256']
        state = actual['complete_state']
        sizes = {name:8*count(value) for name,value in state.items()}
        assert sizes == actual['state_tensor_bytes_by_field']
        assert sum(sizes.values()) == actual['state_tensor_bytes'] == 16*stages+104
        assert actual['physics_tensor_bytes'] == sum(actual['physics_tensor_bytes_by_field'].values()) == 8*(n*n+2*n+3)
        assert actual['work'] == {'explicit_exponentials':2,'largest_matrix':n+2,'augmented_input_bytes':[8*(n+2)**2]*2}
        assert state['upper'] == [0.,0.] and state['value'] == state['discounted_hits']
        conserved = [math.fsum([*state['active'][i],*state['phase'][i],state['upper'][i]])-mark
                     for i,mark in enumerate(config['marks'])]
        reference = actual['deterministic_reference_80_digits']
        for values_key,reference_keys,error_key in (
            ('values',('values_probability','values_content'),'value_signed_errors'),
            ('gradients',('gradients_probability','gradients_content'),'gradient_signed_errors')):
            expected_errors = [[value-float(ref) for value,ref in zip(values,reference[key])]
                               for values,key in zip(actual[values_key],reference_keys)]
            assert expected_errors == actual[error_key]
        maximum_value = max(abs(x) for row in actual['value_signed_errors'] for x in row)
        maximum_gradient = max(abs(x) for row in actual['gradient_signed_errors'] for x in row)
        assert maximum_value == actual['maximum_value_absolute_error']
        assert maximum_gradient == actual['maximum_gradient_absolute_error']
        rows.append({'target':target,'stages':stages,'max_value_abs_error':maximum_value,
                     'max_lambda_gradient_abs_error':maximum_gradient,'probability_value_signed_errors':actual['value_signed_errors'][0],
                     'probability_gradient_signed_errors':actual['gradient_signed_errors'][0],
                     'independent_conservation_errors':conserved,'dynamic_tensor_bytes':sum(sizes.values()),
                     'physics_tensor_bytes':actual['physics_tensor_bytes'],
                     'forward_seconds':actual['forward_seconds'],'backward_six_scalar_seconds':actual['backward_seconds'],
                     'whole_child_peak_rss_kib':actual['peak_rss_native_kib'],
                     'release_before_half_mean':actual['erlang_release_before_half_mean']})
    return {'status':'RETAINED_ORIGINALS_HASH_AND_ARITHMETIC_REVIEWED','scientific_gate_passed':False,
            'new_model_calls':0,'new_matrix_exponentials':0,'review_source_sha256':sha(Path(__file__)),
            'frozen_execution_source_sha256':frozen,'original_files_sha256':files,'rows':rows,
            'all_twenty_actual_cases_completed':True,'old_gates_changed':False,
            'max_independent_conservation_error':max(abs(x) for r in rows for x in r['independent_conservation_errors']),
            'cost_comparison_to_archived_full_state_is_same_batch':False,
            'unverified_scope':'Other cumulative observables, varying inputs/reset metadata, continuum diffusion, and task benefit.'}


if __name__ == '__main__':
    result = review()
    output = EVIDENCE.parent/'REVIEW.json'
    with output.open('x') as stream:
        json.dump(result,stream,sort_keys=True,allow_nan=False);stream.write('\n')
    print(json.dumps({'status':result['status'],'cases':len(result['rows']),
                      'max_independent_conservation_error':result['max_independent_conservation_error']}))
