from pathlib import Path
p=Path('/mnt/data/hepta_execution_20261023/work/paired_superiority.py')
s=p.read_text()
needle='''    counts = [len(world_ids[str(s)]) for s in seeds]
'''
insert='''    protected_manifest = protocol.get("protected_world_ids")
    _need(isinstance(protected_manifest, dict) and
          set(protected_manifest) == set(world_ids),
          "missing preregistered protected-task cohort")
    protected_sets = {}
    for registered_seed in seeds:
        ids = protected_manifest[str(registered_seed)]
        source = world_ids[str(registered_seed)]
        _need(isinstance(ids, list) and len(ids) >= 2 and
              all(isinstance(x, str) for x in ids) and
              len(set(ids)) == len(ids) and set(ids).issubset(source),
              "invalid preregistered protected-task identities")
        protected_sets[registered_seed] = set(ids)
'''+needle
assert s.count(needle)==1
s=s.replace(needle,insert)
needle='''    cost_units = protocol.get("cost_units")
'''
insert='''    episode_cost_limit = _number(protocol.get("episode_cost_limit"),
                                 "preregistered total episode cost ceiling", lower=1e-9)
'''+needle
assert s.count(needle)==1
s=s.replace(needle,insert)
needle='''            _need(type(row.get("protected_task")) is bool, "protected status missing")
'''
repl=needle+'''            _need(protected[i, j] == (world_id in protected_sets[seed]),
                  "protected-task relabeling or unregistered cohort")
'''
assert s.count(needle)==1
s=s.replace(needle,repl)
needle='''                _need(abs(subtotal - total) <= max(1e-9, total * 1e-7),
                      "physical cost ledger not reconciled")
'''
repl=needle+'''                # An overbudget execution is an outcome, not an omission. It
                # remains in the denominator with the registered failed loss.
                # A completed output that exceeded a HARD common resource
                # ceiling is inadmissible even if aggregate mean cost is low.
                if total > episode_cost_limit + max(1e-9, episode_cost_limit * 1e-7):
                    _need(all(dr["status"] == "failed" for dr in drows),
                          "overbudget episode must be marked failed in every draw")
'''
assert s.count(needle)==1
s=s.replace(needle,repl)
s=s.replace('''               "all_registered_worlds_seen": True, "registered_seeds": len(seeds),''',
'''               "all_registered_worlds_seen": True,
               "protected_cohort_matches_registration": True,
               "registered_episode_cost_ceiling": episode_cost_limit,
               "registered_seeds": len(seeds),''')
p.write_text(s)

p=Path('/mnt/data/hepta_execution_20261023/work/test_paired_superiority.py')
s=p.read_text()
needle='''        'calibration_world_ids': [f'calibration-{i}' for i in range(100)],
'''
repl=needle+'''        'protected_world_ids': {str(s): [f'heldout-{s}-{i}' for i in range(32)
                                           if i % 4 == 0] for s in seeds},
'''
assert s.count(needle)==1;s=s.replace(needle,repl)
needle='''        'draws_per_world': 2, 'failure_loss': 2.0, 'cost_units': 'measured_cpu_seconds',
'''
repl='''        'draws_per_world': 2, 'failure_loss': 2.0,
        'cost_units': 'measured_cpu_seconds', 'episode_cost_limit': 2.0,
'''
assert s.count(needle)==1;s=s.replace(needle,repl)
anchor='''    def test_no_real_decoder_outputs_claimed(self):
'''
extra='''    def test_protected_label_cannot_be_reassigned_after_lock(self):
        d = study_fixture()
        d['worlds'][0]['protected_task'] = False
        with self.assertRaisesRegex(EvidenceGap, 'protected-task relabeling'):
            evaluate(d)

    def test_protected_cohort_must_be_preregistered(self):
        d = study_fixture()
        del d['protocol']['protected_world_ids']
        with self.assertRaisesRegex(EvidenceGap, 'missing preregistered protected'):
            evaluate(d)

    def test_protected_manifest_cannot_name_other_seed_or_duplicates(self):
        d = study_fixture()
        d['protocol']['protected_world_ids']['101'] += ['heldout-211-0']
        with self.assertRaisesRegex(EvidenceGap, 'invalid preregistered protected'):
            evaluate(d)
        d = study_fixture()
        d['protocol']['protected_world_ids']['101'] += ['heldout-101-0']
        with self.assertRaisesRegex(EvidenceGap, 'invalid preregistered protected'):
            evaluate(d)

    def test_completed_overbudget_episode_denied_despite_low_average_cost(self):
        d = study_fixture()
        extra = 4.0
        cost = d['worlds'][0]['outcomes']['ndu']['measured_cost']
        cost['controller'] += extra
        cost['total'] += extra
        with self.assertRaisesRegex(EvidenceGap, 'overbudget episode'):
            evaluate(d)

    def test_overbudget_failure_kept_in_full_denominator(self):
        d = study_fixture()
        cost = d['worlds'][0]['outcomes']['ndu']['measured_cost']
        cost['controller'] += 4
        cost['total'] += 4
        for dr in d['worlds'][0]['outcomes']['ndu']['decoded_draw_scores']:
            dr.update(status='failed', loss=2.0, quality=0, ambiguity=1,
                      inconsistency=1)
        rec = evaluate(d)
        self.assertEqual(rec['worlds_per_seed'], 32)
        self.assertFalse(rec['comparison']['static']['gates']['physical_total_cost'])
        self.assertEqual(rec['status'], 'HOLD_NO_GO')

    def test_nonpositive_common_episode_cost_limit_denied(self):
        d = study_fixture()
        d['protocol']['episode_cost_limit'] = 0
        with self.assertRaisesRegex(EvidenceGap, 'episode cost ceiling'):
            evaluate(d)

'''
assert s.count(anchor)==1;s=s.replace(anchor,extra+anchor)
p.write_text(s)
print('patched',len(s))
