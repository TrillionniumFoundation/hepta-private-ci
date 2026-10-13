"""End-to-end shared Torch fixture, explicitly NOT pretrained model evidence."""

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

import torch

from development_learning import LearningRow, read_pinned_json, run_local, run_shared_learning
from shared_encoder_batch import FeatureRequest, FrozenFeature, SharedStemEngine, digest_text


class TensorBackend:
    simulated = True
    encoder_digest, preprocessor_digest, runtime_digest = ('c'*64, 'd'*64, 'e'*64)

    def __init__(self):
        self.calls = 0
        self.weight = torch.eye(4).requires_grad_(False)

    def encode_many(self, texts, representation):
        self.calls += 1
        with torch.inference_mode():
            features = torch.tensor([[float(t), 1., 0., 0.] for t in texts]) @ self.weight
        return [FrozenFeature.from_values(tuple(r), 1, representation) for r in features.tolist()]


def census():
    rows, labels = [], {}
    for split, values in [('train', [-4, -3, -2, -1, 1, 2, 3, 4]), ('heldout', [-2.5, -1.5, 1.5, 2.5])]:
        for i, value in enumerate(values):
            for cell in ('a', 'b'):
                name, text = f'{split}-{cell}-{i}', str(value)
                request = FeatureRequest(name, cell, 'a'*64, 1, 'b'*64, 'c'*64, 'd'*64, 'e'*64, digest_text(text), text)
                rows.append(LearningRow(request, f'{split}-{i}', 1 if split == 'train' else 2, split))
                if split == 'train':
                    labels[name] = int(value > 0) ^ int(cell == 'b')
    return tuple(rows), labels


class LearningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.threads)

    def test_shared_tensor_forward_and_separate_real_head_training(self):
        backend = TensorBackend()
        original = backend.weight.clone()
        rows, labels = census()
        report = run_shared_learning(SharedStemEngine(backend), rows, labels, classes=2, steps=100)
        self.assertEqual(report['encoder_calls'], 1)
        self.assertEqual(report['encoder_batch_widths'], [12])
        self.assertEqual(len(report['predictions']), 8)
        for prediction in report['predictions']:
            row = next(r for r in rows if r.request.request_id == prediction['request_id'])
            truth = int(float(row.request.text) > 0) ^ int(row.request.cell_id == 'b')
            self.assertEqual(torch.tensor(prediction['trained_logits']).argmax().item(), truth)
        self.assertTrue(torch.equal(original, backend.weight))
        self.assertIsNone(backend.weight.grad)
        self.assertTrue(report['simulated_encoder'])
        self.assertFalse(report['scored_heldout_labels'])

    def test_all_fold_failures_precede_encoder(self):
        rows, labels = census()
        for field in ({'source_group': 'train-0'}, {'observed_at': 1}, {'observed_at': True}, {'split': 'test'}):
            backend = TensorBackend()
            bad = rows[:-1] + (replace(rows[-1], **field),)
            with self.assertRaises(ValueError):
                run_shared_learning(SharedStemEngine(backend), bad, labels, classes=2)
            self.assertEqual(backend.calls, 0)

    def test_test_labels_extra_or_missing_training_labels_rejected(self):
        rows, labels = census()
        for bad in ({**labels, rows[-1].request.request_id: 0}, {}, {**labels, next(iter(labels)): True}):
            backend = TensorBackend()
            with self.assertRaises(ValueError):
                run_shared_learning(SharedStemEngine(backend), rows, bad, classes=2)
            self.assertEqual(backend.calls, 0)

    def test_same_text_cross_fold_rejected_without_encoding(self):
        rows, labels = census()
        r = rows[-1].request
        bad = rows[:-1] + (replace(rows[-1], request=replace(r, text=rows[0].request.text,
                                                         input_digest=rows[0].request.input_digest)),)
        backend = TensorBackend()
        with self.assertRaises(ValueError):
            run_shared_learning(SharedStemEngine(backend), bad, labels, classes=2)
        self.assertEqual(backend.calls, 0)

    def test_late_backend_and_scope_drift_preflight(self):
        rows, labels = census()
        for field in ({'scope_digest': 'f'*64}, {'runtime_digest': 'f'*64}):
            backend = TensorBackend()
            bad = rows[:-1] + (replace(rows[-1], request=replace(rows[-1].request, **field)),)
            with self.assertRaises(ValueError):
                run_shared_learning(SharedStemEngine(backend), bad, labels, classes=2)
            self.assertEqual(backend.calls, 0)

    def test_cli_rejects_heldout_label_fields_before_loading(self):
        rows, labels = census()
        with tempfile.TemporaryDirectory() as tmp:
            public = [asdict(row) for row in rows]
            public[-1]['label'] = 1
            path = Path(tmp) / 'rows.json'
            path.write_text(json.dumps(public))
            label_path = Path(tmp) / 'labels.json'
            label_path.write_text(json.dumps(labels))
            args = SimpleNamespace(rows=path, rows_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                   labels=label_path, labels_sha256=hashlib.sha256(label_path.read_bytes()).hexdigest())
            with self.assertRaisesRegex(ValueError, 'heldout labels'):
                run_local(args)

    def test_cli_rejects_invalid_budget_before_importing_real_loader(self):
        rows, labels = census()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'rows.json'
            path.write_text(json.dumps([asdict(row) for row in rows]))
            label_path = Path(tmp) / 'labels.json'
            label_path.write_text(json.dumps(labels))
            args = SimpleNamespace(rows=path, rows_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                   labels=label_path, labels_sha256=hashlib.sha256(label_path.read_bytes()).hexdigest(),
                                   classes=2, steps=0, parameter_budget=16384, max_tokens=512)
            with self.assertRaisesRegex(ValueError, 'pre-load resource'):
                run_local(args)

    def test_strict_byte_bound_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.json'
            for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e999}', b'x'*4_194_305):
                path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    read_pinned_json(path, hashlib.sha256(raw).hexdigest())
            raw = json.dumps({'train-0': 1}).encode()
            path.write_bytes(raw)
            self.assertEqual(read_pinned_json(path, hashlib.sha256(raw).hexdigest()), {'train-0': 1})
            with self.assertRaises(ValueError):
                read_pinned_json(path, 'a'*64)


if __name__ == '__main__':
    unittest.main()
