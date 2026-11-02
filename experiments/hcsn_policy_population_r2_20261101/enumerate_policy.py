"""Exact finite-law aggregate reliability of the unchanged R2 visible-state hash.

This enumerates a mathematical finite sampling law, not PRNG seeds, new test
episodes, a new policy, or a neural mechanism. Completed R2 artifacts stay
immutable. All rational statements depend on the stated without-replacement,
uniform one-WRITE-erasure law.
"""
import ast
from fractions import Fraction
import hashlib
import itertools
import json
from pathlib import Path
import time

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
POSTERIOR=ROOT/'experiments/hcsn_missing_reliability_r2_20261101/posterior.py'
LAW=ROOT/'experiments/hcsn_four_stage_flow_20261031/synthetic_data.py'
CANDIDATE=ROOT/'experiments/hcsn_missing_reliability_r2_20261101/results/run001/CANDIDATE.json'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    started=time.process_time();source=POSTERIOR.read_text();tree=ast.parse(source)
    salt=next(ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign)
              and any(isinstance(t,ast.Name) and t.id=='SALT' for t in node.targets))
    owner=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='VisiblePosterior')
    forward=next(n for n in owner.body if isinstance(n,ast.FunctionDef) and n.name=='forward')
    assert [n.arg for n in forward.args.args]==['self','x','dt','observed']
    assert not ({'y','target_available','dependencies','world_id','split','seed'} & {n.id for n in ast.walk(forward) if isinstance(n,ast.Name)})
    hash_assignment=next(n for n in ast.walk(forward) if isinstance(n,ast.Assign)
        and any(isinstance(t,ast.Name) and t.id=='coin' for t in n.targets))
    assert {n.id for n in ast.walk(hash_assignment.value) if isinstance(n,ast.Name)}=={'int','hashlib','SALT','self','state'}
    q=json.loads(CANDIDATE.read_text())['q'];assert .5<q<1
    accepted=total=states=0;by_query_key=[0]*4;by_update_key=[0]*4;digest=hashlib.sha256()
    for original in itertools.permutations(range(8),4):
        unseen=sorted(set(range(8))-set(original))
        for updated_key in range(4):
            for fresh in unseen:
                updates=[255]*4;updates[updated_key]=fresh;states+=1
                for query in sorted(set(range(4))-{updated_key}):
                    # This is byte-identical to int8[-1]->uint8[255] in the
                    # frozen source: Selective has no aliases and no initial erasure.
                    state=bytes(original)+bytes(updates)+bytes([255]*4)+bytes([query,0,1])
                    coin=int.from_bytes(hashlib.blake2b(salt+b'selective'+state,digest_size=8).digest(),'big')
                    decision=coin<2**62;accepted+=decision;total+=1
                    by_query_key[query]+=decision;by_update_key[updated_key]+=decision
                    digest.update(state+bytes([decision]))
    assert states==1680*4*4==26880 and total==states*3==80640
    fraction=Fraction(accepted,total)
    accuracy=(8+2*fraction)/(8+3*fraction)
    known_coverage=(8+2*fraction)/10
    overall_coverage=(8+3*fraction)/12
    result=dict(schema='hcsn.r2.exact-finite-policy-population.v1',
        source_sha256={str(p.relative_to(ROOT)):sha(p) for p in [POSTERIOR,LAW,CANDIDATE,Path(__file__)]},
        frozen_policy_q=q,policy_changed=False,new_confirmation_draws=0,
        law='Four distinct original values sampled uniformly from eight; Selective updates two distinct uniformly selected keys with two fresh distinct values; erase one of six WRITE events uniformly, independently of values; score each of four keys once',
        hash_free_fields=['ordered visible initial values by key','ordered visible update values by key','ordered visible B-to-A alias map','current A query key','counts of initial/final missing WRITE slots','declared task and fixed salt'],
        canceled_freedoms=dict(task='Selective so aliases are all255',query_order='Each key is queried once; hash uses the current key, no query index',
            prelude_order='Initial/update maps canonicalize by key; positions within each registered stage do not enter hash',
            distractors='Typed DISTRACTOR events do not change these maps',time='Clocks never enter hash',
            hidden_completion='Erased final key and fresh value do not enter the visible state or hash',
            erasure_position='Either final update can be erased; both yield the same visible-state law and missing_final=1'),
        conditional_visible_states=states,ambiguous_state_query_pairs=total,accepted_ambiguous_pairs=accepted,
        rejected_ambiguous_pairs=total-accepted,accepted_by_query_key=by_query_key,accepted_by_observed_update_key=by_update_key,
        enumeration_sha256=digest.hexdigest(),accepted_fraction=dict(exact=str(fraction),decimal=float(fraction)),
        derivation=[
            'Conditional on a final-update erasure: each visible initial assignment, observed update key and observed fresh value has equal weight; three possible erased keys and three possible missing fresh values remain, independently of the hash.',
            'A given ambiguous query retains its old value and remains available with probability2/3. Its accepted subset therefore has correctness2/3, not95%.',
            'Initial erasures occur with probability4/6. Half are later overwritten, producing4 certain answers; half leave3 certain answers plus one rejected initial-unknown query. Thus this branch contributes mean3.5 certain accepted/available answers.',
            'Final erasures occur with probability2/6. They produce1 certain accepted answer,3 ambiguous queries, and3 available targets. If hash acceptance fraction is a, accepted count is1+3a and accepted correct/available count is1+2a.',
            'Across all four queries, expected accepted correctness=(8+2a)/(8+3a), known-answer coverage=(8+2a)/10, total acceptance coverage=(8+3a)/12.'
        ],
        selective_missing=dict(accepted_correctness=dict(exact=str(accuracy),decimal=float(accuracy)),
            known_answer_coverage=dict(exact=str(known_coverage),decimal=float(known_coverage)),
            overall_query_coverage=dict(exact=str(overall_coverage),decimal=float(overall_coverage)),
            accepted_ambiguous_correctness=dict(exact='2/3',decimal=2/3)),
        population_gate=dict(accepted_correctness_at_least_95_percent=accuracy>=Fraction(95,100),
            known_answer_coverage_at_least_80_percent=known_coverage>=Fraction(80,100),
            conditional_ambiguous_95_percent=False),
        other_conditions='MQAR/Binding one-erasure accepted answers are certain with known coverage1; nonmissing four-query correctness1; registered typed filler128 does not affect the canonical state or hash',
        scope_limits=['Exact finite uniform sampling-law calculation, not a distribution over all PCG seeds',
            'Ordinary shared task-law readout; learned-neural and analytic-core increments remain unestablished',
            'Aggregate reliability does not imply95 percent correctness for each accepted answer',
            'No multiple erasures, shifted/unknown laws, READ repair, resampling, open-domain, hardware or production qualification'],
        body_cpu_seconds=time.process_time()-started,all_blockers_closed=False,production_activation=False)
    with (HERE/'POPULATION.json').open('x') as stream:
        json.dump(result,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')
    print(json.dumps({k:result[k] for k in ['conditional_visible_states','ambiguous_state_query_pairs','accepted_ambiguous_pairs','accepted_fraction','selective_missing','population_gate']},sort_keys=True))


if __name__=='__main__':main()
