"""P5 pre-registered shared-baseline five-axis experiment completeness gate.

One common original task/source/model/seed/scorer and sixteen original trial IDs
form five overlapping four-level sweeps. Source-only structural enforcement is
not original publisher authentication or a prospective registration timestamp.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from scaling_frontier import LEVELS, AXES, validate_series, one_axis_sweeps, ScalingDenied, need, load

SCHEMA = 'hepta.p5.one-origin-five-axis-frozen-design.v1'
OUTPUT = 'hepta.p5.five-axis-observed-full-grid-descriptive.v1'
FIXED = ('logical_cells', 'active_cells', 'reasoning_depth', 'train_rows', 'compute_budget_ns')
PROVENANCE = ('arm', 'seed', 'source_sha256', 'held_label_sha256', 'evaluator_sha256',
              'stem_sha256', 'independent_source_groups', 'total')


def expected(design):
    need(type(design) is dict and set(design) == {
        'schema','authority_posture','production_accepted','teacher_equivalence_certified',
        'baseline','provenance','trial_ids'}, 'frozen design schema drift')
    need(design['schema'] == SCHEMA and design['authority_posture'] == 'DENY_ALL' and
         design['production_accepted'] is False and
         design['teacher_equivalence_certified'] is False,
         'design contains prohibited authority claim')
    baseline, provenance, trials = (design[x] for x in ('baseline','provenance','trial_ids'))
    need(type(baseline) is dict and set(baseline) == set(FIXED) and
         all(type(baseline[k]) is int and baseline[k] in LEVELS[k] for k in FIXED),
         'non-registered frozen baseline')
    need(type(provenance) is dict and set(provenance) == set(PROVENANCE),
         'incomplete original issuer/source/scorer identity')
    need(provenance['arm'] in ('shared_sparse', 'shared_unsplit', 'replicated_421m',
                              'fixed_top1', 'adaptive_split', 'distilled_group') and
         type(provenance['seed']) is int and provenance['seed'] >= 0 and
         type(provenance['independent_source_groups']) is int and
         provenance['independent_source_groups'] >= 1 and
         type(provenance['total']) is int and provenance['total'] >= 1,
         'invalid original arm/seed/denominator/groups')
    for name in ('source_sha256','held_label_sha256','evaluator_sha256','stem_sha256'):
        val = provenance[name]
        need(type(val) is str and len(val) == 64 and val != '0'*64 and
             all(c in '0123456789abcdef' for c in val),
             'invalid exact original source/scorer/model ' + name)
    need(provenance['independent_source_groups'] <= provenance['total'],
         'duplicated source evidence or fake denominator')
    # Exactly ONE common baseline and fifteen changed configurations; the
    # baseline is *reused* across all axes, never counted as five samples.
    keys = {'baseline': baseline.copy()}
    for axis in AXES:
        for v in LEVELS[axis]:
            if v == baseline[axis]:
                continue
            keys[f'{axis}={v}'] = {**baseline, axis:v}
    need(type(trials) is dict and set(trials) == set(keys) and
         len(set(trials.values())) == len(keys) and
         all(type(t) is str and 1 <= len(t) <= 128 for t in trials.values()),
         'missing, duplicated or posthoc remapped preregistered trial identities')
    return {trials[k]: {**v, **provenance, 'trial_id':trials[k]} for k,v in keys.items()}


def audit(design, original):
    keys = expected(design)
    rows = validate_series(original)
    need(len(rows) == len(keys) == 16, 'all sixteen original point observations required')
    got = {r['trial_id']:r for r in rows}
    need(set(got) == set(keys), 'missing/added/unregistered original trial')
    for name, record in got.items():
        for field, value in keys[name].items():
            need(record[field] == value, 'pre-registered baseline/identity changed: ' + field)
    descriptive = one_axis_sweeps(original)
    curves = descriptive['matched_one_axis_sweeps']
    need(len(curves) == 5 and set(r['swept_axis'] for r in curves) == set(AXES),
         'one of five full four-level original-source curves missing')
    for curve in curves:
        need(curve['levels'] == list(LEVELS[curve['swept_axis']]) and
             curve['source_sha256'] == design['provenance']['source_sha256'] and
             curve['arm'] == design['provenance']['arm'] and
             curve['seed'] == design['provenance']['seed'] and
             curve['quality_denominator'] == design['provenance']['total'],
             'uncoupled, cherry-picked or denominator-shifted learning curve')
    return {'schema':OUTPUT, 'authority_posture':'DENY_ALL',
            'production_accepted':False, 'model_selected':False,
            'design_sha256':sha256(json.dumps(design,sort_keys=True,separators=(',',':'),
                                          allow_nan=False).encode()).hexdigest(),
            'original_design_points':16, 'original_independent_source_groups':
                design['provenance']['independent_source_groups'],
            'shared_baseline_not_counted_five_times':True,
            'five_complete_one_axis_curves':curves,
            'prospective_registration_time_authenticated':False,
            'source_publisher_or_scorer_authenticated_externally':False,
            'independent_teacher_equivalence_certified':False,
            'ten_t_hundred_t_extrapolation_permitted':False,
            'whole_system_cost_pareto_qualified':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--frozen-design',required=True,type=Path)
    p.add_argument('--expected-design-sha256',required=True)
    p.add_argument('--original-observations',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args()
    need(not a.output.exists() and not a.output.is_symlink(), 'create-only output required')
    raw=a.frozen_design.read_bytes()
    need(0 < len(raw) < 500_000 and sha256(raw).hexdigest() == a.expected_design_sha256,
         'missing independently frozen preregistration digest')
    result=audit(load(a.frozen_design),load(a.original_observations))
    with a.output.open('xb') as f:
        f.write((json.dumps(result,sort_keys=True,allow_nan=False,separators=(',',':'))+'\n').encode())
    print('P5_COMPLETE_FIVE_AXIS_STRUCTURE_ONLY / NO_TEACHER_EQUIVALENCE / DENY_ALL')

if __name__ == '__main__':main()
