"""Independent scope-limited check of the public Protocol reassignment repair."""
import hashlib
import json
from dataclasses import replace
from pathlib import Path
import platform
import shutil
import sys
import time

WORK = Path('/workspace/scratch/b5d58a60397e/memory-cell-work/qualification/memory-cell-v15')
HERE = Path(__file__).resolve().parent
SNAPSHOT = HERE / 'frozen-protocol-source'
SNAPSHOT.mkdir(exist_ok=True)
NAMES = ('admission.py', 'cohort.py', 'admission_test_support.py', 'isolated_runner.py')
source_before = {}
for name in NAMES:
    raw = (WORK / name).read_bytes()
    source_before[name] = {'sha256': hashlib.sha256(raw).hexdigest(),
                          'git_blob_sha1': hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),
                          'bytes': len(raw)}
    (SNAPSHOT / name).write_bytes(raw)
sys.path.insert(0, str(SNAPSHOT))
import admission
from admission import Case, Run, Protocol, MatchedEvaluator, budget_digest, digest
from admission_test_support import fixture_cost_protocol, fixture_ledger, fixture_registration

records = []
checks = []
worker_calls = []
real_run_arm = admission.run_arm

def record_arm(cases_wire, model, factory, deadline, **limits):
    observation = {'bundle': model.bundle, 'deadline_seconds': deadline, **limits}
    rows, receipt = real_run_arm(cases_wire, model, factory, deadline, **limits)
    observation.update(worker_status=receipt['status'], worker_pid=receipt['worker_pid'],
                       completed_rows=len(rows), cpu_seconds=receipt.get('cpu_seconds'),
                       peak_rss_bytes=receipt.get('peak_rss_bytes'))
    worker_calls.append(observation)
    return rows, receipt

admission.run_arm = record_arm


def require(condition, message):
    if not condition:
        raise ValueError(message)


def factory():
    return lambda choice, payload: payload if choice else None


def setup(*, looks=10000, all_gain=False):
    cases = [Case(str(i), str(i), 'retained', str(i), i, i) for i in range(256)]
    protocol = fixture_cost_protocol(Protocol('independent-frozen-protocol-review', True,
        256, .05, 1, .5, 16, 1., ('retained',), (('train_cpu_s', 1.),), (), looks,
        worker_cpu_seconds=5, worker_wall_seconds=10., worker_address_space_bytes=512*1024*1024))
    candidate = Run('candidate-frozen', 'memory', 'train', 'executor', budget_digest(protocol),
                    lambda q: True, 'encoder', 'decoder', 'tools')
    incumbent = replace(candidate, bundle='incumbent-frozen',
                        predict=(lambda q: False) if all_gain else (lambda q: int(q) < 192))
    registration = fixture_registration(cases, protocol, candidate, incumbent)
    evaluator = MatchedEvaluator(cases, factory, protocol, registration=registration)
    return evaluator, candidate, incumbent, protocol, registration


def run(evaluator, candidate, incumbent, ledgers=None):
    if ledgers is None:
        ledgers = [fixture_ledger(evaluator, model) for model in (candidate, incumbent)]
    before = len(worker_calls)
    result = evaluator.evaluate(candidate, incumbent, *ledgers,
        manifest={'bundle':candidate.bundle, 'memory':candidate.memory})
    return result, worker_calls[before:]


def brief(result):
    return {name:result[name] for name in ('approved','quality_qualified','resource_qualified',
        'economic_qualified','reasons','per_bound_alpha','paired_mean','paired_lower_bound',
        'protocol','protocol_settings','observed_protocol_settings','cohort_registration',
        'budget','workload','extra_cost_per_read','requests_per_arm')}


def same_envelope(calls, protocol):
    expected = {'deadline_seconds':protocol.deadline_seconds,
                'cpu_seconds':protocol.worker_cpu_seconds, 'wall_seconds':protocol.worker_wall_seconds,
                'address_space_bytes':protocol.worker_address_space_bytes}
    # Record cpu_limit separately: receipt CPU must not overwrite the dispatched limit.
    for call in calls:
        for key, value in expected.items():
            compare_key = 'dispatched_cpu_seconds' if key == 'cpu_seconds' else key
            require(call[compare_key] == value, 'arm envelope used changed '+key)
        require(call['worker_status'] == 'completed' and call['completed_rows'] == 256,
                'an arm did not complete its exact fixed case roster')
    require(len(calls) == 2 and len({x['worker_pid'] for x in calls}) == 2,
            'two distinct actual workers were not observed')

# Keep actual use and actual measured CPU under distinct names.
def record_arm(cases_wire, model, factory, deadline, **limits):
    observation = {'bundle':model.bundle, 'deadline_seconds':deadline,
                   'dispatched_cpu_seconds':limits['cpu_seconds'],
                   'wall_seconds':limits['wall_seconds'],
                   'address_space_bytes':limits['address_space_bytes']}
    rows, receipt = real_run_arm(cases_wire, model, factory, deadline, **limits)
    observation.update(worker_status=receipt['status'], worker_pid=receipt['worker_pid'],
                       completed_rows=len(rows), measured_cpu_seconds=receipt.get('cpu_seconds'),
                       peak_rss_bytes=receipt.get('peak_rss_bytes'))
    worker_calls.append(observation)
    return rows, receipt
admission.run_arm = record_arm

began = time.perf_counter()
report = {'schema':'hepta.memory.independent-frozen-protocol-review.v1',
          'source_before':source_before, 'checks':checks, 'observations':records,
          'scope':'Synthetic protocol controls using real bounded child interpreters. No neural-memory efficacy or production qualification.',
          'persistent_look_ledger_implemented':False,
          'python':sys.version, 'platform':platform.platform()}
try:
    e,c,i,p,registration = setup()
    baseline, calls = run(e,c,i)
    require(baseline['approved'] is False and baseline['quality_qualified'] is True,
            'original conservative-bound control is invalid')
    require(baseline['resource_qualified'] is True and baseline['paired_mean'] == .25,
            'baseline worker/cost condition is invalid')
    require(abs(baseline['per_bound_alpha'] - 2.5e-6) < 1e-15, 'baseline alpha differs')
    same_envelope(calls,p)
    records.append({'case':'original_10000_look_control', 'result':brief(baseline),'actual_worker_calls':calls})
    checks.append('original 10000-look conservative control and two real workers')

    e,c,i,p,registration = setup()
    binding_before = [e.cost_binding(model) for model in (c,i)]
    e.protocol = replace(e.protocol, planned_looks=1)
    require(binding_before == [e.cost_binding(model) for model in (c,i)], 'cost binding followed reassigned protocol')
    exact,calls = run(e,c,i)
    require(exact['approved'] is False and 'protocol_changed_after_freeze' in exact['reasons'],
            'original 10000-to-1 counterexample was not refused')
    require(exact['quality_qualified'] is False and exact['resource_qualified'] is True,
            'freeze refusal is masked by invalid resource fixtures')
    require(exact['protocol_settings'] == digest(vars(p)) == registration['protocol_settings'],
            'reported settings left the registered protocol')
    require(exact['observed_protocol_settings'] == digest(vars(e.protocol)) != exact['protocol_settings'],
            'observed changed settings not explicitly separated')
    require(exact['per_bound_alpha'] == baseline['per_bound_alpha']
            and exact['paired_lower_bound'] == baseline['paired_lower_bound'],
            'alpha or bound used a changed public protocol')
    same_envelope(calls,p)
    records.append({'case':'original_10000_to_1_regression', 'result':brief(exact),'actual_worker_calls':calls,
                    'cost_bindings_before_and_after_equal':True})
    checks.append('original 10000-to-1 reproduction is rejected with the frozen alpha/bound')

    e,c,i,p,registration = setup()
    old_bindings = [e.cost_binding(model) for model in (c,i)]
    changed = replace(p, identity='changed-after-freeze', planned_looks=1, alpha=.5,
        expected_reads=1024, deadline_seconds=17., worker_cpu_seconds=9,
        worker_wall_seconds=20., worker_address_space_bytes=2*1024*1024*1024,
        prices=(('train_cpu_s',2.),), limits=(('serve_cpu_s',1000.),('peak_rss_bytes',8*1024*1024*1024)),
        workload_digest='f'*64)
    e.protocol = changed
    require(old_bindings == [e.cost_binding(model) for model in (c,i)], 'frozen cost identity changed')
    varied,calls = run(e,c,i)
    require('protocol_changed_after_freeze' in varied['reasons'] and not varied['approved'],
            'changed joint policy was not refused')
    require(varied['budget'] == budget_digest(p) != budget_digest(changed), 'budget digest was reassigned')
    require(varied['workload'] == p.workload_digest != changed.workload_digest, 'workload identity was reassigned')
    require(varied['per_bound_alpha'] == baseline['per_bound_alpha'] and varied['protocol_settings'] == digest(vars(p)),
            'statistical settings were reassigned')
    same_envelope(calls,p)
    records.append({'case':'alpha_deadline_caps_cost_and_workload_reassignment', 'result':brief(varied),
                    'actual_worker_calls':calls,'cost_bindings_before_and_after_equal':True})
    checks.append('alpha, deadline, worker caps, workload, cost identity stay on one frozen protocol for both arms')

    forged = [fixture_ledger(e,model) for model in (c,i)]
    for ledger in forged:
        ledger.update(protocol=changed.identity, protocol_settings=digest(vars(changed)),
                      horizon_reads=changed.expected_reads, budget=budget_digest(changed),
                      workload=changed.workload_digest)
    refused,calls = run(e,c,i,forged)
    require(not refused['approved'] and not refused['resource_qualified'], 'rebound cost receipts were accepted')
    for arm in ('candidate','incumbent'):
        for field in ('protocol','protocol_settings','horizon_reads','budget','workload'):
            require(arm+'_cost_identity_mismatch:'+field in refused['reasons'], 'missing cost mismatch '+arm+'/'+field)
    same_envelope(calls,p)
    records.append({'case':'both_arm_cost_receipts_rebound_to_changed_protocol', 'result':brief(refused),
                    'actual_worker_calls':calls})
    checks.append('both arm receipts rebound to reassigned settings are rejected')

    e,c,i,p,registration = setup(looks=1,all_gain=True)
    old_bindings = [e.cost_binding(model) for model in (c,i)]
    def change_between_arms(*args,**kwargs):
        e.protocol = changed
        return record_arm(*args,**kwargs)
    admission.run_arm = change_between_arms
    during,calls = run(e,c,i)
    admission.run_arm = record_arm
    require(during['approved'] and during['protocol_settings'] == digest(vars(p)),
            'safe frozen execution changed after public mutation during dispatch')
    require(during['budget'] == budget_digest(p) and during['workload'] == p.workload_digest,
            'budget/workload changed during dispatch')
    require(old_bindings == [e.cost_binding(model) for model in (c,i)], 'cost binding changed during dispatch')
    same_envelope(calls,p)
    records.append({'case':'public_reassignment_during_dispatch_ignored_by_both_frozen_arms',
                    'result':brief(during),'actual_worker_calls':calls,
                    'note':'The start-of-call protocol was valid; both arms and all resulting bounds use that frozen protocol. No new protocol is activated.'})
    checks.append('public replacement during dispatch cannot change either arm or its cost/statistical settings')
    report['passed'] = True
except Exception as error:
    report.update(passed=False,error=type(error).__name__,reason=str(error))
finally:
    report['source_after'] = {name:{'sha256':hashlib.sha256((WORK/name).read_bytes()).hexdigest()} for name in NAMES}
    report['source_unchanged_during_review'] = all(source_before[n]['sha256']==report['source_after'][n]['sha256'] for n in NAMES)
    report['passed'] = report.get('passed',False) and report['source_unchanged_during_review']
    report['checks_completed'] = len(checks)
    report['wall_seconds'] = time.perf_counter()-began
    report['probe_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (HERE/'frozen-protocol-green.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('passed','checks_completed','source_unchanged_during_review','wall_seconds')},indent=2))
    if not report['passed']:
        print(report.get('error'),report.get('reason'))
        raise SystemExit(1)
