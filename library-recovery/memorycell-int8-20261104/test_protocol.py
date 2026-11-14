"""No runtime imports, model access, network, downloads or real-model tests."""
import ast
import copy
import json
from pathlib import Path
import tempfile
import unittest
from common import ROOT, agreement, nearest_rank, process_peak, read_json, sha256, summarize, top_set, validate_fixtures, verify_assets
from fixture_builder import build
from runtime_integrity import digest

class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.protocol = read_json(ROOT / 'protocol.json')

    def test_fixture_is_exact_original_build(self):
        self.assertEqual(read_json(ROOT / 'fixtures.json'), build())
        self.assertEqual(len(validate_fixtures(build())), 12)

    def test_labels_rejected(self):
        data = build(); data['queries'][0]['label'] = 1
        with self.assertRaises(AssertionError): validate_fixtures(data)

    def test_bad_lengths_rejected(self):
        data = build(); data['queries'][0]['passages'][0]['text'] = 'short'
        with self.assertRaises(AssertionError): validate_fixtures(data)

    def test_fixed_session_and_thread_budget(self):
        self.assertEqual(self.protocol['order'], ['fp32', 'int8', 'int8', 'fp32'] * 3)
        self.assertEqual(self.protocol['threads'], 1)
        self.assertLessEqual(self.protocol['budget']['wall_seconds'], 600)
        self.assertLessEqual(self.protocol['budget']['rss_bytes'], 2 * 1024**3)

    def test_inherited_ru_maxrss_is_not_process_peak(self):
        self.assertEqual(process_peak({'ru_maxrss_bytes': 100000000, 'status_VmHWM': 8576 * 1024}), 8576 * 1024)
        with self.assertRaises(KeyError): process_peak({'ru_maxrss_bytes': 100000000})

    def test_percentile_nearest_rank(self):
        self.assertEqual(nearest_rank(list(range(1, 61)), .95), 57)

    def test_top_sets(self):
        self.assertEqual(top_set([1, 1 + 0.5e-6, 0, -1], 1e-6), {0, 1})

    def test_nonfinite_rejected(self):
        with self.assertRaises(AssertionError): top_set([1, 0, float('nan'), 3], 1e-6)

    def test_identity_agreement(self):
        data = [[3.0, 2.0, 1.0, 0.0]] * 12
        a = agreement(data, data, 1e-6)
        self.assertEqual(a['max_abs_raw_logit_difference'], 0)
        self.assertEqual(a['margin_comparable_pairs'], 72)
        self.assertEqual(a['margin_concordance'], 1)
        self.assertEqual(a['identical_top_set_queries'], 12)

    def test_full_rank_inversion_not_hidden_by_top_one(self):
        a = agreement([[3, 2, 1, 0]] * 12, [[3, 1, 2, 0]] * 12, 1e-6)
        self.assertEqual(a['top_set_overlap_queries'], 12)
        self.assertEqual(a['discordant_strict_passage_pairs'], 12)
        self.assertEqual(len(a['all_pairwise_rank_changes']), 12)
        self.assertLess(a['margin_concordance'], .98)

    def test_candidate_ties_count_against_fixed_denominator(self):
        a = agreement([[3, 2, 1, 0]] * 12, [[3, 2, 2, 0]] * 12, 1e-6)
        self.assertEqual(a['margin_comparable_pairs'], 72)
        self.assertEqual(a['margin_concordant_pairs'], 60)

    def test_top_set_inflation_detected(self):
        a = agreement([[3, 2, 1, 0]] * 12, [[3, 3, 1, 0]] * 12, 1e-6)
        self.assertEqual(a['top_set_overlap_queries'], 12)
        self.assertEqual(a['identical_top_set_queries'], 0)

    def test_no_margin_pairs_is_not_vacuous_success(self):
        a = agreement([[1, 1, 1, 1]] * 12, [[1, 1, 1, 1]] * 12, 1e-6)
        self.assertEqual(a['margin_concordance'], 0)

    def sessions(self):
        results = []
        for arm in self.protocol['order']:
            int8 = arm == 'int8'
            results.append({'arm': arm, 'scores': [[3, 2, 1, 0]] * 12,
                'timing': {'mean_query_ms': 8 if int8 else 10, 'p95_query_ms': 9 if int8 else 11,
                           'pairs_per_second': 500 if int8 else 400},
                'state_serialized_bytes': 70 if int8 else 100,
                'first_query_from_launch_ms': 120 if int8 else 100,
                'ready_from_launch_ms': 200 if int8 else 100,
                'full_session_from_launch_ms': 400 if int8 else 500,
                'startup_inference_peak_rss_bytes': 500 if int8 else 450,
                'worker_peak_rss_bytes': 700 if int8 else 600})
        return results

    def test_positive_policy_example_only(self):
        summary = summarize(self.sessions(), self.protocol)
        self.assertTrue(all(summary['gates'].values()))
        self.assertEqual(len(summary['paired_costs']), 6)
        self.assertEqual(summary['paired_costs'][0]['break_even_queries'], 50)
        self.assertGreater(summary['paired_costs'][0]['ready_from_launch_ratio'], 1)

    def test_one_bad_session_pair_fails(self):
        sessions = self.sessions(); sessions[-2]['timing']['pairs_per_second'] = 399
        summary = summarize(sessions, self.protocol)
        self.assertFalse(summary['gates']['warm_throughput'])
        self.assertEqual(summary['decision'], 'DOES_NOT_QUALIFY')

    def test_startup_cost_can_fail_candidate(self):
        sessions = self.sessions()
        for s in sessions:
            if s['arm'] == 'int8': s['ready_from_launch_ms'] = 10000
        self.assertFalse(summarize(sessions, self.protocol)['gates']['500_query_projected_cost'])

    def test_repetition_variation_fails(self):
        sessions = copy.deepcopy(self.sessions()); sessions[-1]['scores'][0][0] += .1
        self.assertFalse(summarize(sessions, self.protocol)['gates']['repeat_consistency'])

    def test_sources_compile_and_no_top_level_heavy_import(self):
        for filename in ('common.py', 'worker.py', 'run_primary.py', 'fixture_builder.py', 'runtime_integrity.py'):
            tree = ast.parse((ROOT / filename).read_text())
            for node in tree.body:
                if isinstance(node, ast.Import):
                    self.assertFalse(any(n.name in {'torch', 'transformers'} for n in node.names))

    def test_offline_and_safe_loading_explicit(self):
        worker = (ROOT / 'worker.py').read_text()
        for required in ('local_files_only=True', 'trust_remote_code=False', 'use_safetensors=True',
                         "attn_implementation='eager'", 'torch.float32', 'inplace=False', 'torch.qint8',
                         'sorted(quantized_names) == sorted(original_names)', 'output_loading_info=True', 'missing_keys', 'unexpected_keys', 'mismatched_keys', 'error_msgs', "attempt['supervisor_pid'] == os.getppid()"):
            self.assertIn(required, worker)
        self.assertNotIn('torch.load(', worker)
        self.assertIn("open('x')", (ROOT / 'run_primary.py').read_text())

    def test_runtime_manifest_canonical_and_content_sensitive(self):
        self.assertEqual(digest({'a': 1, 'b': 2}), digest({'b': 2, 'a': 1}))
        self.assertNotEqual(digest({'binary_sha256': 'one'}), digest({'binary_sha256': 'two'}))
        self.assertIn("verify_runtime(admission['runtime_integrity'])", (ROOT / 'run_primary.py').read_text())

    def test_failure_audit_fields_and_external_clock_are_prescribed(self):
        runner = (ROOT / 'run_primary.py').read_text()
        for field in ('last_worker_observation', 'worker_vmhwm_bytes', 'parent_vmhwm_bytes', 'violated_bounds', 'exit_status', 'worker_elapsed_seconds'):
            self.assertIn(field, runner)
        self.assertIn('/usr/bin/time -p -o private_outer_timing.txt', (ROOT / 'PROTOCOL.md').read_text())

    def test_assets_reject_unknown_downloaded_code_before_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            names = ['config.json', 'tokenizer_config.json', 'vocab.txt', 'model.safetensors', 'remote.py']
            for name in names: (root / name).write_text('fictional test bytes')
            admission = {'asset_sha256': {name: sha256(root / name) for name in names},
                         'model_revision': self.protocol['model_revision']}
            with self.assertRaises(AssertionError): verify_assets(root, admission, self.protocol)

    def test_assets_reject_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ['config.json', 'tokenizer_config.json', 'vocab.txt']:
                (root / name).write_text('{}')
            (root / 'model.safetensors').symlink_to(root / 'vocab.txt')
            admission = {'asset_sha256': {p.name: sha256(p) for p in root.iterdir()},
                         'model_revision': self.protocol['model_revision']}
            admission['asset_sha256']['model.safetensors'] = self.protocol['model_safetensors_sha256']
            with self.assertRaises(AssertionError): verify_assets(root, admission, self.protocol)

if __name__ == '__main__':
    unittest.main(verbosity=2)
