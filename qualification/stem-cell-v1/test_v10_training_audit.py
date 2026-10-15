"""Adversarial independent training-trace tests; synthetic receipt is NOT a trained model."""
import copy
import random
import unittest

from v9_source_panels import dataset_design
from v9_typed_graph import digest
from v10_training_audit import verify_trace


class TrainingTrace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.public, truth = dataset_design()
        train = {k: v for k, v in truth.items() if k.startswith('train/')}
        cls.seal = dict(schema='hepta.v10.real-granite-source.v1',
                        public_sha256=digest(cls.public), train_rows=288,
                        held_rows=960, source_groups=312,
                        train_label_sha256=digest(train))
        cls.groups = {}
        for row in cls.public:
            if row['case_id'].startswith('train/'):
                cls.groups.setdefault(row['source_group'], []).append(row['case_id'])
        cls.schedule = {}
        for seed in (41, 47, 53):
            rng = random.Random(f'hepta/v10/granite/fixed-batches/{seed}')
            rows = []
            for step in range(1, 257):
                ids = rng.sample(sorted(cls.groups), 4)
                rows.append(dict(update=step, groups=ids,
                                 source_sha256=digest([c for g in ids for c in cls.groups[g]]),
                                 ce=1., pair=.5, total=1.25))
            cls.schedule[seed] = rows

    def receipt(self, seed=41, arm='bridge'):
        return dict(schema='hepta.v10.real-granite-training.v1', seed=seed, arm=arm,
                    input_public_sha256=self.seal['public_sha256'],
                    training_labels_sha256=self.seal['train_label_sha256'],
                    model_parameters=38466 if arm == 'base' else 42562,
                    actual_updates=256, batch_size=16,
                    total_optimizer_case_exposures=4096, source_groups=72,
                    optimizer='Adam_foreach_false', learning_rate=.001,
                    depth=3, pair_weight=.5,
                    held_labels_seen=False, held_predictions_scored=False,
                    model_selected=False, production_accepted=False, authority='DENY_ALL')

    def test_full_three_seed_three_arm_trace(self):
        for seed in (41, 47, 53):
            for arm in ('base', 'bridge', 'endpoint'):
                with self.subTest(seed=seed, arm=arm):
                    self.assertEqual(verify_trace(self.public, self.seal,
                        self.receipt(seed, arm), self.schedule[seed], seed=seed, arm=arm)
                        ['real_recorded_optimizer_exposures'], 4096)

    def reject(self, *, receipt=None, seal=None, schedule=None):
        with self.assertRaises(ValueError):
            verify_trace(self.public, seal if seal is not None else self.seal,
                receipt if receipt is not None else self.receipt(),
                schedule if schedule is not None else self.schedule[41], seed=41, arm='bridge')

    def test_train_label_changed_but_resigned_model_receipt_rejected(self):
        x=self.receipt();x['training_labels_sha256']='0'*64
        self.reject(receipt=x)

    def test_mismatched_source_seal_rejected(self):
        seal=dict(self.seal);seal['public_sha256']='f'*64
        self.reject(seal=seal)

    def test_mismatched_weight_architecture_count_rejected(self):
        x=self.receipt();x['model_parameters']=42563
        self.reject(receipt=x)

    def test_heldout_used_or_fake_promotion_rejected(self):
        for key,val in [('held_labels_seen',True),('held_predictions_scored',True),
                        ('production_accepted',True),('authority','ALLOW')]:
            x=self.receipt();x[key]=val
            self.reject(receipt=x)

    def test_partial_steps_or_work_undercharge_rejected(self):
        x=self.receipt();x['total_optimizer_case_exposures']=4080
        self.reject(receipt=x)
        self.reject(schedule=self.schedule[41][:-1])

    def test_reordered_minibatch_rejected(self):
        s=copy.deepcopy(self.schedule[41]);s[0],s[1]=s[1],s[0]
        self.reject(schedule=s)

    def test_tampered_sample_hash_even_with_plausible_groups_rejected(self):
        s=copy.deepcopy(self.schedule[41]);s[8]['source_sha256']='0'*64
        self.reject(schedule=s)

    def test_float_nan_or_false_loss_accounting_rejected(self):
        for bad in (float('nan'), 1.5, -1.):
            s=copy.deepcopy(self.schedule[41]);s[4]['total']=bad
            self.reject(schedule=s)

    def test_extra_receipt_workflow_or_schedule_field_rejected(self):
        s=copy.deepcopy(self.schedule[41]);s[10]['override']='unregistered'
        self.reject(schedule=s)

    def test_different_seed_plan_rejected(self):
        self.reject(schedule=self.schedule[47])

if __name__=='__main__': unittest.main()
