from pathlib import Path
root=Path(__file__).resolve().parent
p=root/'paired_superiority.py'
s=p.read_text()
a='''    flat_ids = [k for s in seeds for k in world_ids[str(s)]]
'''
b='''    # Protected-task membership is part of the frozen evaluation plan, not
    # a classification that the scorer may change after observing outcomes.
    protected_flags = protocol.get("heldout_protected_flags")
    _need(isinstance(protected_flags, dict) and
          set(protected_flags) == set(world_ids) and
          all(isinstance(protected_flags[str(seed)], list) and
              len(protected_flags[str(seed)]) == counts[i] and
              all(type(flag) is bool for flag in protected_flags[str(seed)])
              for i, seed in enumerate(seeds)),
          "missing or invalid frozen protected-task label manifest")
    flat_ids = [k for s in seeds for k in world_ids[str(s)]]
'''
assert s.count(a)==1;s=s.replace(a,b)
a='''            protected[i, j] = row.get("protected_task") is True
            _need(type(row.get("protected_task")) is bool, "protected status missing")
'''
b='''            _need(type(row.get("protected_task")) is bool, "protected status missing")
            _need(row["protected_task"] is protected_flags[str(seed)][j],
                  "protected-task label differs from frozen heldout manifest")
            protected[i, j] = protected_flags[str(seed)][j]
'''
assert s.count(a)==1;s=s.replace(a,b)
a='''               "protected_worlds_per_seed": protected_world_counts,
'''
b='''               "protected_worlds_per_seed": protected_world_counts,
               "protected_labels_checked_against_frozen_manifest": True,
'''
assert s.count(a)==1;s=s.replace(a,b)
p.write_text(s)
q=root/'test_paired_superiority.py';s=q.read_text()
a='''    return {'schema': 'hepta-mgp-paired-v1', 'protocol': p, 'worlds': worlds}
'''
b='''    lock_protected_task_labels({'protocol': p, 'worlds': worlds})
    return {'schema': 'hepta-mgp-paired-v1', 'protocol': p, 'worlds': worlds}


def lock_protected_task_labels(study):
    # Test-fixture builder only. In real experiments this manifest must be
    # frozen before any test outputs are produced and independently certified.
    p = study['protocol']
    p['heldout_protected_flags'] = {str(seed): [row['protected_task']
                                        for row in study['worlds'] if row['seed'] == seed]
                                  for seed in p['seeds']}
'''
assert s.count(a)==1;s=s.replace(a,b)
# Existing tests deliberately mutate protected membership to inspect coverage;
# lock the changed intended fixture BEFORE evaluating so assertions exercise
# the intended downstream gate rather than the new mismatch gate.
for fragment in [
'''        d['worlds'][0]['protected_task'] = True
        with self.assertRaisesRegex(EvidenceGap, 'insufficient protected original-source groups'):''',
'''                row['protected_task'] = False
        with self.assertRaisesRegex(EvidenceGap, 'insufficient protected original-source groups'):''',
'''            row['protected_task'] = row['world_id'] in {'heldout-101-0', 'heldout-101-1'} or (row['seed'] != 101 and row['protected_task'])
        with self.assertRaisesRegex(EvidenceGap, 'insufficient protected original-source groups'):''',
'''        d['worlds'] = enlarged
        result = evaluate(d)''',
'''            row['protected_task'] = False
        with self.assertRaisesRegex(EvidenceGap, 'no protected-task'):'''
]:
    assert s.count(fragment)==1,fragment
    if fragment.startswith('        d[\'worlds\'] = enlarged'):
        rep=fragment.replace('        result = evaluate(d)', '        lock_protected_task_labels(d)\n        result = evaluate(d)')
    else:
        rep=fragment.replace('        with self.assertRaisesRegex(', '        lock_protected_task_labels(d)\n        with self.assertRaisesRegex(')
    s=s.replace(fragment,rep)
anchor='''    def test_missing_training_source_manifest_rejected(self):
'''
new='''    def test_frozen_protected_manifest_required(self):
        d = study_fixture()
        del d['protocol']['heldout_protected_flags']
        with self.assertRaisesRegex(EvidenceGap, 'frozen protected-task label manifest'):
            evaluate(d)

    def test_frozen_protected_manifest_requires_boolean_exact_population(self):
        d = study_fixture()
        d['protocol']['heldout_protected_flags']['101'][1] = 1
        with self.assertRaisesRegex(EvidenceGap, 'frozen protected-task label manifest'):
            evaluate(d)
        d = study_fixture()
        d['protocol']['heldout_protected_flags']['307'].pop()
        with self.assertRaisesRegex(EvidenceGap, 'frozen protected-task label manifest'):
            evaluate(d)

    def test_posthoc_reclassification_cannot_flip_protected_service_decision(self):
        d = study_fixture(bootstrap_replicates=2000)
        for row in d['worlds']:
            if row['protected_task']:
                for dr in row['outcomes']['ndu']['decoded_draw_scores']:
                    dr['quality'] = 0.70
        prior = evaluate(d)
        self.assertFalse(prior['all_provisional_gates_pass'])
        self.assertEqual(prior['ndu_protected_source_equal_quality_by_seed'], [.7] * 3)
        # Same observed raw scores and original-source counts; only relabel
        # the externally registered protected tasks in the heldout rows.
        for row in d['worlds']:
            row['protected_task'] = int(row['world_id'].rsplit('-', 1)[1]) % 4 == 2
        with self.assertRaisesRegex(EvidenceGap, 'protected-task label differs from frozen heldout manifest'):
            evaluate(d)

    def test_frozen_membership_and_unmodified_rows_still_validate(self):
        d = study_fixture(bootstrap_replicates=2000)
        r = evaluate(d)
        self.assertTrue(r['all_provisional_gates_pass'])
        self.assertTrue(r['protected_labels_checked_against_frozen_manifest'])
        self.assertEqual(r['status'], 'HOLD_NO_GO')

'''
assert s.count(anchor)==1;s=s.replace(anchor,new+anchor)
q.write_text(s)
