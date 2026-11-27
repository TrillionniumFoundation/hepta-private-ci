import json
import unittest
from control import Command, ControlProfile, MODE, UnsupportedCommand

SHA = 'a' * 64
SEM = tuple(range(12))
POLICY = tuple((i + 1) / 78 for i in range(12))


class ControlTests(unittest.TestCase):
    def profile(self, image=SEM):
        return ControlProfile(SHA, SEM, image, MODE)

    def test_all_keep_is_exact_identity(self):
        result = self.profile().condition(POLICY, POLICY, Command(0, 0, 0), observed_model_sha256=SHA)
        self.assertIs(result['text'], POLICY)
        self.assertIs(result['image'], POLICY)

    def test_explicit_words_and_unspecified_ratios(self):
        result = self.profile().condition(POLICY, POLICY, Command(3, 0, 0), observed_model_sha256=SHA)
        self.assertEqual(result['supported_image_outcomes'], 4)
        self.assertEqual(result['image'][:8], (0.,) * 8)
        self.assertAlmostEqual(sum(result['image']), 1)
        self.assertAlmostEqual(result['image'][8] / result['image'][11], POLICY[8] / POLICY[11])

    def test_observed_semantics_not_latent_ids(self):
        permuted = tuple((i + 4) % 12 for i in SEM)
        result = self.profile(permuted).condition(POLICY, POLICY, Command(3, 1, 1), observed_model_sha256=SHA)
        self.assertEqual(result['image'][4], 1)
        self.assertEqual(result['text'][8], 1)

    def test_empty_support_and_zero_mass_refuse(self):
        with self.assertRaises(UnsupportedCommand):
            self.profile((0,) * 12).condition(POLICY, POLICY, Command(3, 0, 0), observed_model_sha256=SHA)
        concentrated = (1.,) + (0.,) * 11
        with self.assertRaises(UnsupportedCommand):
            self.profile().condition(concentrated, concentrated, Command(3, 0, 0), observed_model_sha256=SHA)

    def test_full_command_collapses_only_when_explicit(self):
        result = self.profile().condition(POLICY, POLICY, Command(2, 2, 2), observed_model_sha256=SHA)
        self.assertEqual(result['image'], (0.,) * 7 + (1.,) + (0.,) * 4)

    def test_request_features_not_targets(self):
        self.assertEqual(Command.from_features([0, 0, 1, 0, 1, 0, 0, 0, 1, 0]), Command(2, 0, 1))
        for bad in ([0] * 10, [1] * 10, [0] * 9, [True] + [0] * 9):
            with self.assertRaises(ValueError): Command.from_features(bad)

    def test_profile_roundtrip_explicit_identity(self):
        profile = self.profile()
        copy = ControlProfile.loads(profile.dumps(), expected_model_sha256=SHA, expected_mode=MODE)
        self.assertEqual(copy, profile)
        self.assertEqual(copy.key, profile.key)
        for sha, mode in ((SHA, 'original'), ('b' * 64, MODE)):
            with self.assertRaises(ValueError): ControlProfile.loads(profile.dumps(), expected_model_sha256=sha, expected_mode=mode)

    def test_tamper_vocab_mapping_and_duplicate_reject(self):
        payload = json.loads(self.profile().dumps())
        for name, value in (('vocabulary', ['unknown']), ('image_semantics', [0] * 12)):
            changed = json.loads(json.dumps(payload)); changed['profile'][name] = value
            with self.assertRaises(ValueError): ControlProfile.loads(json.dumps(changed), expected_model_sha256=SHA, expected_mode=MODE)
        with self.assertRaises(ValueError): ControlProfile.loads('{"profile":0,"profile":1}', expected_model_sha256=SHA, expected_mode=MODE)

    def test_malformed_probability_and_command_reject(self):
        for p in ((float('nan'),) + (0.,) * 11, (1.,) * 12, (True,) + (0.,) * 11):
            with self.assertRaises(ValueError): self.profile().condition(p, POLICY, Command(0, 0, 0), observed_model_sha256=SHA)
        with self.assertRaises(ValueError): Command(True, 0, 0)
        with self.assertRaises(ValueError): Command(4, 0, 0)
        with self.assertRaises(ValueError): self.profile().condition(POLICY, POLICY, Command(0, 0, 0), observed_model_sha256='b' * 64)

if __name__ == '__main__': unittest.main()
