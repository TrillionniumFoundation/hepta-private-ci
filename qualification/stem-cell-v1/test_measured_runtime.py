import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

from execution_meter import BudgetStop, WorkLedger
from matrix_export import export_observed, read_sealed
from matrix_materials import file_sha256, freeze_config, validate_config
from matrix_runtime import execute, publish_prediction_bundle, run_bound, write_json_exclusive
from matrix_test_support import FixtureEncoder, setup
from paired_execution import PHASES, audit_pair, freeze_contract
from test_execution_meter import policy


def measured(arm='shared_421m_sparse_fixed16_no_ndu', mode='strict', cap=10**9):
    plan, old, config, workload = setup(arm)
    contract = freeze_contract(plan, **{k: old[k] for k in (
        'source_sha', 'workload_sha256', 'task_ids', 'device_id', 'observer_id',
        'train_cutoff_ns', 'eval_start_ns', 'eval_end_ns')}, flops_caps=dict.fromkeys(PHASES, cap))
    values = {k: v for k, v in config.items() if k not in ('schema', 'config_id', 'contract_id')}
    config = freeze_config(plan, contract, **values, measurement_policy=policy(mode))
    return plan, contract, config, workload


def perform(plan, contract, config, work, backend=None):
    ledger = WorkLedger(config['measurement_policy'], contract['flops_caps'])
    return execute(plan, contract, config, work, backend or FixtureEncoder(), clock=lambda: 25, meter=ledger)


class MeasuredRuntimeTests(unittest.TestCase):
    def test_bank_training_and_inference_measured_on_actual_dispatch(self):
        p, c, cfg, w = measured()
        _, result, rows = perform(p, c, cfg, w)
        obs = result['work_observation']
        self.assertEqual(obs['unknown_operators'], {})
        self.assertGreater(obs['phase_flops']['train'], obs['phase_flops']['inference'])
        self.assertGreater(obs['cpu_ns'], 0)
        self.assertTrue(obs['latency_includes_measurement_overhead'])
        self.assertIsNone(result['phase_flops']['evaluation'])
        self.assertFalse(result['actual_compute_caps_verified'])
        self.assertEqual(result['feature_cache_payload_bytes'], 32)
        self.assertTrue(all(row['peak_memory_bytes'] is None and row['energy_joules'] is None for row in rows))

    def test_instrumentation_preserves_logits_and_trained_tensors(self):
        p, c, cfg, w = measured()
        _, instrumented, scored = perform(p, c, cfg, w)
        p0, c0, cfg0, w0 = setup()
        _, plain, raw = execute(p0, c0, cfg0, w0, FixtureEncoder(), clock=lambda: 25)
        self.assertEqual(instrumented['trained_bank_sha256'], plain['trained_bank_sha256'])
        self.assertEqual([r['logits'] for r in scored], [r['logits'] for r in raw])

    def test_forward_counts_match_hand_derived_complete_bank_expressions(self):
        from matrix_bank import CellBank
        expected = {'shared_421m_head_no_ndu': 1743,
                    'shared_421m_sparse_fixed16_no_ndu': 343,
                    'shared_421m_sparse_direct32_no_ndu': 379,
                    'shared_421m_sparse_direct32_64m_no_ndu': 487}
        # d=4,c=2,q=3: gate N*(2d+1); softmax 4k-1;
        # each active Head w*(2d+1)+5w+c*(2w+1)+2c, including routing aggregation.
        for arm, total in expected.items():
            p, c, cfg, w = measured(arm)
            bank = CellBank(4, 2, validate_config(p, c, cfg), 3)
            m = WorkLedger(cfg['measurement_policy'], c['flops_caps'])
            with m.scope('inference', 'bank'), torch.inference_mode():
                bank(torch.ones(1, 4))
            self.assertEqual(m.report()['phase_flops']['inference'], total, arm)

    def test_dense_sparse_work_difference_with_same_parameters(self):
        reports = []
        for arm in ('shared_421m_head_no_ndu', 'shared_421m_sparse_fixed16_no_ndu'):
            _, result, _ = perform(*measured(arm))
            reports.append(result)
        self.assertEqual(reports[0]['inventory']['parameters'], reports[1]['inventory']['parameters'])
        self.assertGreater(reports[0]['phase_flops']['inference'], reports[1]['phase_flops']['inference'])

    def test_v1_not_reinterpreted_and_v2_rehash_cannot_change_policy(self):
        p, c, cfg, w = measured()
        self.assertEqual(cfg['schema'], 'hepta.stem.bound-hf-config.v2')
        p0, c0, v1, _ = setup()
        self.assertEqual(v1['schema'], 'hepta.stem.bound-hf-config.v1')
        validate_config(p0, c0, v1)
        changed = copy.deepcopy(cfg); changed['measurement_policy']['wall_time_ns'] += 1
        with self.assertRaises(ValueError): validate_config(p, c, changed)
        with self.assertRaisesRegex(ValueError, 'actual execution meter'):
            execute(p, c, cfg, w, FixtureEncoder(), clock=lambda: 25)
        ledger = WorkLedger(policy(), dict.fromkeys(PHASES, 10**9))
        with self.assertRaisesRegex(ValueError, 'differs from frozen'):
            execute(p, c, cfg, w, FixtureEncoder(), clock=lambda: 25, meter=ledger)

    def test_missing_or_different_bound_cap_is_rejected(self):
        p, c, cfg, w = measured()
        caps = dict(c['flops_caps']); caps['train'] += 1
        ledger = WorkLedger(cfg['measurement_policy'], caps)
        with self.assertRaises(ValueError): execute(p, c, cfg, w, FixtureEncoder(), clock=lambda: 25, meter=ledger)

    def test_inference_cap_stops_followup_work_and_keeps_all_task_ids(self):
        p, c, cfg, w = measured()
        # The fixture warmup costs the same bank work as one actual eval request.
        _, baseline, _ = perform(p, c, cfg, w)
        warmup = baseline['phase_flops']['inference'] // 3
        old = c
        c = freeze_contract(p, **{k: old[k] for k in ('source_sha', 'workload_sha256', 'task_ids', 'device_id',
                            'observer_id', 'train_cutoff_ns', 'eval_start_ns', 'eval_end_ns')},
                            flops_caps={**old['flops_caps'], 'inference': warmup})
        values = {k: v for k, v in cfg.items() if k not in ('schema', 'config_id', 'contract_id')}
        cfg = freeze_config(p, c, **values)
        backend = FixtureEncoder()
        _, result, rows = perform(p, c, cfg, w, backend)
        self.assertEqual([r['task_id'] for r in rows], c['task_ids'])
        self.assertTrue(all(r['status'] == 'failed' for r in rows))
        self.assertEqual(backend.calls, 4)  # No second eval Encoder call after stop.
        self.assertEqual(result['work_observation']['stopped'], 'formula_flop_budget:inference')
        self.assertIsNone(result['phase_flops']['inference'])
        self.assertFalse(backend.reverified)

    def test_failure_ledger_published_without_consumable_prediction_seal(self):
        p, c, cfg, w = measured(cap=1)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); workload = root / 'workload.json'
            write_json_exclusive(workload, w)
            c = freeze_contract(p, **{k: c[k] for k in ('source_sha', 'task_ids', 'device_id', 'observer_id',
                                'train_cutoff_ns', 'eval_start_ns', 'eval_end_ns')},
                                workload_sha256=file_sha256(workload), flops_caps=dict.fromkeys(PHASES, 1))
            vals = {k: v for k, v in cfg.items() if k not in ('schema', 'config_id', 'contract_id')}
            cfg = freeze_config(p, c, **vals)
            output = root / 'run'
            with patch('matrix_runtime.verify_source', return_value={}), patch('matrix_runtime.LocalHFEncoder', return_value=FixtureEncoder()):
                with self.assertRaises(BudgetStop):
                    run_bound(p, c, cfg, workload, root / 'unused', output)
            failure = json.loads((output / 'FAILED.json').read_text())
            self.assertEqual(failure['expected_task_ids'], c['task_ids'])
            self.assertIsNotNone(failure['work_observation']['stopped'])
            self.assertFalse((output / 'COMMITTED.json').exists())
            with self.assertRaises(ValueError): read_sealed(output, 'a' * 64)

    def test_publication_budget_checked_before_commit_marker(self):
        bank, manifest, rows = perform(*measured())
        calls = [0]
        def stop():
            calls[0] += 1
            if calls[0] == 4: raise BudgetStop('publication budget')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(BudgetStop):
                publish_prediction_bundle(root, bank, manifest, rows, clock=lambda: 27, budget_check=stop)
            self.assertFalse((root / 'COMMITTED.json').exists())

    def test_execute_seal_observe_audit_preserves_cost_scope_and_missingness(self):
        exports = []
        with tempfile.TemporaryDirectory() as tmp:
            for i, arm in enumerate(('shared_421m_head_no_ndu', 'shared_421m_sparse_fixed16_no_ndu')):
                p, c, cfg, w = measured(arm)
                bank, manifest, rows = perform(p, c, cfg, w)
                manifest['predictions_complete_at_ns'] = 26
                root = Path(tmp) / str(i); root.mkdir()
                seal = publish_prediction_bundle(root, bank, manifest, rows, clock=lambda: 27)
                labels = {'schema': 'hepta.stem.independent-labels.v1', 'seal_id': seal['seal_id'],
                          'contract_id': c['contract_id'], 'observer_id': c['observer_id'], 'created_at_ns': 31,
                          'rows': [dict(task_id=r['task_id'], input_digest=r['input_digest'], label=j, observed_at_ns=30)
                                   for j, r in enumerate(rows)]}
                label_path = root / 'observer.json'; write_json_exclusive(label_path, labels)
                exported, summary = export_observed(p, c, root, expected_seal_id=seal['seal_id'],
                    observer_path=label_path, expected_observer_sha256=file_sha256(label_path))
                self.assertGreater(exported['phase_flops']['train'], 0)
                self.assertIsNone(exported['phase_flops']['evaluation'])
                self.assertEqual(summary['execution_work_observation']['peak_rss_scope'], 'process_lifetime_not_request_peak')
                exports.append(exported)
            report = audit_pair(p, c, 'sparse_routing', *exports)
            self.assertEqual(report['status'], 'blocked')
            self.assertIn('baseline:missing_evaluation_flops', report['blockers'])
            self.assertIn('candidate:missing_energy_joules', report['blockers'])
            self.assertNotIn('baseline:missing_train_flops', report['blockers'])

    def test_non_cpu_fp32_profile_refuses_other_precision(self):
        p, c, cfg, w = measured()
        m = WorkLedger(cfg['measurement_policy'], c['flops_caps'])
        x = torch.ones(2, dtype=torch.float64)
        with self.assertRaises(BudgetStop):
            with m.scope('train', 'bank'): x.add_(1)
        self.assertEqual(x.tolist(), [1, 1])


if __name__ == '__main__':
    unittest.main()
