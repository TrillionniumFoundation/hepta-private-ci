"""Record every prospective semantic grid cell and both strong-planner outputs."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal as D, localcontext
import hashlib
import json
from pathlib import Path
import platform
import time

from .semantics import backward, ce, duration_tree, exhaustive, pair, terminal_law


def run(output):
    here = Path(__file__).parent
    sources = sorted(here.glob('*.py'))+[here/'protocol.json']
    def hashes(): return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    frozen = json.loads((here/'freeze.json').read_text())
    before = hashes()
    if before != frozen['sha256']:
        raise ValueError('Audit source differs from pre-execution freeze')
    protocol = json.loads((here/'protocol.json').read_text())
    output.mkdir(parents=True, exist_ok=False)
    begin, cpu = time.perf_counter(), time.process_time()
    checks, rows = [], []
    def check(name, valid):
        if not valid: raise AssertionError(name)
        checks.append(name)
    with localcontext() as ctx:
        ctx.prec = protocol['decimal_precision']
        tolerance = D(protocol['equality_tolerance'])
        for eta in map(D, protocol['eta_values']):
            for gamma in map(D, protocol['gamma_values']):
                for p in map(D, protocol['success_probabilities']):
                    for duration in protocol['durations']:
                        graphs = pair(p, duration)
                        result = []
                        physical = []
                        for graph in graphs:
                            dynamic, choices, q = backward(graph, 'root', gamma, eta)
                            strong, policies = exhaustive(graph, 'root', gamma, eta)
                            legacy, legacy_choices, legacy_q = backward(graph, 'root', gamma, eta, 'fixed')
                            check('transport_matches_full_terminal_policy_enumeration', abs(dynamic-strong[0]) < tolerance)
                            check('transport_root_choice_matches_strong_baseline', choices[('root', 0)] == strong[1]['root'])
                            query_policy = {s: next(iter(actions)) for s, actions in graph.items()}
                            query_policy['root'] = 'probe'
                            physical.append(sorted(terminal_law(graph, 'root', query_policy, gamma)))
                            result.append({'transport_value':str(dynamic),'transport_choice':choices[('root', 0)],
                                'strong_value':str(strong[0]),'strong_choice':strong[1]['root'],
                                'fixed_local_value':str(legacy),'fixed_local_choice':legacy_choices[('root', 0)],
                                'transport_probe_value':str(q[('root', 0)]['probe']),
                                'fixed_local_probe_value':str(legacy_q[('root', 0)]['probe'])})
                        check('physical_transcripts_identical_after_forced_node_removal', physical[0] == physical[1])
                        check('transport_preserves_wait_refinement', abs(D(result[0]['transport_probe_value'])-D(result[1]['transport_probe_value'])) < tolerance)
                        if gamma == 1:
                            check('no_discount_fixed_local_refinement_equivalence', abs(D(result[0]['fixed_local_probe_value'])-D(result[1]['fixed_local_probe_value'])) < tolerance)
                        rows.append({'eta':str(eta),'gamma':str(gamma),'p':str(p),'duration':duration,
                                     'coarse':result[0],'refined':result[1],
                                     'same_physical_terminal_law':[[str(x) for x in event] for event in physical[0]]})
        representative = next(r for r in rows if D(r['eta'])==2 and D(r['gamma'])==D('.5') and D(r['p'])==D('.5') and r['duration']==1)
        check('representative_fixed_local_action_flip', representative['coarse']['fixed_local_choice']=='probe' and representative['refined']['fixed_local_choice']=='STOP')
        check('representative_paid_headroom_above_STOP', D(representative['coarse']['strong_value']) > D('.16'))
        uncertain = duration_tree()
        dynamic, choices, q = backward(uncertain, 'root', D('.5'), D(2))
        strong, _ = exhaustive(uncertain, 'root', D('.5'), D(2))
        check('random_duration_transport_equals_full_terminal_enumeration', abs(dynamic-strong[0])<tolerance)
        check('random_duration_probe_matches_direct_terminal_CE', abs(q[('root', 0)]['probe']-ce([(D('.08'),D('-.01')),(D('.32'),D('.49')),(D('.48'),D('-.01')),(D('.12'),D('.24'))],D(2)))<tolerance)
        mixed_trajectory = ce([(D('.5'),D(0)),(D('.5'),D(1))],D(2))
        check('action_randomization_outside_CE_is_different_objective', mixed_trajectory < D('.5'))
        details = {'representative':representative,
                   'paid_headroom_above_STOP':str(D(representative['coarse']['strong_value'])-D('.16')),
                   'matched_strong_planner_headroom':str(D(representative['coarse']['transport_value'])-D(representative['coarse']['strong_value'])),
                   'random_duration':{'dynamic_value':str(dynamic),'exhaustive_value':str(strong[0]),'root_choice':choices[('root',0)],'probe_value':str(q[('root',0)]['probe'])},
                   'action_lottery':{'outside_CE_value':'.5','trajectory_CE_value':str(mixed_trajectory)}}
    if hashes()!=before: raise ValueError('Source changed during execution')
    report={'schema':'ndu.clock-semantics.audit-result.v1','created_at_utc':datetime.now(timezone.utc).isoformat(),
            'protocol':protocol,'source_sha256':before,'freeze_sha256':hashlib.sha256((here/'freeze.json').read_bytes()).hexdigest(),
            'checks':checks,'check_count':len(checks),'all_pass':True,'rows':rows,'details':details,
            'grid_cells':len(rows),'matched_strong_baseline_difference_cells':sum(D(r[k]['transport_value'])!=D(r[k]['strong_value']) and abs(D(r[k]['transport_value'])-D(r[k]['strong_value']))>=D(protocol['equality_tolerance']) for r in rows for k in ['coarse','refined']),
            'fixed_local_action_flip_cells':sum(r['coarse']['fixed_local_choice']!=r['refined']['fixed_local_choice'] for r in rows),
            'wall_seconds':time.perf_counter()-begin,'cpu_seconds':time.process_time()-cpu,'python':platform.python_version(),
            'new_samples':0,'model_calls':0,'host_currency_cost':None,'formal_outward_rounding_claimed':False,
            'candidate_disposition':'REJECT_AS_NEW_ALGORITHM: clock transport matches the classical trajectory-CE planner; retain as a semantic guard',
            'external_review':False,'historical_results_rewritten':False}
    (output/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'grid_cells':len(rows),'checks':len(checks),'fixed_local_action_flips':report['fixed_local_action_flip_cells'],
                      'matched_strong_baseline_difference_cells':report['matched_strong_baseline_difference_cells'],
                      'paid_headroom_above_STOP':details['paid_headroom_above_STOP'],'disposition':report['candidate_disposition']}))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args().output)
