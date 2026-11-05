"""Independent bounded protocol review; synthetic controls, no efficacy claims."""
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys

BASE = Path('/workspace/scratch/b5d58a60397e/cohort-base/qualification/memory-cell-v15')
sys.path.insert(0, str(BASE))
from admission import Case, Run, Protocol, MatchedEvaluator, COSTS, digest
from admission_test_support import fixture_registration

cases = [Case(str(i), str(i), 'retained', str(i), i, i) for i in range(256)]
protocol = Protocol('independent-cohort-review', True, 256, .05, 1, .5, 16,
                    1., ('retained',), (('train_cpu_s', 1.),), (), 10000)
candidate = Run('candidate-frozen', 'memory', 'train', 'executor', 'budget', lambda q: True,
                'encoder', 'decoder', 'tools')
incumbent = replace(candidate, bundle='incumbent-frozen', predict=lambda q: int(q) < 192)
registration = fixture_registration(cases, protocol, candidate, incumbent)

def executor_factory():
    return lambda choice, payload: payload if choice else None

def costs(model, p):
    return {'bundle': model.bundle, 'protocol': p.identity, 'horizon_reads': p.expected_reads,
            'protocol_settings': digest(vars(p)), 'all_searches_and_failures_included': True,
            'resources': dict.fromkeys(COSTS, 0.)}

def evaluate(e, c=candidate, i=incumbent):
    return e.evaluate(c, i, costs(c, e.protocol), costs(i, e.protocol),
                      manifest={'bundle': c.bundle, 'memory': c.memory})

def brief(r):
    return {k:r[k] for k in ('approved','reasons','per_bound_alpha','paired_mean',
                             'paired_lower_bound','cohort_registration','protocol_settings',
                             'qualified_clusters','requests_per_arm')}

baseline = MatchedEvaluator(cases, executor_factory, protocol, registration=registration)
original = evaluate(baseline)
changed = MatchedEvaluator(cases, executor_factory, protocol, registration=registration)
changed.protocol = replace(changed.protocol, planned_looks=1)
changed_report = evaluate(changed)
assert original['approved'] is False
assert changed_report['approved'] is True
assert registration['protocol_settings'] != changed_report['protocol_settings']
assert changed_report['cohort_registration'] == digest(registration)

single = replace(protocol, planned_looks=1)
registered_single = fixture_registration(cases, single, candidate, incumbent)
repeated = MatchedEvaluator(cases, executor_factory, single, registration=registered_single)
repeated_reports = [evaluate(repeated) for _ in range(3)]
assert all(r['approved'] for r in repeated_reports)

clone = copy.deepcopy(registered_single)
expected_wire = digest(clone)
protected = MatchedEvaluator(cases, executor_factory, single, registration=clone)
clone['phases'].clear()
protected_report = evaluate(protected)
assert protected_report['approved'] and protected_report['cohort_registration'] == expected_wire

bad = copy.deepcopy(registered_single)
bad['final_units']['1']['unit'] = bad['final_units']['0']['unit']
duplicate = evaluate(MatchedEvaluator(cases, executor_factory, single, registration=bad))
assert not duplicate['approved']
assert 'replicated_source_unit:0' in duplicate['reasons']

# A new constructor accepts a newly declared roster after the old final cases
# have already been scored. The host, not this predicate, must prevent that.
new_candidate = replace(candidate, bundle='later-candidate')
new_roster = fixture_registration(cases, single, new_candidate, incumbent)
reused = evaluate(MatchedEvaluator(cases, executor_factory, single, registration=new_roster), new_candidate)
assert reused['approved']

result = {
 'schema':'hepta.memory.independent-cohort-review.v1',
 'reviewed_commit':'c8a8bdc5ef9ac060f2c6abf3dc7e561953f8b684',
 'source_sha256':{n:hashlib.sha256((BASE/n).read_bytes()).hexdigest() for n in ('admission.py','cohort.py','admission_test_support.py')},
 'scope':'Synthetic protocol counterexamples and positive controls only; no real-model efficacy sample.',
 'confirmed_bug':{
  'name':'cached registration accepts changed public protocol after freeze',
  'registered_planned_looks':10000,'evaluated_planned_looks':1,
  'original':brief(original),'after_public_protocol_reassignment':brief(changed_report),
  'cohort_still_binds_old_protocol_settings':registration['protocol_settings'],
  'requires_trusted_host_modification':True,
  'qualification':'Internal freeze-consistency bug; not an untrusted network authority bypass.'},
 'documented_missing_service_boundaries':{
  'planned_one_look_allows_same_instance_repeated_evaluation':{'approvals':sum(r['approved'] for r in repeated_reports),'evaluation_calls':len(repeated_reports),'per_bound_alpha':[r['per_bound_alpha'] for r in repeated_reports]},
  'newly_declared_candidate_roster_after_previous_final_evaluation':brief(reused),
  'meaning':'No persistent registration/consumption ledger exists in this predicate. Repeated evaluation is not itself evidence of an invalid bound for fixed deterministic outputs; adaptive selection or stochastic looks require an external durable monitor.'},
 'controls':{'nested_caller_registration_mutation_frozen':brief(protected_report),
             'duplicate_logical_source_unit_rejected':brief(duplicate)},
}
output=Path(__file__).with_name('review.json')
output.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
