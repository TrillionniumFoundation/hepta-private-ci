"""Real tiny-decoder behavior tests; no pretrained-memory capability claims."""

import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch
from peft import get_peft_model_state_dict
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace
from transformers import LlamaConfig, LlamaForCausalLM, PreTrainedTokenizerFast

from parametric_model import SourceMemoryCell, completion_loss, optimizer_module
from pretrained import frozen_digest


TEMPLATES = ["What is the {relation} of {entity}?"]


def fact(entity, value, source):
    return dict(
        scope="alpha",
        entity=entity,
        relation="color",
        value=value,
        source_digest=source * 64,
    )


class SourceMemoryCellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temporary.name) / "base"
        cls.base.mkdir()
        cls.threads = torch.get_num_threads()
        torch.set_num_threads(1)
        torch.manual_seed(123)
        vocabulary = [
            "[UNK]",
            "[BOS]",
            "[EOS]",
            "red",
            "blue",
            "green",
            "one",
            "two",
            "three",
            "alpha",
            "color",
            "What",
            "is",
            "the",
            "of",
            "?",
            "Scope",
            ":",
            "Answer",
        ]
        tokenizer = Tokenizer(
            WordLevel(dict(zip(vocabulary, range(len(vocabulary)))), unk_token="[UNK]")
        )
        tokenizer.pre_tokenizer = Whitespace()
        fast = PreTrainedTokenizerFast(
            tokenizer_object=tokenizer,
            unk_token="[UNK]",
            bos_token="[BOS]",
            eos_token="[EOS]",
            pad_token="[UNK]",
            model_max_length=256,
        )
        fast.chat_template = "{% for message in messages %}{{ message['content'] }} {% endfor %}{% if add_generation_prompt %}Answer: {% endif %}"
        fast.save_pretrained(cls.base)
        model = LlamaForCausalLM(
            LlamaConfig(
                vocab_size=len(vocabulary),
                hidden_size=16,
                intermediate_size=32,
                num_hidden_layers=1,
                num_attention_heads=2,
                num_key_value_heads=2,
                max_position_embeddings=256,
                eos_token_id=2,
                pad_token_id=0,
            )
        )
        model.save_pretrained(cls.base, safe_serialization=True)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.threads)
        cls.temporary.cleanup()

    def cell(self):
        result = SourceMemoryCell(self.base)
        result.reset("alpha")
        return result

    def test_actual_exposure_masking_and_frozen_matched_generation(self):
        cell = self.cell()
        facts = [fact("one", "red", "a"), fact("two", "blue", "b")]
        with patch(
            "parametric_model.completion_loss", wraps=completion_loss
        ) as observed:
            receipt = cell.fit_sources(facts, 1, 0.001, TEMPLATES)
        self.assertEqual(sorted(receipt["fact_visits"]), [0, 1])
        visited = receipt["fact_visits"].index(1)
        self.assertEqual(receipt["roots"], [facts[visited]["source_digest"]])
        ids, labels = observed.call_args.args[1:]
        start = next(i for i, token in enumerate(labels) if token != -100)
        self.assertEqual(labels, [-100] * start + ids[start:])
        self.assertNotIn(ids[start], ids[:start])
        self.assertGreater(receipt["adapter_delta_squared_norm"], 0)
        self.assertEqual(receipt["initialization"], "frozen_base")
        self.assertIsNone(receipt["learned_parent_manifest_sha256"])
        self.assertEqual(frozen_digest(cell.reader.model), cell.reader.base_digest)
        query = ["What is the color of one?"]
        base, memory = cell.generate(query, False)[0], cell.generate(query, True)[0]
        self.assertEqual(base["prompt_token_ids"], memory["prompt_token_ids"])
        self.assertEqual(base["evidence"], memory["evidence"])
        self.assertEqual(memory["evidence"], [])
        self.assertEqual(
            memory["text"],
            cell.reader.tokenizer.decode(
                memory["token_ids"],
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            ),
        )
        self.assertTrue(
            all(
                not p.requires_grad and p.grad is None
                for p in cell.reader.model.parameters()
            )
        )

    def test_verified_parent_continuation_and_clean_reset(self):
        cell = self.cell()
        original = cell.fit_sources([fact("one", "red", "a")], 2, 0.001, TEMPLATES)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "adapter"
            with patch("parametric_model.os.fsync", wraps=os.fsync) as flushed:
                manifest = cell.save(path, original)
            self.assertEqual(flushed.call_count, 3 if os.name == "nt" else 5)
            self.assertEqual(cell.last_save_receipt["manifest_sha256"], manifest)
            self.assertFalse(cell.last_save_receipt["power_loss_recovery_verified"])
            child = self.cell()
            child.load(
                path,
                expected_manifest_sha256=manifest,
                scope="alpha",
                allowed_roots={"a" * 64},
                revoked=set(),
            )
            self.assertTrue(
                all(
                    torch.equal(v, get_peft_model_state_dict(child.reader.model)[k])
                    for k, v in get_peft_model_state_dict(cell.reader.model).items()
                )
            )
            receipt = child.fit_sources([fact("two", "blue", "b")], 1, 0.001, TEMPLATES)
            self.assertEqual(receipt["initialization"], "verified_adapter")
            self.assertEqual(receipt["learned_parent_manifest_sha256"], manifest)
            self.assertEqual(receipt["roots"], ["a" * 64, "b" * 64])
            receipt["initialization"] = "frozen_base"
            with self.assertRaises(ValueError):
                child.save(Path(directory) / "forged", receipt)
            self.assertFalse((Path(directory) / "forged").exists())
            continuation = child.fit_sources(
                [fact("three", "green", "c")], 1, 0.001, TEMPLATES
            )
            self.assertEqual(continuation["initialization"], "in_memory_adapter")
            self.assertIsNotNone(continuation["previous_write_receipt_sha256"])
            child.reset("alpha")
            clean = child.fit_sources([fact("two", "blue", "b")], 1, 0.001, TEMPLATES)
            self.assertEqual(
                (
                    clean["initialization"],
                    clean["learned_parent_manifest_sha256"],
                    clean["roots"],
                ),
                ("frozen_base", None, ["b" * 64]),
            )
            child.load(
                path,
                expected_manifest_sha256=manifest,
                scope="alpha",
                allowed_roots={"a" * 64},
                revoked=set(),
            )
            with torch.no_grad():
                next(iter(get_peft_model_state_dict(child.reader.model).values())).add_(
                    1
                )
            with self.assertRaises(ValueError):
                child.fit_sources([fact("two", "blue", "b")], 1, 0.001, TEMPLATES)
            rejected = self.cell()
            with self.assertRaises(ValueError):
                rejected.load(
                    path,
                    expected_manifest_sha256=manifest,
                    scope="alpha",
                    allowed_roots={"a" * 64},
                    revoked={"a" * 64},
                )
            self.assertTrue(rejected.reader.quarantined)

    def test_margin_charges_both_forwards_and_source_lineages(self):
        cell = self.cell()
        receipt = cell.fit_sources(
            [fact("one", "red", "a"), fact("two", "blue", "b")],
            1,
            0.001,
            TEMPLATES,
            objective="source_margin",
        )
        self.assertEqual(sorted(receipt["fact_visits"]), [0, 1])
        self.assertEqual(receipt["roots"], ["a" * 64, "b" * 64])
        self.assertEqual(
            [
                a + b
                for a, b in zip(receipt["fact_visits"], receipt["negative_fact_visits"])
            ],
            [1, 1],
        )
        self.assertEqual(receipt["actual_model_forwards"], 2)
        self.assertEqual(receipt["supervised_tokens"], 4)
        self.assertGreater(receipt["input_tokens"], receipt["supervised_tokens"])
        self.assertTrue(
            all(not p.requires_grad for p in cell.reader.model.parameters())
        )

    def test_seeded_epochs_cover_every_source_template_and_reproduce(self):
        facts = [fact("one", "red", "a"), fact("two", "blue", "b")]
        templates = TEMPLATES + ["{entity} has which {relation}?"]
        first = self.cell().fit_sources(facts, 8, 0.001, templates)
        repeated = self.cell().fit_sources(facts, 8, 0.001, templates)
        self.assertEqual(first["example_visits"], [2, 2, 2, 2])
        self.assertEqual(first["schedule_sha256"], repeated["schedule_sha256"])
        self.assertEqual(first["schedule_indices"], repeated["schedule_indices"])
        for offset in (0, 4):
            self.assertEqual(
                sorted(first["schedule_indices"][offset : offset + 4]), [0, 1, 2, 3]
            )

    def test_rejects_source_leakage_bounds_and_numeric_errors(self):
        valid = fact("one", "red", "a")
        invalid = [
            dict(facts=[valid | {"answer": "red"}]),
            dict(facts=[valid, copy.deepcopy(valid)]),
            dict(facts=[valid | {"scope": "beta"}]),
            dict(facts=[valid | {"source_digest": "invalid"}]),
            dict(facts=[valid | {"value": " ".join(["red"] * 16)}]),
            dict(templates=["{entity} {relation} {value}"]),
            dict(templates=["{entity.__class__} {relation}"]),
            dict(templates=["{entity} {relation}" + " word" * 193]),
            dict(steps=True),
            dict(steps=4097),
            dict(learning_rate=float("nan")),
            dict(facts=[valid], objective="source_margin"),
        ]
        for change in invalid:
            with self.subTest(change=change):
                cell = self.cell()
                arguments = dict(
                    facts=[valid], steps=1, learning_rate=0.001, templates=TEMPLATES
                )
                arguments.update(change)
                with self.assertRaises(ValueError):
                    cell.fit_sources(**arguments)
                self.assertTrue(cell.reader.quarantined)
                with self.assertRaises(ValueError):
                    cell.reset("alpha")

    def test_partial_nonfinite_write_is_quarantined_and_frozen(self):
        cell = self.cell()
        original_step = torch.optim.AdamW.step

        def corrupt(optimizer, *args, **kwargs):
            result = original_step(optimizer, *args, **kwargs)
            with torch.no_grad():
                optimizer.param_groups[0]["params"][0].fill_(float("nan"))
            return result

        with patch.object(torch.optim.AdamW, "step", corrupt):
            with self.assertRaises(ValueError):
                cell.fit_sources([fact("one", "red", "a")], 1, 0.001, TEMPLATES)
        self.assertTrue(cell.reader.quarantined)
        self.assertTrue(
            all(
                not p.requires_grad and p.grad is None
                for p in cell.reader.model.parameters()
            )
        )
        with self.assertRaises(ValueError):
            cell.generate(["What is the color of one?"])

    def test_save_rejects_weights_changed_after_the_receipt(self):
        cell = self.cell()
        cell.fit_sources([fact("one", "red", "a")], 1, 0.001, TEMPLATES)
        with torch.no_grad():
            next(
                p for name, p in cell.reader.model.named_parameters() if "lora_" in name
            ).add_(1)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                cell.save(Path(directory) / "corrupt")
            self.assertFalse((Path(directory) / "corrupt").exists())
        self.assertTrue(cell.reader.quarantined)

    def test_global_hooks_cannot_modify_foreign_parameters(self):
        registrations = (
            optimizer_module.register_optimizer_step_pre_hook,
            optimizer_module.register_optimizer_step_post_hook,
        )
        for register in registrations:
            for during_loss in (False, True):
                with self.subTest(register=register.__name__, during_loss=during_loss):
                    cell, foreign, handles = (
                        self.cell(),
                        torch.nn.Parameter(torch.tensor(7.0)),
                        [],
                    )

                    def corrupt(*args, **kwargs):
                        with torch.no_grad():
                            foreign.add_(1)

                    def loss_with_hook(*args, **kwargs):
                        loss = completion_loss(*args, **kwargs)
                        handles.append(register(corrupt))
                        return loss

                    try:
                        if not during_loss:
                            handles.append(register(corrupt))
                        with patch(
                            "parametric_model.completion_loss",
                            side_effect=loss_with_hook,
                        ):
                            with self.assertRaises(ValueError):
                                cell.fit_sources(
                                    [fact("one", "red", "a")], 1, 0.001, TEMPLATES
                                )
                        self.assertEqual(float(foreign.detach()), 7.0)
                        self.assertTrue(cell.reader.quarantined)
                    finally:
                        for handle in handles:
                            handle.remove()

    def test_flush_failure_does_not_return_an_admitted_snapshot(self):
        cell = self.cell()
        cell.fit_sources([fact("one", "red", "a")], 1, 0.001, TEMPLATES)
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "parametric_model.os.fsync", side_effect=OSError("flush failed")
            ):
                with self.assertRaises(OSError):
                    cell.save(Path(directory) / "unflushed")
        self.assertIsNone(cell.last_save_receipt)
        self.assertTrue(cell.reader.quarantined)


if __name__ == "__main__":
    unittest.main()
