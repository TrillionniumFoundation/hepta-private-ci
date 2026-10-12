"""Compare saved complete engines without importing a planner or neural model.

This checks same fixed policies and semantic results, not independence, calibrated
risk, native execution or a speed guarantee. Only declared work fields may differ.
"""
from pathlib import Path
from four_gate_common import digest, require, strict_loads
from fbsde_depth_audit import audit, MODES


def semantic_record(row):
    result = {k:row[k] for k in ('source_id','mode','holder','text','probabilities',
                                 'verifications','problem_sha256')}
    result['decisions'] = [{k:v for k,v in d.items() if k not in
                           ('cpu_ns','nodes','max_bsde_residual')} for d in row['decisions']]
    result['routes'] = [{k:v for k,v in d.items() if k not in
                        ('cpu_ns','planner_cpu_ns','one_step_cpu_ns','planner_nodes',
                         'one_step_nodes','planning_engine','workspace')} for d in row['routes']]
    return result


def compare_runs(original, reused):
    roots = [Path(original),Path(reused)]
    def read(root,name):
        path = root/(name+'.json')
        require(path.is_file() and not path.is_symlink() and path.stat().st_size < 64*1024*1024,
                'bounded complete comparison input')
        return strict_loads(path.read_bytes())
    for root in roots:
        require(not (root/'failure.json').exists(), 'failed run is not a complete comparison')
        audit(root)
    plans = [read(root,'plan') for root in roots]
    require([p.get('planning_engine','fresh_solve_v1') for p in plans] ==
            ['fresh_solve_v1','shared_continuation_v2'], 'explicit engine pair')
    for name in ('inputs','candidate-weights','calibration','priors','model-test'):
        require(read(roots[0],name) == read(roots[1],name), 'retrained or mismatched comparison '+name)
    # Per-run selection hashes include measured teacher CPU and necessarily differ.
    # Each was already validated above; compare the complete non-work teacher data.
    for split in ('train','selection','model_test'):
        teachers = [read(root,'teacher-'+split) for root in roots]
        def teacher_value(row):
            value = {k:v for k,v in row.items() if k not in ('one','two')}
            for stage in ('one','two'):
                value[stage] = {k:v for k,v in row[stage].items() if k != 'cpu_ns'}
            return value
        require([teacher_value(r) for r in teachers[0]] == [teacher_value(r) for r in teachers[1]],
                'comparison changed teacher information')
    routers = [read(root,'router') for root in roots]
    require(routers[0]['fit']['state'] == routers[1]['fit']['state'] and
            all({n:v for n,v in routers[0][k].items() if n != 'source_sha256'} ==
                {n:v for n,v in routers[1][k].items() if n != 'source_sha256'}
                for k in ('selected','heuristic','complete','complete_heuristic')),
            'comparison changed trained route or selected thresholds')
    summaries = {}; total = 0
    for mode in MODES:
        rows = [read(root,mode) for root in roots]
        require([semantic_record(r) for r in rows[0]] == [semantic_record(r) for r in rows[1]],
                'semantic decision changed '+mode)
        total += len(rows[0])
        costs = [sum(r['cpu_ns'] for r in group) for group in rows]
        summaries[mode] = {'outputs':len(rows[0]), 'controller_cpu_ns':costs,
            'semantic_sha256':digest([semantic_record(r) for r in rows[0]])}
    return {'compared_outputs':total,'paired_modes':summaries,'semantic_identity_verified':True,
            'same_machine_pair_is_not_latency_guarantee':True,'new_semantic_efficacy_claimed':False,
            'production_promotion_permitted':False}
