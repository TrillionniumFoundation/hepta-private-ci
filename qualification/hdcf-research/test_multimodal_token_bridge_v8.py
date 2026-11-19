"""Hermetic adversarial tests. All tensors here are synthetic, never pretrained."""
import copy
import hashlib
import json
import os
import stat
import subprocess
import tempfile
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from multimodal_token_bridge_v8 import (  # noqa: E402
    Denied, MAX_FANOUT, Q24, SCHEMA, Scope, SharedFeatureFanout,
    WIDTH, identity, pool_row, to_physical_bank, token_bytes_sha256,
    validate_bank,
)


def mark(label):
    return hashlib.sha256(("fixture-not-publisher:" + label).encode()).hexdigest()


def make_span(kind, i, model, preprocess):
    def token(t):
        v = [0.0] * WIDTH
        v[0] = round(0.125 + 0.01 * i + t * 0.03125, 5)
        v[1] = round(((i % 4) - 1.5) * 0.125 + t * 0.015625, 6)
        v[2] = (i + 1) / 1000.0
        return v
    vectors = [token(t) for t in range(3 if kind in ('audio', 'video') else 1)]
    return {
        'kind': kind,
        'asset_sha256': mark(f'asset:{i}:{kind}'),
        'encoder_sha256': model,
        'preprocess_sha256': preprocess,
        'tokens_sha256': token_bytes_sha256(vectors),
        'time_ms': [0, 100, 200] if kind in ('audio', 'video') else [],
        'vectors': vectors,
    }


def original():
    kinds = ('text', 'image', 'audio', 'video')
    encoders = {k: mark('encoder:' + k) for k in kinds}
    preprocessors = {k: mark('preprocessor:' + k) for k in kinds}
    def row(i, held=False):
        r = {
            'id': f'case-{i}', 'family': 'other-publisher' if held else 'fit-publisher',
            'type': 'visual' if i % 2 else 'audio',
            'event_sha256': mark(f'event:{i}'),
            'modalities': [make_span(k, i, encoders[k], preprocessors[k])
                           for k in sorted(kinds)]
        }
        if not held:
            r['target'] = (i // 2) % 2
        return r
    return {
        'schema': SCHEMA,
        'producer': {
            'principal': 'person-a', 'purpose': 'research',
            'generation': 4, 'epoch': 7, 'source_sha256': mark('publisher-manifest'),
            'encoders': encoders, 'preprocessors': preprocessors,
            'topology': 'separate_frozen_frontends'
        },
        'dimension': WIDTH, 'types': ['audio', 'visual'],
        'fit': [row(i) for i in range(8)],
        'held': [row(i, held=True) for i in range(8, 12)],
    }


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.bank = original()

    def denied(self, edit):
        bank = copy.deepcopy(self.bank)
        edit(bank)
        with self.assertRaises(Denied):
            validate_bank(bank)

    def test_valid_schema(self):
        validate_bank(self.bank)

    def test_immutable_bounded_conversion(self):
        snapshot = copy.deepcopy(self.bank)
        v1 = to_physical_bank(self.bank)
        self.assertEqual(self.bank, snapshot)
        self.assertEqual(v1['schema'], 'hepta.hdcf.frozen-feature-bank.v1')
        self.assertEqual(len(v1['fit']), 8)
        self.assertEqual(len(v1['held']), 4)
        self.assertTrue(all('target' not in r for r in v1['held']))
        self.assertTrue(all(len(r['vector']) == 384 for r in v1['fit'] + v1['held']))
        self.assertEqual(v1, to_physical_bank(self.bank))

    def test_external_original_physical_bank_contract(self):
        # This import succeeds in the real stacked repository; local standalone
        # copy of this new code does not simulate the existing physical trainer.
        try:
            from physical_bank import validate_bundle, train
        except ImportError:
            self.skipTest('parent physical_bank.py not present in isolated slice')
        bank = to_physical_bank(self.bank)
        validate_bundle(bank)
        result = train(bank, steps=16)
        self.assertEqual(result['encoder_forward_count'], 0)
        self.assertTrue(result['heads_actually_trained'])
        self.assertEqual(result['head_params_per_arm'], 2 * (WIDTH + 1))
        self.assertEqual(len(result['predictions']['split']), 4)
        self.assertEqual(len(result['predictions']['shared_one_touch']), 4)

    def test_genuine_two_process_cpu_head_and_separate_blind_review(self):
        # Full original-code integration runs only in the stacked GitHub worktree.
        # These are synthetic fixture tokens and labels, NOT original model data.
        try:
            import physical_cli  # noqa: F401
        except ImportError:
            self.skipTest('parent physical_cli.py not in isolated slice')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            original_input = root / 'unreviewed-multimodal.json'
            converted = root / 'q24-bank.json'
            sealed = root / 'sealed-heads.json'
            private = root / 'blind-labels.json'
            result = root / 'independent-review.json'
            original_input.write_text(json.dumps(self.bank))
            bridge = str(Path(__file__).resolve().with_name('multimodal_token_bridge_v8.py'))
            cli = str(Path(__file__).resolve().with_name('physical_cli.py'))

            def process(*args, succeed=True):
                child = subprocess.run([sys.executable, *args], capture_output=True,
                                       text=True, check=False, timeout=35)
                self.assertEqual(child.returncode == 0, succeed, child.stderr)
                return child

            process(bridge, '--features', str(original_input), '--out', str(converted))
            self.assertEqual(stat.S_IMODE(os.stat(converted).st_mode), 0o600)
            body = json.loads(converted.read_text())
            self.assertTrue(all('target' not in row for row in body['held']))
            process(bridge, '--features', str(original_input), '--out', str(converted),
                    succeed=False)  # No silent overwrite of existing evidence.
            process(cli, 'train', '--features', str(converted), '--out', str(sealed),
                    '--steps', '16')
            trained = json.loads(sealed.read_text())
            self.assertTrue(trained['heads_actually_trained'])
            self.assertEqual(trained['encoder_forward_count'], 0)
            self.assertFalse(trained['held_labels_present_in_training'])

            # Reviewer-only target material is created AFTER the sealed trial.
            labels = {'schema': 'hepta.hdcf.blind-targets.v1',
                      'bundle_digest': trained['bundle_digest'],
                      'targets': [
                          {'id': r['id'], 'family': r['family'], 'type': r['type'],
                           'target': int(r['id'].split('-')[-1]) % 2}
                          for r in self.bank['held']
                      ]}
            private.write_text(json.dumps(labels))
            process(cli, 'review', '--predictions', str(sealed),
                    '--targets', str(private), '--out', str(result))
            review = json.loads(result.read_text())
            self.assertEqual(review['results']['split']['n'], 4)
            self.assertFalse(review['production_authorized'])
            self.assertFalse(review['independent_source_authenticated'])
            labels['bundle_digest'] = mark('spoofed-target-identity')
            private.write_text(json.dumps(labels))
            process(cli, 'review', '--predictions', str(sealed),
                    '--targets', str(private), '--out', str(root / 'denied-review.json'),
                    succeed=False)

    def test_wrong_topology(self):
        self.denied(lambda b: b['producer'].__setitem__('topology', 'shared_and_certified'))

    def test_no_generation_alias(self):
        self.denied(lambda b: b['producer'].__setitem__('epoch', True))

    def test_preprocessor_digest(self):
        self.denied(lambda b: b['fit'][0]['modalities'][0].__setitem__('preprocess_sha256', mark('wrong')))

    def test_source_event_overlap(self):
        self.denied(lambda b: b['held'][0].__setitem__('event_sha256', b['fit'][0]['event_sha256']))

    def test_asset_overlap_across_train_held(self):
        self.denied(lambda b: b['held'][0]['modalities'][0].__setitem__(
            'asset_sha256', b['fit'][0]['modalities'][0]['asset_sha256']))

    def test_holdout_family_overlap(self):
        self.denied(lambda b: b['held'][0].__setitem__('family', b['fit'][0]['family']))

    def test_label_in_blind_inputs(self):
        self.denied(lambda b: b['held'][0].__setitem__('target', 1))

    def test_unregistered_modal_fields(self):
        self.denied(lambda b: b['held'][0]['modalities'][0].__setitem__('credential', 'secret'))

    def test_wrong_token_sha(self):
        self.denied(lambda b: b['held'][0]['modalities'][0]['vectors'][0].__setitem__(0, .987))

    def test_wrong_token_dimension(self):
        self.denied(lambda b: b['fit'][0]['modalities'][0]['vectors'][0].pop())

    def test_temporal_non_monotonic(self):
        self.denied(lambda b: b['fit'][0]['modalities'][0].__setitem__('time_ms', [0, 100, 100]))

    def test_audio_bad_temporal_census(self):
        self.denied(lambda b: b['fit'][0]['modalities'][0].__setitem__('time_ms', [0, 100]))

    def test_text_fake_timestamp(self):
        self.denied(lambda b: next(s for s in b['fit'][0]['modalities'] if s['kind'] == 'text')
                    .__setitem__('time_ms', [3]))

    def test_nonfinite(self):
        self.denied(lambda b: b['fit'][0]['modalities'][0]['vectors'][0].__setitem__(0, float('nan')))

    def test_extra_encoder_mapping(self):
        self.denied(lambda b: b['producer']['encoders'].__setitem__('sensor', mark('sensor')))

    def test_source_case_duplicates(self):
        self.denied(lambda b: b['held'][0].__setitem__('id', b['fit'][0]['id']))

    def test_cell_type_missing_class(self):
        self.denied(lambda b: [r.__setitem__('target', 0) for r in b['fit'] if r['type'] == 'visual'])

    def test_wrong_feature_dtype_boolean(self):
        self.denied(lambda b: b['held'][0]['modalities'][0]['vectors'][0].__setitem__(3, True))

    def test_not_full_modality_alignment_claim(self):
        bank = self.bank
        new = to_physical_bank(bank, ablate_kind='image')
        self.assertNotEqual(new['fit'][0]['vector'], to_physical_bank(bank)['fit'][0]['vector'])
        self.assertEqual(new['producer'], to_physical_bank(bank)['producer'])

    def test_signed_video_order_changes_repr(self):
        row = copy.deepcopy(self.bank['held'][0])
        before = pool_row(row)
        span = next(s for s in row['modalities'] if s['kind'] == 'video')
        span['vectors'].reverse()
        span['tokens_sha256'] = token_bytes_sha256(span['vectors'])
        after = pool_row(row)
        self.assertNotEqual(before, after)

    def test_q24_output(self):
        for f in pool_row(self.bank['fit'][2]):
            self.assertLessEqual(abs(f), 8)
            self.assertEqual(round(f * Q24), f * Q24)

    def test_ablation_last_modality_denied(self):
        row = {'modalities': [copy.deepcopy(self.bank['fit'][0]['modalities'][0])]}
        with self.assertRaises(Denied):
            pool_row(row, ablate_kind=row['modalities'][0]['kind'])

    def test_duplicate_modality(self):
        self.denied(lambda b: b['fit'][0]['modalities'].append(copy.deepcopy(b['fit'][0]['modalities'][0])))

    def test_independence_is_not_proven(self):
        self.assertEqual(self.bank['producer']['source_sha256'],
                         to_physical_bank(self.bank)['producer']['source_sha256'])
        self.assertEqual(identity(self.bank, b'hepta.hdcf.multimodal-bank.v8'),
                         identity(copy.deepcopy(self.bank), b'hepta.hdcf.multimodal-bank.v8'))


class FanoutTests(unittest.TestCase):
    def setUp(self):
        self.fan = SharedFeatureFanout(original())
        self.scope = self.fan.scope

    @staticmethod
    def permit(scope, case, cell):
        return True

    def test_4096_borrowers_one_materialization(self):
        first = self.fan.borrow('case-0', 'cell-0', scope=self.scope, admit=self.permit)
        for i in range(1, MAX_FANOUT):
            result = self.fan.borrow('case-0', f'cell-{i}', scope=self.scope, admit=self.permit)
            self.assertIs(result, first)
        self.assertEqual(self.fan.borrow_count, MAX_FANOUT)
        self.assertEqual(self.fan.pool_count, 1)
        with self.assertRaises(Denied):
            self.fan.borrow('case-0', 'cell-over-limit', scope=self.scope, admit=self.permit)

    def test_no_revoke_bypass_on_cache_hit(self):
        self.fan.borrow('case-0', 'cell-0', scope=self.scope, admit=self.permit)
        with self.assertRaises(Denied):
            self.fan.borrow('case-0', 'cell-0', scope=self.scope, admit=lambda *_: False)
        self.assertEqual(self.fan.borrow_count, 1)

    def test_wrong_scope_and_generation(self):
        wrong = Scope(self.scope.principal, self.scope.purpose, self.scope.generation + 1,
                      self.scope.epoch, self.scope.bundle_digest)
        with self.assertRaises(Denied):
            self.fan.borrow('case-0', 'cell-0', scope=wrong, admit=self.permit)
        self.assertEqual(self.fan.pool_count, 0)

    def test_wrong_scope_purpose(self):
        wrong = Scope(self.scope.principal, 'another-purpose', self.scope.generation,
                      self.scope.epoch, self.scope.bundle_digest)
        with self.assertRaises(Denied):
            self.fan.borrow('case-0', 'cell-0', scope=wrong, admit=self.permit)

    def test_callback_must_return_true_bool(self):
        with self.assertRaises(Denied):
            self.fan.borrow('case-0', 'cell-0', scope=self.scope, admit=lambda *_: 1)

    def test_case_scope(self):
        with self.assertRaises(Denied):
            self.fan.borrow('case-unavailable', 'cell-0', scope=self.scope, admit=self.permit)

    def test_original_input_mutation_does_not_invalidate_immutable_snapshot(self):
        bank = original()
        fan = SharedFeatureFanout(bank)
        expected = pool_row(copy.deepcopy(bank['fit'][0]))
        bank['fit'][0]['modalities'][0]['vectors'][0][0] = 7.0
        got = fan.borrow('case-0', 'cell-0', scope=fan.scope, admit=self.permit)
        self.assertEqual(got, expected)
        self.assertEqual(fan.pool_count, 1)

    def test_reject_unhashable_modality_instead_of_crashing(self):
        bank = original()
        bank['fit'][0]['modalities'][0]['kind'] = []
        with self.assertRaises(Denied):
            SharedFeatureFanout(bank)

    def test_tampered_direct_pool_rejected(self):
        row = copy.deepcopy(original()['fit'][0])
        row['modalities'][0]['vectors'][0][0] = 7.0
        with self.assertRaises(Denied):
            pool_row(row)

    def test_independent_rows_not_collapsed(self):
        a = self.fan.borrow('case-0', 'cell-0', scope=self.scope, admit=self.permit)
        b = self.fan.borrow('case-1', 'cell-0', scope=self.scope, admit=self.permit)
        self.assertNotEqual(a, b)
        self.assertEqual(self.fan.pool_count, 2)


if __name__ == '__main__':
    unittest.main()
