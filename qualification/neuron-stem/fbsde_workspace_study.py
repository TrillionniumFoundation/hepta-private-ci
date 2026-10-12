"""Shared numerical continuation and verified decision workspaces; same study entry.

All task candidates precede solving. Repetitions measure CPU, not independent
semantic outcomes. No text Encoder or learned language reasoning is claimed.
"""
from dataclasses import asdict
import hashlib
from pathlib import Path
import platform
import random
import time

from four_gate_common import digest, write_once, require
from fbsde_coupled import CoupledProfile
from fbsde_continuation import TARGET, compile_bank, load_bank
from fbsde_workspace import choose_candidate

MODES = ('cold_all','warm_all','verified_search')
BINDING = {'scope':'numerical-workspace','generation':1,'objective':digest(TARGET)}


def run(output):
    root = Path(output); root.mkdir(parents=True,exist_ok=False)
    started = time.process_time_ns(); cases = []
    rng = random.Random(65537)
    for a in (.55,.75):
        for steps in (5,8,10):
            p = CoupledProfile(a=a,steps=steps)
            for task in range(8):
                candidates = []
                for i in range(8):
                    x = rng.uniform(-.9,.9)
                    candidates.append({'id':f'candidate-{i}','x0':x,'cost':.9+.8*x+rng.uniform(-.12,.12)})
                cases.append({'id':f'{a}:{steps}:{task}','profile':asdict(p),'candidates':candidates})
    names = ('fbsde_coupled.py','fbsde_riccati.py','fbsde_continuation.py','fbsde_workspace.py',
             'fbsde_workspace_study.py','fbsde_workspace_audit.py','fbsde_riccati_audit.py','four_gate_common.py','fbsde_study.py')
    plan = {'schema':'hepta.fbsde.workspace-study.v1','cases':cases,'methods':MODES,'seed':65537,
            'repeats':3,'anchors':[-1.,0.,1.],'gap_tolerance':1e-8,'binding':BINDING,
            'sources':{n:hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in names},
            'platform':platform.platform(),'equation_target':TARGET,
            'synthetic_numerical_tasks_not_semantic_evidence':True,'production_promotion_permitted':False}
    write_once(root/'design.json',plan)
    banks = {}; prep = []; outputs = []; timings = []
    for case in cases:
        p = CoupledProfile(**case['profile']); key = digest(case['profile'])
        if key not in banks:
            cpu, wall = time.process_time_ns(),time.perf_counter_ns()
            b = compile_bank(p,plan['anchors'],**BINDING)
            payload = {**b.payload(),'sha256':b.identity}
            b = load_bank(payload,**BINDING)
            prep.append({'profile_sha256':key,'bank_sha256':b.identity,
                         'cpu_ns':time.process_time_ns()-cpu,'wall_ns':time.perf_counter_ns()-wall,
                         'stored_scalar_count':sum(1+len(y)+len(d) for _,y,d in b.anchors)})
            banks[key] = b
            write_once(root/f'bank-{key}.json',payload)
        kept = {}
        for repeat in range(plan['repeats']):
            order = list(MODES); random.Random(f"{plan['seed']}:{case['id']}:{repeat}").shuffle(order)
            for position,mode in enumerate(order):
                cpu, wall = time.process_time_ns(),time.perf_counter_ns()
                result = choose_candidate(p,case['candidates'],banks[key],mode=mode,**BINDING)
                cpu, wall = time.process_time_ns()-cpu,time.perf_counter_ns()-wall
                require(result['status'] == 'resolved', 'registered numerical decision unresolved')
                if repeat == 0: kept[mode] = result
                require(result == kept[mode], 'deterministic workspace output drift')
                timings.append({'case_id':case['id'],'method':mode,'repeat':repeat,'position':position,
                                'cpu_ns':cpu,'wall_ns':wall,'output_sha256':digest(result)})
        outputs.append({'id':case['id'],'methods':kept})
    for name,data in [('outputs',outputs),('timings',timings),('preparation',prep)]:
        write_once(root/f'{name}.json',data)
    totals = {m:sum(t['cpu_ns'] for t in timings if t['method']==m) for m in MODES}
    preparation = sum(t['cpu_ns'] for t in prep)
    raw_wrong = sum(max(o['methods']['verified_search']['rows'],key=lambda r:r['initial_score'])['candidate']['id']
                    != o['methods']['cold_all']['selected'] for o in outputs)
    summary = {'schema':'hepta.fbsde.workspace-results.v1','outputs_sha256':digest(outputs),
               'timings_sha256':digest(timings),'preparation_sha256':digest(prep),'query_cpu_ns':totals,
               'standalone_component_cpu_ns':{m:v+(0 if m=='cold_all' else preparation) for m,v in totals.items()},
               'unique_case_refinements':{m:sum(o['methods'][m]['refinements'] for o in outputs) for m in MODES},
               'raw_proposal_wrong_selections':raw_wrong,
               'verified_disagrees_with_complete_exact':sum(o['methods']['verified_search']['selected'] !=
                                                          o['methods']['cold_all']['selected'] for o in outputs),
               'cpu_envelope_ns':time.process_time_ns()-started,
               'preparation_charged_only_to_observed_calls':True,'full_native_lifecycle_measured':False,
               'continuous_time_or_roundoff_certified':False,'neural_encoder_executed':False,
               'semantic_reasoning_improvement_claimed':False,'production_promotion_permitted':False}
    write_once(root/'summary.json',summary)
    from fbsde_workspace_audit import audit
    write_once(root/'arithmetic-audit.json',audit(root))
    return summary
