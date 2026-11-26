"""Synthetic reader controls plus optional mutations of retained native evidence.

Synthetic metadata never counts as a fit, installation, role independence or
native throughput measurement. --study requires the real final artifact reader
to pass first and modifies temporary copies only.
"""
import argparse
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import verify_study as reader


def synthetic_roles():
    return dict(keys=[dict(role=role, pid=index+1, public_key=f'{index+1:064x}')
                      for index, role in enumerate(reader.ROLES)])


class SyntheticReaderControls(unittest.TestCase):
    def test_duplicate_role_cannot_hide_behind_seven_distinct_keys_and_pids(self):
        profile = synthetic_roles()
        profile['keys'][-1]['role'] = 'generator'
        with self.assertRaisesRegex(ValueError, 'exact role set'):
            reader.separated_roles(profile)

    def test_reused_pid_or_key_is_not_separate_custody(self):
        for field in ('pid', 'public_key'):
            profile = synthetic_roles()
            profile['keys'][-1][field] = profile['keys'][0][field]
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'role process/key separation'):
                reader.separated_roles(profile)

    def test_boolean_pid_is_not_a_real_process_identity(self):
        profile = synthetic_roles(); profile['keys'][0]['pid'] = True
        with self.assertRaisesRegex(ValueError, 'role PID'):
            reader.separated_roles(profile)

    def test_raw_json_duplicates_symlinks_and_oversized_inputs_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'input.json'
            path.write_text('{"scope":false,"scope":true}')
            with self.assertRaisesRegex(ValueError, 'duplicate JSON field'):
                reader.load(path)
            path.write_bytes(b'x'*(reader.JSON_LIMIT+1))
            with self.assertRaisesRegex(ValueError, 'material byte bound'):
                reader.load(path)
            path.write_text('{}')
            link = path.with_name('alias.json'); link.symlink_to(path)
            with self.assertRaisesRegex(ValueError, 'canonical regular material'):
                reader.load(link)

    def test_future_material_is_after_freeze_and_has_positive_interval(self):
        commitment = dict(observed_unix_micros=10, body=dict(choices={'q':'add'}, parent_choices={'q':'xor'}))
        body = dict(starts_unix_micros=11, ends_unix_micros=12, **commitment['body'])
        self.assertEqual(reader.window_interval(body, commitment), (11, 12))
        for field, value in [('starts_unix_micros', 10), ('ends_unix_micros', 11), ('ends_unix_micros', 9)]:
            changed = dict(body, **{field:value})
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, 'future generation chronology'):
                reader.window_interval(changed, commitment)

    def test_post_freeze_prediction_substitution_refused(self):
        commitment = dict(observed_unix_micros=10, body=dict(choices={'q':'add'}, parent_choices={'q':'xor'}))
        body = dict(starts_unix_micros=11, ends_unix_micros=12, **commitment['body'])
        body['choices'] = {'q':'multiply'}
        with self.assertRaisesRegex(ValueError, 'frozen prediction substitution'):
            reader.window_interval(body, commitment)

    def test_native_choice_uses_measured_mean_and_preserves_original_tie_order(self):
        actions = {'first':'subtract', 'second':'add'}
        sensor = 'query-'+reader.sha(b'q')
        cells = {(sensor,'first'):(8,0,0,0), (sensor,'second'):(8,2**32,2**32,2**32)}
        self.assertEqual(reader.choice_table(cells, actions, ['q']), {'q':'add'})
        cells[(sensor,'second')] = (8,0,0,0)
        self.assertEqual(reader.choice_table(cells, actions, ['q']), {'q':'subtract'})
        del cells[(sensor,'second')]
        with self.assertRaisesRegex(ValueError, 'partial native action grid'):
            reader.choice_table(cells, actions, ['q'])

    def test_truncated_and_trailing_native_payloads_refused(self):
        for raw in (b'HEPTTB01', b'not-native-payload'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                reader.model(raw)

    def test_synthetic_ips_uses_logged_action_and_fixed_support(self):
        tasks = [dict(query='q') for _ in range(4096)]
        outputs = [dict(logged_operation='add' if index % 4 == 0 else 'xor', logged_correct=True)
                   for index in range(4096)]
        actual = reader.ips_interval(outputs, tasks, {'q':'add'})
        self.assertLess(actual['lower'], 2**32)
        self.assertGreater(actual['upper'], 2**32)
        self.assertEqual(actual['lower']+actual['upper'], 2*2**32)
        # Complete arithmetic correctness is not IPS support if the frozen
        # target action was never independently logged.
        with self.assertRaisesRegex(ValueError, 'actual IPS row/ESS support'):
            reader.ips_interval(outputs, tasks, {'q':'subtract'})

    def test_synthetic_public_product_decision_denies_authority_and_trailing_bytes(self):
        identifier = lambda value: len(value).to_bytes(2, 'big')+value.encode()
        body = (b'HEPTQE01'+bytes(range(1, 33))*4+identifier('test-plan')
                +identifier('candidate')+identifier('baseline')+b'\0\0\0\0')
        encode = lambda raw: raw+bytes.fromhex(reader.sha(b'hepta.product-qualification-record.checksum.v1'+raw))
        self.assertEqual(reader.product_decision(encode(body))['disposition'], 0)
        for altered in (body[:-1]+b'\1', body+b'\0'):
            with self.subTest(altered=altered[-2:]), self.assertRaisesRegex(ValueError, 'cannot grant authority'):
                reader.product_decision(encode(altered))


def mutate_actual_artifact(study, only=None):
    """Rejection controls on real retained output; no re-signing or new source facts."""
    study = study.resolve(strict=True)
    original = reader.verify(study)
    changes = {
        'duplicate-role': ('profile.json', lambda value: value['keys'][-1].update(role='generator')),
        'promoted-production': ('summary.json', lambda value: value.update(production_qualification=True)),
        'missing-install': ('summary.json', lambda value: value.update(installed_generations=2)),
        'wrong-parent': ('summary.json', lambda value: value['generations'][1].update(parent='0'*64)),
        'wrong-launch': ('summary.json', lambda value: value['generations'][0].update(launch_generation=1)),
        'failed-no-update': ('summary.json', lambda value: value.update(no_update_error='accepted')),
        'post-freeze-model': ('generation-1/generation-1-evaluation-inputs.json',
                             lambda value: value['frozen_plan']['folds'][0].update(model_digest='0'*64)),
        'unbound-retention': ('generation-1/generation-1-evaluation-inputs.json',
                             lambda value: value['evaluation_bundle'].update(retention_receipt_digests=['0'*64])),
        'unbound-withdrawal': ('generation-1/generation-1-evaluation-inputs.json',
                              lambda value: value['evaluation_bundle'].update(unlearning_receipt_digest='0'*64)),
        'overlapping-native-windows': ('generation-1/generation-1-evaluation-inputs.json',
                                      lambda value: value['longitudinal_time']['windows'][1].update(starts_unix_micros=1)),
        'wrong-observer-source': ('generation-1/generation-1-evaluation-inputs.json',
                                  lambda value: value['longitudinal_time']['windows'][0].update(observed_source_cut='0'*64)),
        'reused-controller': ('generation-1/generation-1-evaluation-inputs.json',
                             lambda value: value['trust']['signers'][1].update(controller_id=value['trust']['signers'][0]['controller_id'])),
        'missing-live-revoke': ('summary.json', lambda value: value.update(live_process_reader_external_revoke=False)),
        'substituted-revoke': ('revoke-observations.json', lambda value: value.update(revocation_receipt_digest='0'*64)),
        'wrong-sealed-material': ('generation-1/generation-1-evaluation-inputs.json',
                                 lambda value: value['frozen_plan'].update(final_holdout_digest='0'*64)),
        'unbound-product-inputs': ('generation-1/generation-1-evaluation-inputs.json',
                                  lambda value: value['product']['released_inputs'].update(digest='0'*64)),
        'changed-product-alpha': ('generation-1/generation-1-evaluation-inputs.json',
                                  lambda value: value['product']['candidate_plan']['confidence'].update(family_alpha_ppm=100000)),
        'supplied-product-interval': ('generation-1/generation-1-evaluation-inputs.json',
                                      lambda value: value['evaluation_bundle']['metrics'][0]['candidate'].update(lower=2**32)),
        'wrong-final-native-cohort': ('generation-1/generation-1-evaluation-inputs.json',
                                      lambda value: value['frozen_plan'].update(final_holdout_window_id='generation-1-window-1')),
        'false-replay-no-side-effects': ('process-17-replay-negative-controls.json',
                                        lambda value: value[0].update(cas_unchanged=False)),
        'no-update-withdrawal-absent': ('no-update/withdrawal-control/observed.json',
                                      lambda value: value.update(reopened_original_owner=False)),
    }
    if only is not None:
        if only not in changes:
            raise ValueError('unknown retained-artifact mutation control')
        changes = {only:changes[only]}
    outcomes = []
    for name, (relative, change) in changes.items():
        with tempfile.TemporaryDirectory() as temporary:
            cloned = Path(temporary)/study.name
            shutil.copytree(study, cloned)
            for suffix in ('.execution.json', '.native.log', '.custodian.py', '.measurement-correction.json'):
                adjacent = study.with_suffix(suffix)
                if adjacent.is_file(): shutil.copy2(adjacent, cloned.with_suffix(suffix))
            # Absolute descriptor references are intentionally remapped by the
            # reader. Verify the unmodified copied output first so a relocation
            # defect cannot make every subsequent corruption look rejected.
            unchanged = reader.verify(cloned)
            if unchanged != original:
                raise AssertionError(f'unchanged artifact copy differs: {name}')
            path = cloned/relative
            value = reader.load(path); change(value)
            path.write_bytes(reader.canonical(value)+b'\n')
            try:
                reader.verify(cloned)
            except (ValueError, KeyError) as error:
                outcomes.append(dict(control=name, unchanged_copy_verified=True,
                                     rejected=True, reason=str(error)))
            else:
                raise AssertionError(f'actual artifact mutation accepted: {name}')
    return dict(schema='hepta.learning-study-reader-negative-controls.v1', actual_original=original,
                controls=outcomes, source_artifacts_modified=False, production_qualification=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path)
    parser.add_argument('--control', help='Run one named actual mutation; the default runs every control.')
    args, remaining = parser.parse_known_args()
    if args.control is not None and args.study is None:
        parser.error('--control requires retained native output via --study')
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SyntheticReaderControls))
    if not result.wasSuccessful(): raise SystemExit(1)
    if args.study is not None:
        print(json.dumps(mutate_actual_artifact(args.study, args.control), indent=2))
