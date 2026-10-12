"""Hermetic soundness, exact budget, and full candidate census; no task efficacy claim."""
from fractions import Fraction
from itertools import combinations_with_replacement
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from system2_canonical_generation import canonical_successors
from system2_canonical_trial import BUDGETS, PROFILES, evaluate, run, solve_one, tasks
from system2_resumable_search import SearchSession
from system2_verified_search import digest, state_key, successors, verify


def counts():
    return dict(pair_checks=0, pair_skips=0, symmetry_skips=0, emitted=0)


class GenerationTests(unittest.TestCase):
    def test_all_local_numeric_successors_preserved_with_duplicates(self):
        for size in (2,3,4):
            for values in combinations_with_replacement(range(4), size):
                terms=tuple((Fraction(v), ('n'+str(i),)) for i,v in enumerate(values))
                before={state_key(c) for c in successors(terms)}
                after={state_key(c) for c in canonical_successors(terms, counts())}
                self.assertEqual(before, after)

    def test_counters_are_real_and_symmetric_duplicates_not_generated(self):
        terms=tuple((Fraction(2), ('n'+str(i),)) for i in range(4))
        c=counts()
        children=list(canonical_successors(terms,c))
        self.assertEqual(c['pair_checks'],6)
        self.assertEqual(c['pair_skips'],5)
        self.assertEqual(c['symmetry_skips'],2)
        self.assertEqual(c['emitted'],len(children))
        self.assertEqual(len(children),4)

    def test_generator_refuses_missing_counters(self):
        with self.assertRaises(ValueError):
            list(canonical_successors(((Fraction(2),()),(Fraction(2),())),{}))

    def test_default_search_equals_unchanged_existing_reference(self):
        for n in ((1,2,3,4),(1,3,4,6),(4,4,4,4),(6,6,7,9)):
            for budget in BUDGETS:
                self.assertEqual(solve_one(n,budget,'reference')['costs']['generated_successors'],
                                 SearchSession(n,24,'heuristic_search').advance(budget)['costs']['generated_successors'])

    def test_resumption_retains_same_canonical_proof(self):
        for n in ((1,2,3,4),(1,3,4,6),(4,4,4,4),(6,6,7,9)):
            for budget in BUDGETS:
                r=solve_one(n,budget,'canonical_pair')
                if r['found']:
                    self.assertTrue(verify(n,24,r['proof']))
                self.assertLessEqual(r['costs']['generated_successors'],budget)
                self.assertEqual(r['generation_filter']['emitted'],r['costs']['generated_successors'])

    def test_unknown_generator_profiles_fail_closed(self):
        for profile in ('canonical', 'none', '', None, 0):
            with self.assertRaises(ValueError):
                SearchSession((1,2,3,4),24,'heuristic_search',generation_profile=profile)

    def test_fixed_new_cohort_disjoint_without_oracle(self):
        groups=tasks()
        self.assertEqual(list(map(len,groups.values())),[204,48])
        self.assertFalse(set(groups['previous_204']) & set(groups['next_48_tasks']))
        all_ids=[digest(n) for x in groups.values() for n in x]
        self.assertEqual(len(all_ids),len(set(all_ids)))

    def test_real_runner_seals_and_keeps_full_counts(self):
        small={'previous_204':[(1,2,3,4)],'next_48_tasks':[(1,1,1,1)]}
        with tempfile.TemporaryDirectory() as tmp, patch('system2_canonical_trial.tasks',return_value=small):
            result=run(Path(tmp)/'run','a'*40)
            self.assertEqual((result['planned'],result['recorded'],result['failed']),(8,8,0))
            data=(Path(tmp)/'run'/'prediction-seal.json').read_text()
            self.assertIn('"posthoc_analysis_started": false',data)
            rows=[json.loads(x) for x in (Path(tmp)/'run'/'predictions.jsonl').read_text().splitlines()]
            with self.assertRaises(ValueError):
                evaluate(rows[:-1],small)
            with self.assertRaises(ValueError):
                evaluate(rows+rows[:1],small)
            rows[0]['status']='failed'
            rows[0].pop('found',None)
            summary=evaluate(rows,small)
            self.assertEqual(summary['failed'],1)
            self.assertEqual(summary['recorded'],8)

    def test_failed_full_trial_is_retained_not_replaced(self):
        small={'previous_204':[(1,2,3,4)],'next_48_tasks':[(1,1,1,1)]}
        with tempfile.TemporaryDirectory() as tmp, patch('system2_canonical_trial.tasks',return_value=small), patch(
                'system2_canonical_trial.solve_one',side_effect=RuntimeError('injected')):
            out=Path(tmp)/'failed'
            with self.assertRaises(RuntimeError):
                run(out,'b'*40)
            rows=(out/'predictions.jsonl').read_text().splitlines()
            self.assertEqual(len(rows),8)
            summary=json.loads((out/'summary.json').read_text())
            self.assertEqual(summary['failed'],8)


if __name__=='__main__':
    unittest.main()
