"""Actual tiny Llama/GPT2-fast snapshot controls, never pretrained efficacy.

Only the explicit tensor-test environment imports optional Torch/Transformers.
The tiny family has real BF16 weights, tied FP32 parameters and actual forward
computations. It does not qualify the full model, independence or FinalUse.
"""
import builtins
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import llm_base_material as base
import llm_runtime_pilot as runtime


def tiny_material(directory, *, vocabulary=32):
    """Deterministic genuine tensor fixture; no pretrained weights are used."""
    import torch
    from safetensors.torch import save
    from tokenizers import Tokenizer, models, pre_tokenizers
    from transformers import LlamaConfig, LlamaForCausalLM

    config = LlamaConfig(num_hidden_layers=1, hidden_size=8, intermediate_size=16,
        num_attention_heads=2, num_key_value_heads=1, vocab_size=vocabulary,
        max_position_embeddings=128, tie_word_embeddings=True, attention_bias=False,
        mlp_bias=False, rope_theta=100000, rms_norm_eps=1e-5,
        bos_token_id=1, eos_token_id=2, pad_token_id=2).to_dict()
    config.pop('dtype', None)
    config['torch_dtype'] = 'bfloat16'
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(17)
        model = LlamaForCausalLM(LlamaConfig.from_dict(config))
    tensors = {name: value.detach().to(torch.bfloat16).contiguous()
               for name, value in model.named_parameters()}
    vocabulary_map = {'<|endoftext|>': 0, '<|im_start|>': 1, '<|im_end|>': 2,
                      'alpha': 3, 'beta': 4, 'gamma': 5}
    vocabulary_map.update({f'fixture-{i}': i for i in range(6, vocabulary)})
    backend = Tokenizer(models.WordLevel(vocabulary_map, unk_token='<|endoftext|>'))
    backend.pre_tokenizer = pre_tokenizers.WhitespaceSplit()
    added = {str(i): dict(content=token, lstrip=False, normalized=False, rstrip=False,
                         single_word=False, special=True)
             for token, i in vocabulary_map.items() if i < 3}
    tokenizer_config = dict(tokenizer_class='GPT2Tokenizer', added_tokens_decoder=added,
        bos_token='<|im_start|>', eos_token='<|im_end|>', pad_token='<|im_end|>',
        unk_token='<|endoftext|>', additional_special_tokens=['<|im_start|>', '<|im_end|>'],
        chat_template='{{ messages[0]["content"] }}', model_max_length=128,
        add_prefix_space=False, clean_up_tokenization_spaces=False)
    special = {key: tokenizer_config[key] for key in
               ('bos_token', 'eos_token', 'pad_token', 'unk_token', 'additional_special_tokens')}
    blobs = {'model.safetensors': save(tensors), 'config.json': base.canonical(config),
        'generation_config.json': base.canonical(dict(bos_token_id=1, eos_token_id=2, pad_token_id=2)),
        'tokenizer_config.json': base.canonical(tokenizer_config),
        'tokenizer.json': backend.to_str().encode(),
        'special_tokens_map.json': base.canonical(special),
        'README.md': b'explicit tiny untrained Llama fixture, not pretrained model evidence'}
    pins = {name: (len(raw), hashlib.sha256(raw).hexdigest()) for name, raw in blobs.items()}
    manifest = dict(model=runtime.MODEL, revision=runtime.REVISION,
        files={name: dict(size=size, sha256=sha, revision=runtime.REVISION)
               for name, (size, sha) in pins.items()})
    for name, raw in blobs.items():
        (directory / name).write_bytes(raw)
    (directory / 'material-manifest.json').write_bytes(base.canonical(manifest))
    # JSON changes integer object keys (e.g. id2label) to strings. The expected
    # input is the actual encoded configuration, not its pre-encoding builder.
    return pins, manifest, base.decode(blobs['config.json'])


@unittest.skipUnless(os.environ.get('TRNM_ACTUAL_DECODER_TENSOR_TESTS') == '1',
                     'explicit CPU tensor opt-in absent; actual base snapshot NOT_RUN')
class ActualBaseMaterialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch
        from transformers import AutoModelForCausalLM, LlamaForCausalLM
        cls.torch, cls.auto_model, cls.model_class = torch, AutoModelForCausalLM, LlamaForCausalLM
        torch.set_num_threads(1)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.pins, self.manifest, self.config = tiny_material(self.root)
        self.material = base.capture(self.root, self.pins, runtime.MODEL, runtime.REVISION,
                                     self.pins['model.safetensors'][1])
        self.shapes = runtime.contract_module().architecture_shapes(runtime.architecture(self.config))

    def loaded(self, material=None):
        material = material or self.material
        tokenizer = base.tokenizer_from_material(material)
        model, inventory = base.model_from_material(material, self.shapes, self.torch)
        base.bind_loaded(material, model, tokenizer)
        return model, tokenizer, inventory

    def forward(self, model, tokenizer, text='alpha beta gamma alpha'):
        ids = self.torch.tensor([tokenizer.encode(text, add_special_tokens=False)], dtype=self.torch.int64)
        with self.torch.inference_mode():
            return model(input_ids=ids, attention_mask=self.torch.ones_like(ids), use_cache=False).logits

    def test_real_bytes_loading_matches_original_path_loader_and_forward(self):
        from transformers import AutoTokenizer
        reference = self.auto_model.from_pretrained(str(self.root), local_files_only=True,
            trust_remote_code=False, dtype=self.torch.float32, attn_implementation='eager')
        original_tokenizer = AutoTokenizer.from_pretrained(str(self.root), local_files_only=True,
            trust_remote_code=False, use_fast=True)
        original_tokenizer.padding_side = 'left'
        loaded, tokenizer, inventory = self.loaded()
        self.assertEqual(set(inventory), set(self.shapes))
        self.assertTrue(all(item['dtype'] == 'BF16' for item in inventory.values()))
        self.assertEqual(base._tokenizer_state(tokenizer), base._tokenizer_state(original_tokenizer))
        self.assertEqual(loaded.generation_config.to_dict(), reference.generation_config.to_dict())
        self.assertEqual(loaded.lm_head.weight.data_ptr(), loaded.model.embed_tokens.weight.data_ptr())
        for name, shape in self.shapes.items():
            with self.subTest(name=name):
                actual = loaded.get_parameter(name)
                self.assertEqual(actual.dtype, self.torch.float32)
                self.assertEqual(list(actual.shape), shape)
                self.assertTrue(self.torch.equal(actual, reference.get_parameter(name)))
        self.assertTrue(self.torch.equal(self.forward(loaded, tokenizer),
                                         self.forward(reference, original_tokenizer)))
        self.assertEqual(base.loaded_config(loaded, tokenizer, self.manifest), self.config)

    def test_replaced_all_disk_members_cannot_change_captured_model_or_tokenizer(self):
        reference, reference_tokenizer, _ = self.loaded()
        original = self.forward(reference, reference_tokenizer)
        for name in self.pins:
            (self.root / name).write_bytes(b'executable-or-wrong-material-after-capture')
        # All model path discovery is disallowed; a pure in-memory model load
        # must pass None to the standard constructor and supply its config/state.
        normal = self.model_class.from_pretrained
        def in_memory(path, *args, **kwargs):
            self.assertIsNone(path)
            self.assertIn('state_dict', kwargs)
            self.assertIn('generation_config', kwargs)
            return normal(path, *args, **kwargs)
        original_open = builtins.open
        def no_source_open(file, *args, **kwargs):
            if isinstance(file, (str, os.PathLike)) and Path(file).is_relative_to(self.root):
                raise AssertionError('model source path reopened')
            return original_open(file, *args, **kwargs)
        with patch.object(self.model_class, 'from_pretrained', side_effect=in_memory), \
                patch.object(builtins, 'open', side_effect=no_source_open), \
                patch.object(Path, 'open', side_effect=AssertionError('model path reopened')):
            loaded, tokenizer, _ = self.loaded()
        self.assertEqual(tokenizer.encode('alpha beta', add_special_tokens=False), [3, 4])
        self.assertTrue(self.torch.equal(self.forward(loaded, tokenizer), original))
        self.assertEqual(base.loaded_config(loaded, tokenizer, self.manifest), self.config)

    def test_undeclared_adapter_template_index_and_pickle_files_are_never_discovered(self):
        original, original_tokenizer, _ = self.loaded()
        before = self.forward(original, original_tokenizer)
        for name, raw in {
            'adapter_config.json': b'{"base_model_name_or_path":"undeclared-external-path"}',
            'chat_template.jinja': b'poisoned template',
            'model.safetensors.index.json': b'{"weight_map":{"model.norm.weight":"external.bin"}}',
            'pytorch_model.bin': b'not a permitted weight format',
        }.items():
            (self.root / name).write_bytes(raw)
        material = base.capture(self.root, self.pins, runtime.MODEL, runtime.REVISION,
                                self.pins['model.safetensors'][1])
        loaded, tokenizer, _ = self.loaded(material)
        self.assertTrue(self.torch.equal(before, self.forward(loaded, tokenizer)))
        self.assertEqual(base._tokenizer_state(original_tokenizer), base._tokenizer_state(tokenizer))

    def test_unchanged_vocab_size_and_template_do_not_hide_loaded_tokenizer_change(self):
        from tokenizers import Tokenizer
        model, tokenizer, _ = self.loaded()
        changed = json.loads(tokenizer.backend_tokenizer.to_str())
        changed['model']['vocab']['alpha'], changed['model']['vocab']['beta'] = 4, 3
        template, length = tokenizer.chat_template, len(tokenizer)
        tokenizer._tokenizer = Tokenizer.from_str(json.dumps(changed))
        self.assertEqual(len(tokenizer), length)
        self.assertEqual(tokenizer.chat_template, template)
        self.assertEqual(tokenizer.encode('alpha beta', add_special_tokens=False), [4, 3])
        with self.assertRaisesRegex(ValueError, 'BASE_TOKENIZER_CHANGED'):
            base.loaded_config(model, tokenizer, self.manifest)

    def test_actual_rope_and_rms_config_changes_are_refused(self):
        for name, altered in [('rope_theta', 16), ('rms_norm_eps', 0.125)]:
            model, tokenizer, _ = self.loaded()
            setattr(model.config, name, altered)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'BASE_CONFIG_CHANGED'):
                base.loaded_config(model, tokenizer, self.manifest)

    def test_wrong_bf16_inventory_and_nonfinite_refuse_before_model_constructor(self):
        from safetensors.torch import load, save
        source = load(self.material.raw('model.safetensors'))
        name = next(iter(source))
        mutations = []
        floating = dict(source); floating[name] = source[name].float(); mutations.append(('float32', floating))
        missing = dict(source); del missing[name]; mutations.append(('missing', missing))
        extra = dict(source); extra['undeclared.weight'] = source[name].clone(); mutations.append(('extra', extra))
        shape = dict(source); shape[name] = source[name].reshape(-1); mutations.append(('shape', shape))
        nonfinite = {key: value.clone() for key, value in source.items()}
        nonfinite[name].view(-1)[0] = float('nan'); mutations.append(('nonfinite', nonfinite))
        for label, tensors in mutations:
            changed = dict(self.material.files); changed['model.safetensors'] = save(tensors)
            material = base.BaseMaterial(self.material.manifest_raw, tuple(sorted(changed.items())))
            with self.subTest(label=label), \
                    patch.object(self.model_class, 'from_pretrained', side_effect=AssertionError('partial model load')), \
                    self.assertRaises(ValueError):
                base.model_from_material(material, self.shapes, self.torch)

    def test_make_contract_uses_loaded_configuration_even_after_source_directory_removal(self):
        model, tokenizer, _ = self.loaded()
        for path in self.root.iterdir():
            path.unlink()
        plan = runtime.experiment_plan(self.manifest)
        with patch.object(runtime, 'contract_from_inventory', return_value=('tiny-contract-probe',)) as freeze:
            result = runtime.make_contract(model, tokenizer, self.shapes,
                                           self.root, self.manifest, plan)
        self.assertEqual(result, ('tiny-contract-probe',))
        self.assertEqual(freeze.call_args.args[2], self.config)
        self.assertEqual(set(freeze.call_args.args[0]), set(self.shapes))


if __name__ == '__main__':
    unittest.main()
