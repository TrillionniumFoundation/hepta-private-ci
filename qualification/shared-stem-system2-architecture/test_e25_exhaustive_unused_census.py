"""E25 actual original admission-function tests on explicitly SYNTHETIC rows.

No true held human labels, pretrained model forwards or future source family.
The test deliberately imports the pinned original _group_inputs and _digest
rather than substituting a parallel eligibility approximation.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import unittest

from multirc_materials import _group_inputs
from next_round_matrix import _digest
from e25_unseen_material import exhaustive_unused_source_census


def six_original_shaped_passages(count=6):
    rows=[]
    for pid in range(count):
        paragraph=f'Unique original-shaped passage {pid}: a complete evidence paragraph.'
        for question in range(2):
            for answer in range(2):
                rows.append({
                    'idx':{'paragraph':pid,'question':question,'answer':answer},
                    'paragraph':paragraph,'question':f'What happened at {pid} item {question}?',
                    'answer':f'Option {answer} of item {question} in source {pid}.',
                    'label':answer,
                })
    return rows


class E25OriginalSourceCensus(unittest.TestCase):
    def test_exact_six_original_admission_passages(self):
        rows=six_original_shaped_passages()
        groups,stats=exhaustive_unused_source_census(rows)
        self.assertEqual(len(groups),6)
        self.assertEqual((stats['eligible_passages'],stats['eligible_distinct_texts']),(6,6))
        self.assertEqual(stats['admission'],'complete-valid-passage-and-native-slate-label-blind-v1')

    def test_seventh_eligible_passage_must_be_refused_not_silently_dropped(self):
        with self.assertRaisesRegex(ValueError,'exactly six'):
            exhaustive_unused_source_census(six_original_shaped_passages(7))

    def test_five_eligible_passages_cannot_be_imputed_as_six(self):
        with self.assertRaisesRegex(ValueError,'exactly six'):
            exhaustive_unused_source_census(six_original_shaped_passages(5))

    def test_six_source_ids_with_duplicated_normalized_evidence_are_not_six(self):
        rows=six_original_shaped_passages()
        for row in rows:
            if row['idx']['paragraph']==5:
                row['paragraph']=six_original_shaped_passages()[0]['paragraph']
        with self.assertRaisesRegex(ValueError,'exactly six'):
            exhaustive_unused_source_census(rows)

    def test_human_label_flip_cannot_change_admission_or_selected_groups(self):
        rows=six_original_shaped_passages()
        original,stats=exhaustive_unused_source_census(rows)
        changed=deepcopy(rows)
        for r in changed:r['label']=1-r['label']
        again,other=exhaustive_unused_source_census(changed)
        self.assertEqual(original,again)
        self.assertEqual(stats['eligible_distinct_texts'],other['eligible_distinct_texts'])

    def test_source_row_permutation_does_not_change_exhaustive_group_ids(self):
        rows=six_original_shaped_passages()
        expected,_=exhaustive_unused_source_census(rows)
        other,_=exhaustive_unused_source_census(list(reversed(rows)))
        self.assertEqual(expected,other)

    def test_incomplete_original_answer_slate_cannot_count_as_eligible(self):
        rows=six_original_shaped_passages()
        rows=[r for r in rows if not (r['idx']['paragraph']==5 and
                                     r['idx']['question']==1 and r['idx']['answer']==1)]
        with self.assertRaisesRegex(ValueError,'exactly six'):
            exhaustive_unused_source_census(rows)

    def test_duplicate_original_candidate_identity_fails_closed(self):
        rows=six_original_shaped_passages()
        rows.append(deepcopy(rows[0]))
        with self.assertRaises(ValueError):
            exhaustive_unused_source_census(rows)

    def test_refuses_boolean_or_out_of_range_human_label_even_if_selection_blind(self):
        rows=six_original_shaped_passages()
        rows[0]['label']=True
        with self.assertRaises(ValueError):
            exhaustive_unused_source_census(rows)

    def test_source_group_identity_uses_original_pinned_digest(self):
        rows=six_original_shaped_passages()
        groups,_=exhaustive_unused_source_census(rows)
        expected={sha256(f'validation:passage:{p}:{_digest(f"Unique original-shaped passage {p}: a complete evidence paragraph.")}'.encode()).hexdigest()[:32]
                  for p in range(6)}
        self.assertEqual(groups,expected)


if __name__=='__main__':
    unittest.main()
