"""Synthetic integration controls for the separately implemented record reader."""
from pathlib import Path
import tempfile
import unittest
import numpy as np
from data_contract import canonical, digest, exact_radius, head, model_with_head, save
from evaluation_io import model_entry, run_phase
from run_confirmation import primary_contrasts
from value_graph import strict_hidden, strict_scores
import verify_records as reader


def synthetic_graph():
    masks = np.array([[1, 1, 0, 0, 1, 1], [1, 0, 0, 0, 1, 1],
                      [1, 0, 0, 0, 1, 1]], dtype=bool)
    terminal = np.zeros((3, 6))
    terminal[1, 4:] = [-0.8, 0.8]
    terminal[2, 4:] = [0.8, -0.8]
    qstar = terminal.copy()
    qstar[0, 1] = 0.7
    keys = [canonical({'tick': tick, 'synthetic_index': i}) for i, tick in enumerate((0, 1, 1))]
    return dict(masks=masks, terminal=terminal, qstar=qstar,
        posterior=np.array([0.5, 0.9, 0.1]), optimal_values=np.array([0.7, 0.8, 0.8]),
        edges=[[[(0.25, 1, 0.1), (0.75, 2, 0.1)], [], []], [[], [], []], [[], [], []]],
        order=[0, 1, 2], initial=0, states=[{'tick': t} for t in (0, 1, 1)], keys=keys,
        public={'id': 'synthetic_branching_world'}, state_order_sha256=digest(canonical(keys).encode()))


class ReaderControls(unittest.TestCase):
    def test_mixed_metrics_and_independent_dyadic_radius(self):
        value = {'a': [1.0, None, True, {'x': -2.0}], 'b': 'synthetic'}
        reader.compare_metrics(value, value)
        with self.assertRaises(ValueError):
            reader.compare_metrics({'a': [1.0, None, 1, {'x': -2.0}], 'b': 'synthetic'}, value)
        original = np.zeros((4, 49)); original[0, 0] = 1.0
        changed = original.copy(); changed[3, -1] = 0.5
        witness = reader.radius_check(original, changed)
        expected = exact_radius(original, changed)
        self.assertEqual(witness, {key: expected[key] for key in witness})
        changed[3, -1] = np.nextafter(0.5, np.inf)
        with self.assertRaises(ValueError):
            reader.radius_check(original, changed)

    def test_complete_phase_alias_and_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = np.zeros((4, 49)); rows[0, 0] = 2.0; rows[3, -1] = -1.0
            base = {'network': {'w2': rows[:, :48].tolist(), 'b2': rows[:, 48].tolist()},
                    'synthetic_only': True}
            anchor = save(root / 'original.json.gz', base)
            changed = rows.copy(); changed[0, -1] = 0.8
            candidate = save(root / 'candidate.json.gz', model_with_head(base, changed, 'Q')[0])
            models = {'KEEP': model_entry(anchor['path'], base, 'KEEP', 'KEEP'),
                      'Q_1': model_entry(candidate['path'], base, 'Q', 'Q_1'),
                      'G_1': model_entry(candidate['path'], base, 'G', 'G_1')}
            for entry in models.values():
                reader.model_check(entry, base)
            graph = synthetic_graph()
            graph_pin = save(root / 'graph.json.gz', graph)
            H = np.zeros((3, 49)); H[:, -1] = 1
            item = {'world_index': 0, 'graph': graph, 'graph_pin': graph_pin, 'H': H}
            record, record_pin = run_phase(root / 'phase.json', 'SELECT', 11, models,
                                          [item], 'a' * 64, lambda: None)
            checked, metrics, _, summary = reader.phase_check(record_pin, 'SELECT', 11,
                models, [0], {0: item}, 'a' * 64, lambda: None)
            self.assertAlmostEqual(summary['KEEP']['utility'], 0.0, places=14)
            self.assertAlmostEqual(summary['Q_1']['utility'], 0.3, places=14)
            self.assertAlmostEqual(metrics[0]['Q_1']['terminal_gap_contribution'], 0.4, places=14)
            self.assertEqual(checked['worlds'][0]['arms']['G_1']['alias_of'], 'Q_1')
            self.assertEqual(checked['worlds'][0]['arms']['G_1']['evaluation_CPU_seconds'], 0.0)
            record['worlds'][0]['arms']['G_1']['evaluation_CPU_seconds'] = 0.001
            corrupt_pin = save(root / 'corrupt.json', record)
            with self.assertRaisesRegex(ValueError, 'alias records no second evaluation'):
                reader.phase_check(corrupt_pin, 'SELECT', 11, models, [0], {0: item}, 'a' * 64, lambda: None)

    def test_independent_primary_interval(self):
        fits, summaries = {}, {}
        for index, fit in enumerate(reader.FITS):
            summaries[str(fit)] = {}
            fits[str(fit)] = {}
            for domain in ('iid', 'ood'):
                summary = {'KEEP': {'utility': 0.1}, 'T_SELECTED': {'utility': 0.15},
                           'G_SELECTED': {'utility': 0.16 + 0.01 * index}}
                summaries[str(fit)][domain] = summary
                fits[str(fit)][domain] = {'summary': summary}
        records = primary_contrasts(fits)
        reader.primary_check(records, summaries)
        records[0]['familywise95_interval'][0] += 0.01
        with self.assertRaises(ValueError):
            reader.primary_check(records, summaries)

    def test_hidden_arithmetic_across_array_shapes(self):
        rng = np.random.default_rng(1137137)
        X, w, b = rng.normal(size=(137, 85)), rng.normal(0, 0.1, size=(48, 85)), rng.normal(0, 0.1, 48)
        base = {'network': {'w1': w.tolist(), 'b1': b.tolist()}}
        primary = strict_hidden(base, X)
        independent = reader.independent_hidden(base, X)
        original_shape = np.ones((137, 49))
        for index in range(len(X)):
            original_shape[index, :48] = np.tanh(np.sum(w * X[index][None, :], axis=1) + b)
        self.assertEqual(primary.tobytes(), independent.tobytes())
        self.assertEqual(primary.tobytes(), original_shape.tobytes())
        rows = rng.normal(0, 0.1, (4, 49))
        self.assertEqual(strict_scores(rows, primary)[0].tobytes(), reader.independent_scores(rows, primary).tobytes())


if __name__ == '__main__':
    unittest.main()
