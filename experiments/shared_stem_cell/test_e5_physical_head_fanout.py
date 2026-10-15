"""Actual CPU Head math on synthetic features; not pretrained/production evidence."""
import unittest
import math
import e5_physical_head_fanout as m

class TestCPUHeadFanout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = m.run(logical_cells=64, active_cells=8, mode='shared', repeats=1, train_steps=1)
        cls.cloned = m.run(logical_cells=64, active_cells=8, mode='cloned', repeats=1, train_steps=1)

    def test_head_parameter_inventory(self):
        self.assertEqual(self.shared['physical_cell_head_parameters'], 64 * 9744)
    def test_head_learning_changes_actual_weights(self):
        self.assertEqual(self.shared['heads_with_changed_weights'], 8)
    def test_shared_buffer_physical_identity(self):
        self.assertEqual(self.shared['physical_feature_buffer_count'], 1)
        self.assertEqual(self.cloned['physical_feature_buffer_count'], 8)
    def test_actual_identical_data_and_predictions(self):
        self.assertEqual(self.shared['synthetic_feature_q24_sha256'], self.cloned['synthetic_feature_q24_sha256'])
        self.assertEqual(self.shared['sampled_f32_prediction_sha256'], self.cloned['sampled_f32_prediction_sha256'])
    def test_bytes_scale_as_actual_buffers(self):
        self.assertEqual(self.cloned['resident_feature_tensor_payload_bytes'], 8*self.shared['resident_feature_tensor_payload_bytes'])
    def test_latency_and_cpu_are_measured(self):
        self.assertGreater(self.shared['observed_throughput_outputs_per_second'], 0)
        d = self.shared['observed_per_head_forward_latency_ms']
        self.assertTrue(0 < d['p50'] <= d['p95'] <= d['p99'])
    def test_never_authenticate_synthetic_head(self):
        self.assertFalse(self.shared['actual_pretrained_encoder_forward'])
        self.assertFalse(self.shared['production_worker_or_ndu_verified'])
        self.assertFalse(self.shared['production_promotion_permitted'])
        self.assertIsNone(self.shared['hardware_energy_joules'])
    def test_bad_scale_denied(self):
        with self.assertRaises(m.Invalid): m.run(logical_cells=65, active_cells=8, mode='shared')
    def test_bad_active_denied(self):
        with self.assertRaises(m.Invalid): m.run(logical_cells=64, active_cells=65, mode='shared')
    def test_bad_mode_denied(self):
        with self.assertRaises(m.Invalid): m.run(logical_cells=64, active_cells=4, mode='forged')
    def test_bad_training_budget_denied(self):
        with self.assertRaises(m.Invalid): m.run(logical_cells=64, active_cells=4, mode='shared', train_steps=100)

if __name__ == '__main__': unittest.main()
