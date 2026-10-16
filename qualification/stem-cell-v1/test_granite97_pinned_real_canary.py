"""No-download profile tests; never claim these are pretrained Encoder runs."""
import json
from pathlib import Path
import tempfile
import unittest

from granite97_pinned_real_canary import (
    EXPECTED_LAYERS, EXPECTED_MAX_CONTEXT, EXPECTED_PARAMETERS, HIDDEN_WIDTH,
    MODEL_ID, REVISION, exclusive_json, validate_profile,
)


class Granite97R2ProfileTests(unittest.TestCase):
    def profile(self, **changes):
        fields = dict(model_id=MODEL_ID, revision=REVISION,
            parameter_count=EXPECTED_PARAMETERS, hidden_width=HIDDEN_WIDTH,
            layers=EXPECTED_LAYERS, context=EXPECTED_MAX_CONTEXT)
        return dict(fields, **changes)

    def test_identity_is_exact_model_revision_not_a_generic_granite(self):
        self.assertEqual(validate_profile(**self.profile())['parameter_count'], 97_441_152)
        self.assertEqual(validate_profile(**self.profile())['hidden_width'], 384)
        self.assertEqual(validate_profile(**self.profile())['context_tokens'], 32_768)

    def test_other_size_family_and_unpinned_revision_are_rejected(self):
        for change in (dict(model_id='ibm-granite/granite-embedding-311m-multilingual-r2'),
                       dict(model_id='granite embedding 97m'),
                       dict(revision='main'),
                       dict(revision='deadbeef'*5),
                       dict(parameter_count=97_000_000),
                       dict(hidden_width=768),
                       dict(layers=22),
                       dict(context=8192),
                       dict(parameter_count=True)):
            with self.subTest(change=change):
                with self.assertRaisesRegex(ValueError, 'frozen Granite97 R2'):
                    validate_profile(**self.profile(**change))

    def test_exclusive_json_prevents_overwriting_existing_results(self):
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname) / 'probe.json'
            exclusive_json(target, {'revision':REVISION, 'production_authorized':False})
            self.assertEqual(json.loads(target.read_text())['revision'], REVISION)
            with self.assertRaises(FileExistsError):
                exclusive_json(target, {'revision':'main'})
            self.assertEqual(json.loads(target.read_text())['revision'], REVISION)


if __name__ == '__main__':
    unittest.main()
