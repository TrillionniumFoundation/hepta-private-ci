import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import experiment as ex


class EngineeringChecks(unittest.TestCase):
    def test_analytic_jacobians(self):
        rng = np.random.default_rng(17)
        a, b, w = rng.normal(size=(4, 3)), rng.normal(size=(4, 3)), rng.normal(size=7)
        for kind in ('linear', 'gated', 'lowrank', 'mlp'):
            _, jac = ex.forward(w, a, b, kind)
            for j in range(len(w)):
                delta = np.zeros_like(w)
                delta[j] = 1e-6
                numeric = (ex.forward(w+delta, a, b, kind)[0]-ex.forward(w-delta, a, b, kind)[0])/2e-6
                np.testing.assert_allclose(jac[:, j], numeric, atol=1e-8)

    def test_transitive_source_and_byte_clustering(self):
        rows = [dict(id=str(i), source_id=str(i), page_id=str(i), image_sha256=str(i)) for i in range(4)]
        rows[1]['image_sha256'] = rows[0]['image_sha256']
        rows[2]['page_id'] = rows[1]['page_id']
        self.assertEqual(ex.components(rows), [[0, 1, 2], [3]])

    def test_split_isolation_and_frozen_drift_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            folder, out = Path(temp)/'input', Path(temp)/'output'
            ex.fixture(folder)
            manifest, a, b = ex.inputs(folder)
            examples = ex.design(manifest, a, b)
            assigned = {}
            for row in examples:
                for index in (row['image'], row['text']):
                    self.assertEqual(assigned.setdefault(index, row['split']), row['split'])
                self.assertEqual(row['image'] == row['text'], row['y'] == 1)
            ex.freeze(folder, out)
            metadata = json.loads((folder/'manifest.json').read_text())
            metadata['rows'][0]['id'] = 'changed'
            ex.save(folder/'manifest.json', metadata)
            with self.assertRaisesRegex(ValueError, 'drift'):
                ex.run(folder, out)

    def test_missing_lowrank_and_empty_selection(self):
        a, b, w = np.ones((4, 3)), np.zeros((4, 3)), np.ones(7)
        logits, _ = ex.forward(w, a, b, 'lowrank')
        np.testing.assert_array_equal(logits, np.ones(4))
        result = ex.metrics(np.array([0, 1, 0, 1]), np.full(4, 0.5), np.array(['a', 'a', 'b', 'b']), 0.6)
        self.assertEqual(result['coverage'], 0)
        self.assertIsNone(result['selective_risk'])
        self.assertEqual(result['conformal_block_coverage'], 1)

    def test_historical_manifest_rejects_prefreeze_edits(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)/'input'
            ex.fixture(folder)
            manifest, a, b = ex.inputs(folder)
            manifest['historical_examples'] = ex.design(manifest, a, b)
            manifest['kind'] = 'historical_P39_development_only'
            manifest['original_archive_sha256'] = 'fixture-archive-identity'
            ex.save(folder/'manifest.json', manifest)
            original = (folder/'manifest.json').read_bytes()
            # No historical rows or bank are shipped in this test fixture.
            with patch.object(ex, 'HISTORICAL_MANIFEST_SHA256', ex.digest(folder/'manifest.json')), \
                 patch.object(ex, 'HISTORICAL_BANK_SHA256', ex.digest(folder/'features.npz')):
                ex.freeze(folder, Path(temp)/'accepted')
                for field in ('y', 'split', 'block', 'source_id', 'image_sha256', 'archive'):
                    with self.subTest(field=field):
                        altered = json.loads(original)
                        if field == 'y':
                            altered['historical_examples'][0]['y'] ^= 1
                        elif field in ('split', 'block'):
                            altered['historical_examples'][0][field] = 'changed'
                        elif field in ('source_id', 'image_sha256'):
                            altered['rows'][0][field] = 'changed'
                        else:
                            altered['original_archive_sha256'] = 'changed'
                        ex.save(folder/'manifest.json', altered)
                        with self.assertRaisesRegex(ValueError, 'Historical manifest mismatch'):
                            ex.freeze(folder, Path(temp)/('rejected-'+field))
                        self.assertFalse((Path(temp)/('rejected-'+field)).exists())


if __name__ == '__main__':
    unittest.main()
