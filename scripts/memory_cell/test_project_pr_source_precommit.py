"""Source/label isolation regression tests: synthetic fixtures are NOT model evidence."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from project_pr_source_precommit import (
    CUT, PARTITIONS, SCHEMA, TYPES, audit, read_pinned, review_worklist, write_once
)


def fixture():
    result = dict(
        schema=SCHEMA, source_cut_utc=CUT,
        policy=dict(
            source_type="public-github-open-pull-requests",
            source_content="immutable_git_commit_trees_and_file_blob_refs",
            candidate_selection="two_updated_before_cut_per_project_fixed_before_review",
            full_code_and_human_label_not_in_this_manifest=True,
            published_source_pretraining_contamination_unknown=True,
            reopened_pr_chronology_not_certified=True,
        ),
        partitions=PARTITIONS, task_types=list(TYPES),
        no_answers_or_labels=True, independent_review_certified=False,
        prospective_outcomes_observed=False, task_improvement_established=False,
        model_executions=0, production_accepted=False,
        cases=[],
    )
    for i, (repo, partition) in enumerate(PARTITIONS.items()):
        for j in range(2):
            root=f'{i+1:040x}'
            number=(i+1)*100+j
            result['cases'].append(dict(
                repo=repo, partition=partition, pull_number=number,
                pull_url=f'https://github.com/{repo}/pull/{number}',
                title='Actual preregistered PR history',
                created_at='2026-10-09T00:00:00Z',
                last_updated_at='2026-10-11T00:00:00Z',
                state_at_capture='open',
                head_sha=root, tree_sha=f'{i+12:040x}',
                parents=[f'{i+13:040x}'],
                head_committed_at='2026-10-11T00:00:00Z',
                commits=[dict(sha=root, committed_at='2026-10-11T00:00:00Z', summary='Original commit')],
                files=[dict(path=f'src/file{j}.py',status='modified',blob_sha=f'{i+18:040x}',additions=2,deletions=1)],
                description_sha256='f'*64,
            ))
    return result


class FrozenProjectSourceGateTests(unittest.TestCase):
    def test_four_disjoint_project_families_with_eight_real_source_slots(self):
        self.assertEqual(audit(fixture())['partition_pr_counts'],dict(train=2,selection=2,evaluation=4))

    def test_review_form_never_emits_gold_or_model_decision(self):
        form=review_worklist(fixture())
        self.assertEqual(len(form['cases']),16)
        self.assertFalse(form['independent_semantic_review'])
        self.assertTrue(form['unsigned_only'])
        self.assertTrue(all(x['reviewer_verdict']=='unreviewed' and x['gold_answer_unavailable'] for x in form['cases']))
        self.assertTrue(all(x['source_commit_urls'] and x['original_file_refs'] for x in form['cases']))

    def test_answer_and_production_promotion_are_inadmissible(self):
        for k, value in [('no_answers_or_labels',False),('independent_review_certified',True),('model_executions',1),('production_accepted',True)]:
            m=fixture();m[k]=value
            with self.subTest(k=k),self.assertRaises(ValueError):audit(m)
        m=fixture();m['cases'][0]['gold']='invented';
        with self.assertRaises(ValueError):audit(m)

    def test_late_sources_and_commits_fail_closed(self):
        for path in ('last_updated_at','head_committed_at'):
            m=fixture();m['cases'][0][path]='2026-10-13T00:00:00Z'
            with self.subTest(path=path),self.assertRaises(ValueError):audit(m)
        m=fixture();m['cases'][0]['commits'][0]['committed_at']='2026-10-13T00:00:00Z'
        with self.assertRaises(ValueError):audit(m)

    def test_no_duplicate_reused_or_mispartitioned_pr(self):
        for change in ('clone','family','partition'):
            m=fixture()
            if change=='clone':m['cases'][1]=deepcopy(m['cases'][0])
            if change=='family':m['cases'][0]['repo']='numpy/numpy'
            if change=='partition':m['cases'][0]['partition']='evaluation'
            with self.subTest(change=change),self.assertRaises(ValueError):audit(m)

    def test_invalid_immutable_source_refs_and_paths(self):
        for name,value in [('head_sha','x'*40),('tree_sha','0'),('parents',['bad'])]:
            m=fixture();m['cases'][0][name]=value
            with self.subTest(name=name),self.assertRaises(ValueError):audit(m)
        for value in ('../../credentials','/private/path','src/a b.py'):
            m=fixture();m['cases'][0]['files'][0]['path']=value
            with self.subTest(path=value),self.assertRaises(ValueError):audit(m)
        m=fixture();m['cases'][0]['files']*=2
        with self.assertRaises(ValueError):audit(m)

    def test_exact_commit_chain_and_source_census(self):
        m=fixture();m['cases'][0]['commits'][0]['sha']='9'*40
        with self.assertRaises(ValueError):audit(m)
        m=fixture();m['cases'][0]['commits']+=deepcopy(m['cases'][0]['commits'][:])
        with self.assertRaises(ValueError):audit(m)
        m=fixture();m['cases'][0]['files']=[]
        with self.assertRaises(ValueError):audit(m)

    def test_sha_pin_and_strict_json_reject_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'original.json'
            write_once(p,fixture())
            good=sha256(p.read_bytes()).hexdigest()
            self.assertEqual(audit(read_pinned(p,good))['source_prs'],8)
            with self.assertRaises(FileExistsError):write_once(p,fixture())
            with self.assertRaises(ValueError):read_pinned(p,'f'*64)
            p.write_bytes(p.read_bytes().replace(b'"train"',b'"evaluation"',1))
            with self.assertRaises(ValueError):read_pinned(p,good)
            p.write_bytes(b'{"x":1,"x":2}')
            with self.assertRaises(ValueError):read_pinned(p,sha256(p.read_bytes()).hexdigest())


if __name__=='__main__':
    unittest.main()
