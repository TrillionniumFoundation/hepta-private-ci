import copy
import json
import tempfile
import unittest
from pathlib import Path

import torch

from execution_meter import WorkLedger
from final_campaign import _cost_record, audit_campaign
from matrix_materials import file_sha256
from next_round_matrix import _digest
from paired_execution import PHASES
from test_execution_meter import policy
from work_record import validate_work_record


def observation(*, unknown=False, failed=False):
    ledger = WorkLedger(policy(), dict.fromkeys(PHASES, 10**9))
    try:
        with ledger.scope('train', 'bank'):
            torch.ones(3).add(1)
            if unknown:
                torch.sin(torch.ones(3))
            if failed:
                raise OSError('test callback failure')
    except OSError:
        pass
    return ledger, ledger.report()


class WorkRecordTests(unittest.TestCase):
    def test_complete_live_record_preserves_actual_prefix(self):
        _, record = observation()
        self.assertEqual(validate_work_record(record)['train'], 3)
        self.assertEqual(_cost_record({'work_observation': record})['phases']['train'],
                         {'known_formula_work': 3, 'complete_count': 3})

    def test_unknown_record_prefix_is_retained_but_cannot_be_complete(self):
        _, record = observation(unknown=True)
        self.assertEqual(validate_work_record(record)['train'], 3)
        cost = _cost_record({'work_observation': record})
        self.assertEqual(cost['phases']['train'], {'known_formula_work': 3, 'complete_count': None})
        record['phase_flops']['train'] = 3
        with self.assertRaisesRegex(ValueError, 'cannot claim complete'):
            _cost_record({'work_observation': record})

    def test_failed_callback_never_becomes_complete_count(self):
        _, record = observation(failed=True)
        validate_work_record(record)
        record['phase_flops']['train'] = 3
        with self.assertRaisesRegex(ValueError, 'cannot claim complete'):
            validate_work_record(record)

    def test_unobserved_phase_is_not_explicit_zero(self):
        _, record = observation()
        record['phase_flops']['evaluation'] = 0
        with self.assertRaisesRegex(ValueError, 'unobserved phase'):
            validate_work_record(record)

    def test_duplicate_scope_and_prefix_mismatch_reject(self):
        _, record = observation()
        for change in ('duplicate', 'count'):
            bad = copy.deepcopy(record)
            if change == 'duplicate':
                bad['scopes'].append(copy.deepcopy(bad['scopes'][0]))
            else:
                bad['phase_flops']['train'] += 1
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_work_record(bad)

    def test_unknown_inventory_cannot_disagree_with_scopes(self):
        _, record = observation(unknown=True)
        for change in ('missing', 'excess', 'scope_zero'):
            bad = copy.deepcopy(record)
            if change == 'missing': del bad['operators']['aten.sin.default']
            elif change == 'excess': bad['unknown_operators']['aten.sin.default'] += 1
            else: bad['scopes'][0]['unknown_operators'] = 0
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_work_record(bad)

    def test_boolean_negative_and_nonfinite_counters_reject(self):
        _, record = observation()
        for field, value in (('calls', True), ('formula_flops', -1),
                             ('unknown_operators', float('nan')), ('cpu_ns', 1.5),
                             ('failed_calls', 2)):
            bad = copy.deepcopy(record); bad['scopes'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_work_record(bad)

    def test_policy_and_scope_upgrades_reject(self):
        _, record = observation()
        p = policy(); p['mode'] = 'strict'
        with self.assertRaisesRegex(ValueError, 'frozen configuration'):
            validate_work_record(record, expected_policy=p)
        for flag in ('hardware_instruction_count', 'observer_evaluation_measured', 'production_authorized'):
            bad = copy.deepcopy(record); bad[flag] = True
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                validate_work_record(bad)

    def test_aborted_reservations_require_failed_stopped_scope(self):
        _, record = observation()
        record['aborted_formula_reservations'] = 1
        with self.assertRaisesRegex(ValueError, 'stopped ledger'):
            validate_work_record(record)
        record['stopped'] = 'operator_execution_failed'
        with self.assertRaisesRegex(ValueError, 'failed scope'):
            validate_work_record(record)

    def test_failed_kernel_record_retains_unexecuted_reservation(self):
        meter = WorkLedger(policy(), dict.fromkeys(PHASES, 10**9))
        a, b = torch.ones(2, 3), torch.ones(4, 2)
        with self.assertRaises(RuntimeError):
            with meter.scope('train', 'bank'): a @ b
        record = meter.report()
        self.assertGreater(record['aborted_formula_reservations'], 0)
        self.assertEqual(validate_work_record(record)['train'], 0)
        self.assertIsNone(record['phase_flops']['train'])

    def test_report_is_detached_from_ledger_policy_and_scopes(self):
        meter, first = observation()
        expected = copy.deepcopy(first)
        first['policy']['mode'] = 'strict'
        first['scopes'][0]['formula_flops'] = 999
        first['operators'].clear()
        self.assertEqual(meter.report(), expected)
        self.assertEqual(meter.policy['mode'], 'observe')
        self.assertEqual(meter.rows['train:bank']['formula_flops'], 3)

    def test_new_stop_does_not_rewrite_a_prior_snapshot(self):
        meter, before = observation()
        expected = copy.deepcopy(before)
        try: meter.stop('late_publication_stop')
        except RuntimeError: pass
        after = meter.report()
        self.assertEqual(before, expected)
        self.assertIsNone(before['stopped'])
        self.assertEqual(after['stopped'], 'late_publication_stop')
        validate_work_record(after)

    def test_missing_observations_remain_missing(self):
        self.assertIsNone(_cost_record({})['phases']['train']['complete_count'])
        with self.assertRaises(ValueError): validate_work_record({})


class WorkRecordCampaignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import test_final_campaign as fixtures
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.root = Path(cls.tmp.name)
        cls.plan, cls.contract, cls.protocol, cls.labels = fixtures.build_campaign(cls.root)

    def test_resealed_inconsistent_success_cannot_enter_final_audit(self):
        import shutil
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'copy'; shutil.copytree(self.root, root)
            path = root / 'candidate' / 'execution.json'
            manifest = json.loads(path.read_text())
            obs = manifest['work_observation']
            scope = next(s for s in obs['scopes'] if s['phase'] == 'inference')
            scope['unknown_operators'] += 1
            obs['operators']['aten.sin.default'] = 1
            obs['unknown_operators']['aten.sin.default'] = 1
            # Preserve the incorrect complete phase count and rebind the outer
            # hashes: this tests semantic rejection, not simple hash mismatch.
            path.write_text(json.dumps(manifest))
            seal_path = root / 'candidate' / 'COMMITTED.json'
            seal = json.loads(seal_path.read_text())
            seal['files']['execution.json'] = file_sha256(path)
            seal['seal_id'] = _digest({k: v for k, v in seal.items() if k != 'seal_id'})
            seal_path.write_text(json.dumps(seal))
            labels = copy.deepcopy(self.labels)
            labels['terminals']['candidate']['id'] = seal['seal_id']
            lp = root / 'labels.json'; lp.write_text(json.dumps(labels))
            with self.assertRaisesRegex(ValueError, 'cannot claim complete'):
                audit_campaign(self.plan, self.contract, root / 'workload.json', root / 'registry',
                               expected_protocol_id=self.protocol['protocol_id'],
                               directories={r: str(root / r) for r in ('baseline', 'candidate')},
                               labels_path=lp, expected_labels_sha256=file_sha256(lp))

    def test_rehashed_failed_prefix_cannot_be_upgraded_to_complete(self):
        import shutil
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'copy'; shutil.copytree(self.root, root)
            fp = root / 'baseline' / 'FAILED.json'
            failure = json.loads(fp.read_text())
            obs = failure['work_observation']
            scope = next(s for s in obs['scopes'] if s['phase'] == 'train')
            scope['failed_calls'] = 1
            obs['phase_flops']['train'] = sum(s['formula_flops'] for s in obs['scopes'] if s['phase'] == 'train')
            fp.write_text(json.dumps(failure))
            labels = copy.deepcopy(self.labels)
            labels['terminals']['baseline']['id'] = file_sha256(fp)
            lp = root / 'labels.json'; lp.write_text(json.dumps(labels))
            with self.assertRaisesRegex(ValueError, 'cannot claim complete'):
                audit_campaign(self.plan, self.contract, root / 'workload.json', root / 'registry',
                               expected_protocol_id=self.protocol['protocol_id'],
                               directories={r: str(root / r) for r in ('baseline', 'candidate')},
                               labels_path=lp, expected_labels_sha256=file_sha256(lp))


if __name__ == '__main__':
    unittest.main()
