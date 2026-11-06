"""Byte/context and dispatch regressions only; no real tensor or model execution."""
import argparse
import ast
import copy
import hashlib
import inspect
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import llm_runtime_parent_step as step
import llm_runtime_pilot as runtime
import test_llm_parent_material as material_fixture


class ParentStepTests(unittest.TestCase):
    def setUp(self):
        # These complete factor bytes are an explicit synthetic boundary fixture.
        # The real public model roots remain unmodified in production sources.
        fixture = material_fixture.ParentMaterialTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.root = fixture.directory
        self.family = fixture.family
        self.manifest = dict(model=runtime.MODEL, revision=runtime.REVISION, files={
            name: dict(size=size, sha256=sha, revision=runtime.REVISION)
            for name, (size, sha) in runtime.PUBLIC_FILES.items()})
        self.config = dict(num_hidden_layers=30, hidden_size=576, intermediate_size=1536,
            num_attention_heads=9, num_key_value_heads=3, vocab_size=49152,
            max_position_embeddings=8192, tie_word_embeddings=True, attention_bias=False, mlp_bias=False,
            rope_theta=100000, rms_norm_eps=1e-5, hidden_act='silu', attention_dropout=0.0, rope_scaling=None)
        self.materials = self.root / 'materials'
        self.materials.mkdir()
        runtime.save(self.materials / 'config.json', self.config)
        runtime.save(self.materials / 'tokenizer_config.json', dict(chat_template='explicit fixture template'))
        self.family['material_pins']['tokenizer_files_root'] = runtime.contract_module().H(
            'llm-tokenizer-file-index-v1', runtime.canonical({name: dict(sha256=self.manifest['files'][name]['sha256'],
                byte_length=self.manifest['files'][name]['size']) for name in
                ('tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json')})).hex()
        family_patch = patch.object(runtime, 'verify_family', return_value=self.family)
        family_patch.start(); self.addCleanup(family_patch.stop)
        material_patch = patch.object(runtime, 'verify_materials', return_value=(self.manifest, self.config))
        material_patch.start(); self.addCleanup(material_patch.stop)
        self.plan = runtime.experiment_plan(self.manifest)
        runtime.save(self.root / 'plan.json', self.plan)
        self.contract, raw, self.cid = runtime.contract_from_inventory(fixture.contract['backbone']['index'],
            'explicit fixture template', self.config, self.manifest, self.plan)
        fixture.contract_path.write_bytes(raw)
        adapter = copy.deepcopy(fixture.adapter); adapter['contract'] = self.cid
        raw, self.aid = runtime.contract_module().freeze_wrapped_adapter(adapter, self.contract, self.cid)
        fixture.adapter_path.write_bytes(raw)
        self.value = dict(schema=step.SCHEMA, scope=step.SCOPE, attempt_id='1' * 64,
            operation='train', experiment=runtime.identity(self.plan), source=step.sources(),
            files=dict(materials=str(self.materials), plan=str(self.root / 'plan.json'),
                parent_contract=str(fixture.contract_path), parent_adapter=str(fixture.adapter_path),
                parent_artifact=str(fixture.artifact_path), candidate_directory=None),
            parent=dict(contract=self.cid, adapter=self.aid, file_sha256=fixture.sha), candidate=None,
            output=str(self.root / 'output' / 'execution'), flags=dict(step.FALSES))

    def arguments(self, value=None):
        value = value or self.value
        return argparse.Namespace(materials=value['files']['materials'], plan=value['files']['plan'],
            expected_plan=value['experiment'], output=str(Path(value['output']).parent),
            attempt_id=value['attempt_id'], operation=value['operation'],
            parent_contract=value['files']['parent_contract'], parent_adapter=value['files']['parent_adapter'],
            parent_artifact=value['files']['parent_artifact'], expected_contract=value['parent']['contract'],
            expected_parent_adapter=value['parent']['adapter'],
            expected_parent_file_sha256=value['parent']['file_sha256'],
            candidate_directory=value['files']['candidate_directory'],
            expected_candidate_adapter=None if value['candidate'] is None else value['candidate']['adapter'],
            expected_candidate_file_sha256=None if value['candidate'] is None else value['candidate']['file_sha256'],
            expected_candidate_record_sha256=None if value['candidate'] is None else value['candidate']['record_sha256'],
            expected_candidate_result_sha256=None if value['candidate'] is None else value['candidate']['result_sha256'])

    def candidate(self):
        # An unchanged candidate is legal material; this does not select it.
        directory = self.root / 'trained' / 'execution'
        directory.mkdir(parents=True)
        training_input = copy.deepcopy(self.value)
        training_input['output'] = str(directory)
        runtime.save(directory.parent / 'parent-step-input.json', training_input)
        (directory / 'wrapped-adapter.json').write_bytes(self.fixture.adapter_path.read_bytes())
        (directory / 'artifact.safetensors').write_bytes(self.fixture.artifact_path.read_bytes())
        (directory / 'target-contract.json').write_bytes(self.fixture.contract_path.read_bytes())
        pins = dict(adapter=self.aid, file_sha256=self.fixture.sha)
        record = dict(schema='llm-runtime-parent-candidate-v1', scope=step.SCOPE, operation='train',
            attempt_binding=step.attempt_binding(training_input), input=runtime.identity(training_input),
            contract=self.cid, parent=self.value['parent'], candidate=pins, flags=dict(step.FALSES))
        runtime.save(directory / 'parent-candidate.json', record)
        # Explicit fabricated receipt fixtures only test rejection/binding. They
        # are never supplied to a model acceptance path or called execution proof.
        receipt = dict(schema='llm-runtime-parent-step-actual-v1', scope=step.SCOPE, operation='train',
            attempt_id=training_input['attempt_id'], attempt_binding=step.attempt_binding(training_input),
            input=runtime.identity(training_input), source=training_input['source'],
            experiment=training_input['experiment'], parent=training_input['parent'],
            parent_preflight=step.preflight(training_input)[6], parent_readback=self.aid,
            actual_backend='cpu', actual_device='cpu', actual_threads=self.plan['threads'],
            torch_cuda=None, environment={name: 'fabricated-boundary-test-not-execution' for name in
                ('torch', 'transformers', 'peft', 'safetensors', 'tokenizers', 'numpy', 'accelerate')},
            outcome='success', observed_wall_ns=1, training={'steps': self.plan['training_steps']},
            candidate=pins, unchanged_parent=True, **step.FALSES)
        runtime.save(directory / 'actual-receipt.json', receipt)
        result = dict(schema='llm-runtime-parent-step-result-v1', scope=step.SCOPE,
            input=runtime.identity(training_input), attempt_binding=step.attempt_binding(training_input),
            supervisor=dict(outcome='success', stop_reason=None), outcome='success',
            completion_verified=True, actual_receipt_sha256=runtime.file_sha(directory / 'actual-receipt.json'),
            flags=dict(step.FALSES))
        runtime.save(directory.parent / 'parent-step-result.json', result)
        value = copy.deepcopy(self.value)
        value.update(operation='evaluate', candidate=dict(**pins,
            record_sha256=runtime.file_sha(directory / 'parent-candidate.json'),
            result_sha256=runtime.file_sha(directory.parent / 'parent-step-result.json')))
        value['files']['candidate_directory'] = str(directory)
        return value, record, directory

    def test_exact_byte_preflight_has_all_factors_without_importing_tensor_runtime(self):
        with patch.object(runtime, 'runtime_import', side_effect=AssertionError('no model imports')) as imports:
            result = step.preflight(self.value)
        self.assertEqual(result[4], self.fixture.material)
        self.assertEqual((result[6]['factor_tensors'], result[6]['factor_bytes']), (120, 921600))
        self.assertFalse(Path(self.value['output']).parent.exists())
        imports.assert_not_called()

    def test_all_three_parent_pins_fail_before_output_or_dispatch(self):
        for name in ('contract', 'adapter', 'file_sha256'):
            changed = copy.deepcopy(self.value); changed['parent'][name] = 'f' * 64
            with self.subTest(pin=name), patch.object(runtime, 'supervise') as supervise, \
                    patch.object(runtime, 'runtime_import') as imports, self.assertRaises(ValueError):
                step.run(self.arguments(changed))
            supervise.assert_not_called(); imports.assert_not_called()
            self.assertFalse(Path(changed['output']).parent.exists())

    def test_attempt_identity_is_bounded_nonzero_hex_and_affects_binding(self):
        for attempt in (True, '', 'x' * 64, 'a' * 65, 'A' * 64, '0' * 64):
            changed = copy.deepcopy(self.value); changed['attempt_id'] = attempt
            with self.subTest(attempt=attempt), self.assertRaises(ValueError): step.preflight(changed)
        changed = copy.deepcopy(self.value); changed['attempt_id'] = '2' * 64
        self.assertNotEqual(step.attempt_binding(changed), step.attempt_binding(self.value))
        self.assertEqual(step.preflight(changed)[4], self.fixture.material)

    def test_old_source_plan_and_changed_source_tuple_are_rejected(self):
        changed = copy.deepcopy(self.value); changed['source']['runtime'] = 'f' * 64
        with self.assertRaisesRegex(ValueError, 'PARENT_STEP_SOURCE'): step.preflight(changed)
        old = copy.deepcopy(self.plan); old['runtime_source'] = 'f' * 64
        runtime.save(self.root / 'plan.json', old)
        changed = copy.deepcopy(self.value); changed['experiment'] = runtime.identity(old)
        with self.assertRaisesRegex(ValueError, 'PARENT_STEP_EXPERIMENT'): step.preflight(changed)

    def test_old_contract_cannot_be_relabelled_with_current_plan(self):
        old = copy.deepcopy(self.plan); old['runtime_source'] = 'f' * 64
        contract, raw, cid = runtime.contract_from_inventory(self.contract['backbone']['index'],
            'explicit fixture template', self.config, self.manifest, old)
        self.fixture.contract_path.write_bytes(raw)
        adapter = copy.deepcopy(self.fixture.adapter); adapter['contract'] = cid
        raw, aid = runtime.contract_module().freeze_wrapped_adapter(adapter, contract, cid)
        self.fixture.adapter_path.write_bytes(raw)
        changed = copy.deepcopy(self.value); changed['parent'].update(contract=cid, adapter=aid)
        with self.assertRaisesRegex(ValueError, 'PARENT_STEP_CURRENT_CONTRACT'): step.preflight(changed)

    def test_recipe_changes_cannot_hide_under_a_rehashed_plan(self):
        plan = copy.deepcopy(self.plan); plan['recipes']['candidate']['learning_rate'] = '100'
        runtime.save(self.root / 'plan.json', plan)
        changed = copy.deepcopy(self.value); changed['experiment'] = runtime.identity(plan)
        with self.assertRaisesRegex(ValueError, 'PARENT_STEP_EXACT_PLAN'): step.preflight(changed)

    def test_candidate_exact_record_and_same_attempt_parent_bindings(self):
        value, _, _ = self.candidate()
        self.assertEqual(step.preflight(value)[5], self.fixture.material)
        for mutate in (lambda v: v.update(attempt_id='2' * 64),
                       lambda v: v['candidate'].update(record_sha256='f' * 64),
                       lambda v: v['candidate'].update(file_sha256='f' * 64)):
            changed = copy.deepcopy(value); mutate(changed)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError): step.preflight(changed)

    def test_rehashed_wrong_candidate_operation_parent_or_authority_still_refuse(self):
        value, record, directory = self.candidate()
        for mutate in (lambda r: r.update(operation='readback'),
                       lambda r: r['parent'].update(adapter='f' * 64),
                       lambda r: r['flags'].update(adoption=True),
                       lambda r: r.update(extra='unrecognized')):
            changed_record = copy.deepcopy(record); mutate(changed_record)
            runtime.save(directory / 'parent-candidate.json', changed_record)
            changed = copy.deepcopy(value)
            changed['candidate']['record_sha256'] = runtime.file_sha(directory / 'parent-candidate.json')
            with self.subTest(mutate=mutate), self.assertRaises(ValueError): step.preflight(changed)

    def test_file_role_swaps_and_candidate_in_readback_refuse(self):
        changed = copy.deepcopy(self.value)
        changed['files']['parent_adapter'] = changed['files']['parent_artifact']
        with self.assertRaises(ValueError): step.preflight(changed)
        value, _, _ = self.candidate(); value['operation'] = 'readback'
        with self.assertRaisesRegex(ValueError, 'PARENT_STEP_CANDIDATE_ROLE'): step.preflight(value)

    def test_failed_dispatch_uses_original_budget_and_cannot_be_reported_as_success(self):
        with patch.object(runtime, 'supervise', return_value=dict(outcome='failed',
                stop_reason='rss-observation-unavailable')) as supervise, \
                self.assertRaisesRegex(ValueError, 'PARENT_STEP_CHILD_FAILED'):
            step.run(self.arguments())
        command, _, budget = supervise.call_args.args
        self.assertEqual(budget, self.plan['training_budget'])
        self.assertIsNone(supervise.call_args.kwargs['exit_observation'])
        self.assertIn('parent-step', command)
        result = runtime.read_json(Path(self.value['output']).parent / 'parent-step-result.json')
        self.assertEqual(result['supervisor']['outcome'], 'failed')
        self.assertEqual(result['outcome'], 'failed')
        self.assertIs(result['completion_verified'], False)
        self.assertTrue(all(result['flags'][k] is False for k in step.FALSES))

    def test_zero_exit_without_actual_receipt_stays_failed(self):
        with patch.object(runtime, 'supervise', return_value=dict(outcome='success', stop_reason=None)), \
                self.assertRaises(OSError):
            step.run(self.arguments())
        result = runtime.read_json(Path(self.value['output']).parent / 'parent-step-result.json')
        self.assertEqual(result['outcome'], 'failed')
        self.assertIs(result['completion_verified'], False)

    def test_explicit_profiles_and_both_original_budgets_reach_the_same_supervisor(self):
        for profile in runtime.EXIT_PROFILES[1:]:
            plan = runtime.experiment_plan(self.manifest, exit_observation=profile)
            runtime.save(self.root / 'plan.json', plan)
            contract, raw, cid = runtime.contract_from_inventory(self.contract['backbone']['index'],
                'explicit fixture template', self.config, self.manifest, plan)
            self.fixture.contract_path.write_bytes(raw)
            adapter = copy.deepcopy(self.fixture.adapter); adapter['contract'] = cid
            raw, aid = runtime.contract_module().freeze_wrapped_adapter(adapter, contract, cid)
            self.fixture.adapter_path.write_bytes(raw)
            for operation, budget_name in (('train', 'training_budget'), ('readback', 'inference_budget')):
                changed = copy.deepcopy(self.value)
                changed.update(operation=operation, experiment=runtime.identity(plan),
                    output=str(self.root / (profile + '-' + operation) / 'execution'))
                changed['parent'].update(contract=cid, adapter=aid)
                with self.subTest(operation=operation), patch.object(runtime, 'supervise', return_value=dict(
                        outcome='failed', stop_reason='rss-observation-unavailable')) as supervise, \
                        self.assertRaisesRegex(ValueError, 'PARENT_STEP_CHILD_FAILED'):
                    step.run(self.arguments(changed))
                self.assertEqual(supervise.call_args.args[2], plan[budget_name])
                self.assertEqual(supervise.call_args.kwargs['exit_observation'], plan['exit_observation'])

    def test_parent_rejects_every_schema_profile_mix_before_output_or_dispatch(self):
        pairs = [(profile, 'llm-runtime-public-pilot-plan-v'+str(index+1))
            for own,profile in enumerate(runtime.EXIT_PROFILES)
            for index in range(len(runtime.EXIT_PROFILES)) if own != index]
        for source_profile, wrong_schema in pairs:
            plan = runtime.experiment_plan(self.manifest, exit_observation=source_profile)
            plan['schema'] = wrong_schema
            runtime.save(self.root / 'plan.json', plan)
            changed = copy.deepcopy(self.value); changed['experiment'] = runtime.identity(plan)
            with self.subTest(profile=source_profile), \
                    patch.object(runtime,'supervise',side_effect=AssertionError('must not dispatch')), \
                    self.assertRaisesRegex(ValueError,'EXIT_OBSERVER_'):
                step.run(self.arguments(changed))
            self.assertFalse(Path(changed['output']).parent.exists())

    def test_candidate_without_completed_training_and_bound_original_input_refuses(self):
        value, _, directory = self.candidate()
        result_path = directory.parent / 'parent-step-result.json'
        original = runtime.read_json(result_path)
        for mutate in (lambda r: r.update(outcome='failed'),
                       lambda r: r['supervisor'].update(outcome='failed', stop_reason='rss-observation-unavailable'),
                       lambda r: r.update(completion_verified=False),
                       lambda r: r.update(actual_receipt_sha256='f' * 64)):
            result = copy.deepcopy(original); mutate(result); runtime.save(result_path, result)
            changed = copy.deepcopy(value)
            changed['candidate']['result_sha256'] = runtime.file_sha(result_path)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError): step.preflight(changed)
        runtime.save(result_path, original)
        path = directory.parent / 'parent-step-input.json'
        training_input = runtime.read_json(path); training_input['attempt_id'] = '9' * 64
        runtime.save(path, training_input)
        with self.assertRaisesRegex(ValueError, 'PARENT_STEP_TRAINING_INPUT'): step.preflight(value)

    def test_candidate_missing_or_failed_actual_training_receipt_refuses(self):
        value, _, directory = self.candidate()
        path = directory / 'actual-receipt.json'
        report = runtime.read_json(path); report['outcome'] = 'failed'
        runtime.save(path, report)
        with self.assertRaisesRegex(ValueError, 'PARENT_STEP_COMPLETION_CONTEXT'): step.preflight(value)
        path.unlink()
        with self.assertRaises(OSError): step.preflight(value)

    def test_child_input_and_file_role_fail_before_model_import_or_output(self):
        changed = copy.deepcopy(self.value); changed['parent']['file_sha256'] = 'f' * 64
        frozen = self.root / 'input.json'; runtime.save(frozen, changed)
        args = argparse.Namespace(parent_step_input=str(frozen), expected_parent_step_input=runtime.identity(changed),
            materials=changed['files']['materials'], plan=changed['files']['plan'], output=changed['output'], role='candidate')
        with patch.object(runtime, 'runtime_import') as imports, self.assertRaises(ValueError): step.child(args)
        imports.assert_not_called()
        self.assertFalse(Path(changed['output']).parent.exists())
        args.expected_parent_step_input = 'e' * 64
        with self.assertRaisesRegex(ValueError, 'PARENT_STEP_INPUT_PIN'): step.child(args)

    def test_readback_preflight_is_read_only_and_never_makes_a_candidate(self):
        changed = copy.deepcopy(self.value); changed['operation'] = 'readback'
        paths = [Path(changed['files'][k]) for k in ('parent_contract', 'parent_adapter', 'parent_artifact')]
        before = [(p.stat().st_mtime_ns, p.read_bytes()) for p in paths]
        step.preflight(changed)
        self.assertEqual(before, [(p.stat().st_mtime_ns, p.read_bytes()) for p in paths])
        self.assertFalse(Path(changed['output']).parent.exists())

    def test_actual_child_wiring_loads_parent_once_before_training_or_candidate_copy(self):
        source = inspect.getsource(step.child)
        self.assertLess(source.index('preflight(value)'), source.index('runtime.runtime_import'))
        self.assertLess(source.index("'parent-byte-readback'"), source.index("'training'"))
        self.assertLess(source.index("'parent-byte-readback'"), source.index("'candidate-byte-readback'"))
        calls = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call) and
                 isinstance(n.func, ast.Attribute) and n.func.attr == 'insert_lora']
        self.assertEqual(len(calls), 1)
        self.assertNotIn('load_file(', source)
        self.assertNotIn('gain', source)
        self.assertNotIn('parent-step', inspect.getsource(runtime.run))

    def test_cli_exposes_real_parent_step_operations_without_optional_model_import(self):
        result = subprocess.run([sys.executable, str(Path(runtime.__file__)), 'parent-step', '--help'],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('{train,evaluate,readback}', result.stdout)
        self.assertIn('--expected-parent-file-sha256', result.stdout)


if __name__ == '__main__':
    unittest.main()
