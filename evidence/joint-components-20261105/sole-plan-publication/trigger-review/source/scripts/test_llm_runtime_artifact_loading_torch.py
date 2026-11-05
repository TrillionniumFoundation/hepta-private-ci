"""Real CPU Torch loader controls with a tiny, untrained projection module.

The public-material importer and declared family are replaced only inside the
child harness. Actual checked artifact bytes, Torch parameters, the copy path,
material readback and greedy decoder execute. These are loader-boundary tests,
not a pretrained SmolLM run, behavior qualification, isolation or FinalUse proof.
The opt-in is the existing CPU tensor-test switch; missing Torch is an error when
requested, never a passing fallback.
"""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import pickle
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import llm_runtime_pilot as runtime

c = runtime.contract_module()
from test_llm_adapter_contract import fixture_contract
from test_llm_runtime_artifact_loading import encoded, material_wire


@unittest.skipUnless(os.environ.get('TRNM_ACTUAL_DECODER_TENSOR_TESTS') == '1',
                     'explicit CPU tensor opt-in absent; actual artifact tensors NOT_RUN')
class ActualArtifactTensorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch
        cls.torch = torch
        torch.set_num_threads(1)

    def setUp(self):
        torch = self.torch
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.artifacts = self.directory / 'artifact'
        self.artifacts.mkdir()
        self.device = torch.device('cpu')
        self.manifest = dict(scope='tiny-untrained-real-torch-loader-test-only')
        self.plan = runtime.experiment_plan(self.manifest, threads=1, steps=1)
        self.plan_path = self.directory / 'plan.json'
        runtime.save(self.plan_path, self.plan)
        self.contract = fixture_contract()
        self.contract['numeric']['storage_dtype'] = 'float32'
        self.shapes = c.architecture_shapes(self.contract['architecture'])
        self.parameters = {name: torch.nn.Parameter(torch.zeros(shape, dtype=torch.float32))
                           for name, shape in self.shapes.items()}
        self.contract['backbone']['index'] = {
            name: runtime.tensor_descriptor(t) for name, t in self.parameters.items()}
        self.base = c.H('llm-tensor-index-v1', c.canonical(self.contract['backbone']['index'])).hex()
        self.contract['backbone']['index_root'] = self.base
        for target in self.contract['targets']:
            target.update(rank=4, alpha=[8, 1])
        self.raw_contract, self.cid = c.freeze_target_contract(self.contract)
        self.factor_shapes = {target['module'] + '.' + factor: shape
            for target in self.contract['targets']
            for factor, shape in (('A', [target['rank'], target['in_features']]),
                                  ('B', [target['out_features'], target['rank']]))}
        self.factor_parameters = {name: torch.nn.Parameter(torch.zeros(shape, dtype=torch.float32))
                                  for name, shape in self.factor_shapes.items()}
        parameters, factors = self.parameters, self.factor_parameters
        self.model_calls = []
        calls = self.model_calls

        class TinyProjection(torch.nn.Module):
            def forward(self, input_ids, attention_mask, position_ids, use_cache):
                calls.append(input_ids.detach().clone())
                # Actual embedding, matrix products, low-rank update and logits.
                # This is intentionally a tiny projection, not an LLM emulator.
                x = torch.nn.functional.embedding(input_ids, parameters['model.embed_tokens.weight'])
                q = parameters['model.layers.0.self_attn.q_proj.weight']
                x = x @ q.T + 2 * (x @ factors['model.layers.0.self_attn.q_proj.A'].T) @ factors['model.layers.0.self_attn.q_proj.B'].T
                return SimpleNamespace(logits=x @ parameters['lm_head.weight'].T)

        self.model = TinyProjection()
        self.tokenizer = SimpleNamespace(
            apply_chat_template=lambda *args, **kwargs: 'tiny test prompt',
            encode=lambda *args, **kwargs: [1, 3, 5],
            decode=lambda ids, **kwargs: ','.join(map(str, ids)))
        self.insert = Mock(side_effect=lambda model, *_: model)
        self.path_loader = Mock(side_effect=AssertionError('unchecked artifact path loader called'))

    def record(self, role='current-backbone'):
        return dict(role=role, artifact=self.base, contract=self.cid,
            kind=self.plan['recipes'][role]['kind'], source_model=runtime.WEIGHT_SHA,
            experiment=runtime.identity(self.plan), parent_backbone=self.base,
            resulting_backbone=self.base, file_sha256=None, native_artifact_H=None,
            native_domain='artifact', native_admission_accepted=False)

    def prepare(self, role='budget-matched-full-tune', material=None):
        factor = self.plan['recipes'][role]['kind'] in ('lora', 'random-lora')
        shapes = self.factor_shapes if factor else self.shapes
        if material is None:
            material = {name: runtime.tensor_bytes(self.torch.arange(math.prod(shape),
                dtype=self.torch.float32).reshape(shape) / 128 + (number + 1) / 16)
                for number, (name, shape) in enumerate(shapes.items())}
        record = self.record(role)
        if factor:
            def desc(name, shape):
                raw = material[name]
                return dict(dtype='float32', shape=shape, byte_length=len(raw),
                            sha256=hashlib.sha256(raw).hexdigest())
            modules = {target['module']: dict(
                A=desc(target['module'] + '.A', [4, target['in_features']]),
                B=desc(target['module'] + '.B', [target['out_features'], 4]),
                rank=4, alpha=[8, 1], dropout=False) for target in self.contract['targets']}
            wrapped = dict(schema='pon-wrapped-decoder-lora-material-v1', contract=self.cid,
                modules=modules, material_scope='factor-bytes-and-insertion-interface-not-functional-equivalence')
            raw, record['artifact'] = c.freeze_wrapped_adapter(wrapped, self.contract, self.cid)
            (self.artifacts / 'wrapped-adapter.json').write_bytes(raw)
        else:
            index = {name: dict(dtype='float32', shape=shapes[name], byte_length=len(raw),
                sha256=hashlib.sha256(raw).hexdigest()) for name, raw in material.items()}
            record['artifact'] = record['resulting_backbone'] = c.H(
                'llm-tensor-index-v1', c.canonical(index)).hex()
        header, payload = material_wire(material, shapes)
        self.write_material(record, encoded(header, payload))
        return record, material, header, payload

    def write_material(self, record, raw):
        (self.artifacts / 'artifact.safetensors').write_bytes(raw)
        record.update(file_sha256=hashlib.sha256(raw).hexdigest(),
                      native_artifact_H=c.H('artifact', raw).hex())
        runtime.save(self.artifacts / 'artifact.json', record)

    def invoke(self, record):
        runtime.save(self.artifacts / 'artifact.json', record)
        output = self.directory / 'output'
        output.mkdir(exist_ok=True)
        observer = SimpleNamespace(events=[], stage=lambda _, action: action())
        imports = (self.torch, self.device, None, None, None, Mock(), self.path_loader)
        args = SimpleNamespace(phase='evaluate', role=record['role'], output=str(output),
            materials=str(self.directory / 'unused-public-materials'), plan=str(self.plan_path),
            artifact=str(self.artifacts))
        # Only public-model provisioning and tiny adapter insertion are injected;
        # tensor construction, finiteness, copying, descriptor hashing, wrap
        # readback and decode/forward are the unmodified actual implementations.
        with patch.object(runtime, 'Observer', return_value=observer), \
                patch.object(runtime, 'verify_materials', return_value=(self.manifest, {})), \
                patch.object(runtime, 'runtime_import', return_value=imports), \
                patch.object(runtime, 'load_model', return_value=(self.model, self.tokenizer, self.shapes, {})), \
                patch.object(runtime, 'make_contract', return_value=(self.contract, self.raw_contract, self.cid)), \
                patch.object(runtime.importlib.metadata, 'version', return_value='tiny-injected-model-test'), \
                patch.object(runtime, 'insert_lora', self.insert), \
                patch.object(runtime, 'backbone_tensors', return_value=self.parameters), \
                patch.object(runtime, 'adapter_tensors', return_value=self.factor_parameters):
            runtime.child(args)
        return runtime.read_json(output / 'actual-receipt.json')

    def snapshot(self):
        return {name: runtime.tensor_bytes(t) for name, t in
                {**self.parameters, **self.factor_parameters}.items()}

    def assert_refused(self, record, pattern):
        before = self.snapshot()
        self.model_calls.clear()
        self.insert.reset_mock()
        with self.assertRaisesRegex(ValueError, pattern):
            self.invoke(record)
        self.assertEqual(self.snapshot(), before, 'refused artifact changed a parameter')
        self.assertFalse(self.model_calls, 'refused artifact reached a real forward')
        self.insert.assert_not_called()
        self.path_loader.assert_not_called()
        receipt = runtime.read_json(self.directory / 'output/actual-receipt.json')
        self.assertEqual(receipt['outcome'], 'failed')
        self.assertNotIn('forward_executed', receipt)
        self.assertTrue(all(receipt[name] is False for name in runtime.QUALIFICATIONS))

    def test_real_full_tune_copies_exact_bytes_and_executes_greedy_forward(self):
        record, material, _, _ = self.prepare()
        before = runtime.decode_tokens(self.model, self.tokenizer, [1, 3, 5], 'tiny',
            self.contract, self.cid, self.plan, self.torch, self.device)
        self.model_calls.clear()
        receipt = self.invoke(record)
        after = runtime.decode_tokens(self.model, self.tokenizer, [1, 3, 5], 'tiny',
            self.contract, self.cid, self.plan, self.torch, self.device, artifact=record['artifact'])
        self.assertEqual({n: runtime.tensor_bytes(t) for n, t in self.parameters.items()}, material)
        self.assertNotEqual(before['logits_sha256'], after['logits_sha256'])
        self.assertNotEqual(before['response']['generated_token_ids'], after['response']['generated_token_ids'])
        self.assertEqual(receipt['outcome'], 'success')
        self.assertEqual(receipt['artifact'], record['artifact'])
        self.assertTrue(receipt['forward_executed'])
        self.assertTrue(all(receipt[name] is False for name in runtime.QUALIFICATIONS))
        self.path_loader.assert_not_called()

    def test_official_safetensors_writer_round_trips_through_checked_real_loader(self):
        from safetensors.torch import save_file
        record, material, _, _ = self.prepare()
        tensors = {name: self.torch.frombuffer(bytearray(raw), dtype=self.torch.float32).reshape(self.shapes[name])
                   for name, raw in material.items()}
        path = self.artifacts / 'artifact.safetensors'
        save_file(tensors, str(path), metadata={'scope': 'tiny-loader-test'})
        self.write_material(record, path.read_bytes())
        receipt = self.invoke(record)
        self.assertEqual({n: runtime.tensor_bytes(t) for n, t in self.parameters.items()}, material)
        self.assertEqual(receipt['artifact'], record['artifact'])
        self.assertTrue(receipt['forward_executed'])

    def test_real_adapter_factor_copies_and_readback_keep_backbone_unchanged(self):
        for role in ('candidate', 'fresh-budget-matched-lora', 'randomized-rank-matched-lora'):
            with self.subTest(role=role):
                record, material, _, _ = self.prepare(role)
                before = {n: runtime.tensor_bytes(t) for n, t in self.parameters.items()}
                receipt = self.invoke(record)
                self.assertEqual({n: runtime.tensor_bytes(t) for n, t in self.factor_parameters.items()}, material)
                self.assertEqual({n: runtime.tensor_bytes(t) for n, t in self.parameters.items()}, before)
                self.assertEqual(receipt['artifact'], record['artifact'])
                self.assertTrue(receipt['forward_executed'])
                self.assertTrue(all(receipt[name] is False for name in runtime.QUALIFICATIONS))

    def test_real_immutable_baseline_remains_exact_and_executes_forward(self):
        before = self.snapshot()
        receipt = self.invoke(self.record())
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(receipt['artifact'], self.base)
        self.assertTrue(receipt['forward_executed'])
        self.insert.assert_not_called()

    def test_f64_broadcast_shape_and_extra_tensor_refuse_before_real_copy(self):
        record, _, header, payload = self.prepare()
        first = next(iter(header))
        for field, value in [('dtype', 'F64'), ('shape', [1]), ('shape', [True, 8])]:
            changed = copy.deepcopy(header)
            changed[first][field] = value
            self.write_material(record, encoded(changed, payload))
            with self.subTest(field=field, value=value):
                self.assert_refused(record, 'PARENT_MATERIAL_TENSOR_PROFILE')
        header['extra-executable-code'] = header[first]
        self.write_material(record, encoded(header, payload))
        self.assert_refused(record, 'PARENT_MATERIAL_TENSOR_SET')

    def test_last_nonfinite_tensor_refuses_before_first_real_parameter_copy(self):
        _, material, _, _ = self.prepare()
        last = next(reversed(material))
        for value in (float('nan'), float('inf'), float('-inf')):
            changed = dict(material, **{last: struct.pack('<f', value) + material[last][4:]})
            record, _, _, _ = self.prepare(material=changed)
            with self.subTest(value=value):
                self.assert_refused(record, 'RUNTIME_ARTIFACT_NONFINITE')

    def test_last_target_dtype_or_shape_mismatch_refuses_before_first_real_copy(self):
        record, _, _, _ = self.prepare()
        last = next(reversed(self.parameters))
        original = self.parameters[last]
        for changed in (self.torch.nn.Parameter(original.to(self.torch.float64)),
                        self.torch.nn.Parameter(self.torch.zeros((1,), dtype=self.torch.float32))):
            self.parameters[last] = changed
            self.assert_refused(record, 'RUNTIME_ARTIFACT_PARAMETER_PROFILE')
        self.parameters[last] = original

    def test_adapter_nonfinite_with_matching_material_root_refuses_before_insertion(self):
        _, material, _, _ = self.prepare('candidate')
        last = next(reversed(material))
        material[last] = struct.pack('<f', float('nan')) + material[last][4:]
        record, _, _, _ = self.prepare('candidate', material)
        self.assert_refused(record, 'LLM_ADAPTER_NONFINITE')

    def test_replaced_path_cannot_change_verified_bytes_used_by_real_torch(self):
        import llm_parent_material as parent
        record, material, header, payload = self.prepare()
        path = self.artifacts / 'artifact.safetensors'
        alternate = encoded(header, struct.pack('<f', 99.0) + payload[4:])
        original_read = parent.read_regular
        reads = []

        def swapped(name, maximum):
            raw = original_read(name, maximum)
            if Path(name) == path:
                reads.append(hashlib.sha256(raw).hexdigest())
                path.write_bytes(alternate)
            return raw

        with patch.object(parent, 'read_regular', side_effect=swapped):
            receipt = self.invoke(record)
        self.assertEqual(reads, [record['file_sha256']])
        self.assertNotEqual(hashlib.sha256(path.read_bytes()).hexdigest(), record['file_sha256'])
        self.assertEqual({n: runtime.tensor_bytes(t) for n, t in self.parameters.items()}, material)
        self.assertEqual(receipt['outcome'], 'success')
        self.path_loader.assert_not_called()

    def test_pickle_payload_is_rejected_without_unpickling_or_forward(self):
        record, _, _, _ = self.prepare()
        # A real pickle stream, including a GLOBAL constructor, must remain data.
        raw = pickle.dumps(self.torch.ones((2, 2)), protocol=4)
        self.write_material(record, raw)
        with patch.object(self.torch, 'load', side_effect=AssertionError('pickle load called')):
            self.assert_refused(record, 'PARENT_MATERIAL_HEADER')

    def test_weight_record_cannot_authorize_runtime_code_or_native_admission(self):
        record, _, _, _ = self.prepare()
        for field, value in [('executable', 'unauthorized-plugin'), ('native_admission_accepted', True),
                             ('kind', 'python-module')]:
            changed = dict(record, **{field: value})
            with self.subTest(field=field):
                self.assert_refused(changed, 'RUNTIME_ARTIFACT_')

    def test_copy_failure_preserves_failed_receipt_and_cannot_execute_forward(self):
        record, _, _, _ = self.prepare()
        original_copy = self.torch.Tensor.copy_
        copies = []

        def interrupted(tensor, source, *args, **kwargs):
            copies.append(tensor)
            if len(copies) == 2:
                raise RuntimeError('injected-real-copy-interruption')
            return original_copy(tensor, source, *args, **kwargs)

        with patch.object(self.torch.Tensor, 'copy_', interrupted), \
                self.assertRaisesRegex(RuntimeError, 'injected-real-copy-interruption'):
            self.invoke(record)
        self.assertEqual(len(copies), 2)
        self.assertFalse(self.model_calls)
        receipt = runtime.read_json(self.directory / 'output/actual-receipt.json')
        self.assertEqual(receipt['outcome'], 'failed')
        self.assertNotIn('forward_executed', receipt)
        self.assertTrue(all(receipt[name] is False for name in runtime.QUALIFICATIONS))
        # The in-memory model is partial after an interruption; it must be
        # discarded. This control establishes refusal, not atomic rollback.


if __name__ == '__main__':
    unittest.main()
