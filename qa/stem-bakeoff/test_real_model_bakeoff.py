"""Tiny execution/replay regressions; fixtures are never model-quality evidence.

Only checkpoint/archive trust anchors use local fixtures. Tokenization, a real
Transformers forward, training, artifact reload and Head fanout all execute.
"""

from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import torch

from cell_head_training import load_head_artifact
import prepare_news_cohorts as data
from real_encoder import CANDIDATES, FrozenRealEncoder
from real_head_fanout import measure_fanout
import real_model_bakeoff as runner
from teacher_snapshot import inventory


def fixture_archive(path):
    publishers = {ood: next(f"fixture publisher {i}" for i in range(100)
                           if data.publisher_is_ood(f"fixture publisher {i}") == ood)
                  for ood in (False, True)}
    records = []
    for split, month in data.WINDOWS.items():
        timestamp = int(datetime.strptime(month + "-02", "%Y-%m-%d")
                        .replace(tzinfo=timezone.utc).timestamp() * 1000)
        for category, label in data.LABELS.items():
            source = f"{split}-{label}"
            records.append("\t".join((source, f"class{label} {split} specimen",
                "https://fixture.invalid/" + source, publishers[split == "ood"],
                category, "story-" + source, "fixture.invalid", str(timestamp))))
    with zipfile.ZipFile(path, "w") as zipped:
        zipped.writestr(zipfile.ZipInfo("newsCorpora.csv", (1980, 1, 1, 0, 0, 0)),
                        "\n".join(records) + "\n")


def fixture_checkpoint(path):
    from tokenizers import Tokenizer, models, pre_tokenizers
    from transformers import ModernBertConfig, ModernBertModel, PreTrainedTokenizerFast
    config = ModernBertConfig(vocab_size=16, hidden_size=8, intermediate_size=16,
        num_hidden_layers=1, num_attention_heads=2, pad_token_id=0, cls_token_id=1,
        sep_token_id=2, bos_token_id=1, eos_token_id=2)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(19)
        model = ModernBertModel(config)
    model.save_pretrained(path)
    vocabulary = {"[PAD]": 0, "[UNK]": 1, **{f"class{i}": i + 2 for i in range(4)}}
    tokenizer = Tokenizer(models.WordLevel(vocabulary, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    PreTrainedTokenizerFast(tokenizer_object=tokenizer, pad_token="[PAD]",
                           unk_token="[UNK]").save_pretrained(path)
    return sum(p.numel() for p in model.parameters())


class RealModelBakeoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous_threads = torch.get_num_threads()
        cls.previous_rng = torch.random.get_rng_state()
        cls.addClassCleanup(torch.set_num_threads, cls.previous_threads)
        cls.addClassCleanup(torch.random.set_rng_state, cls.previous_rng)
        cls.temporary = cls.enterClassContext(tempfile.TemporaryDirectory())
        cls.root = Path(cls.temporary)
        cls.archive = cls.root / "tiny-source.zip"
        fixture_archive(cls.archive)
        cls.enterClassContext(patch.object(data, "ARCHIVE_SHA256", data.sha(cls.archive.read_bytes())))
        cls.enterClassContext(patch.object(data, "ARCHIVE_URL", "https://fixture.invalid/tiny-source.zip"))
        cls.cohorts = cls.root / "cohorts"
        data.prepare_archive(cls.archive, cls.cohorts, counts={name: 4 for name in data.WINDOWS})
        cls.snapshot = cls.root / "checkpoint"
        parameters = fixture_checkpoint(cls.snapshot)
        facts = inventory(cls.snapshot)
        weight_hash = next(item["sha256"] for item in facts["entries"]
                           if item["path"] == "model.safetensors")
        cls.enterClassContext(patch.dict(CANDIDATES["granite97m"],
            {"weight_sha256": weight_hash, "width": 8, "checkpoint_parameters": parameters}))
        cls.arguments = {"candidate": "granite97m", "snapshot": cls.snapshot,
            "inventory_sha256": facts["inventory_sha256"], "cohorts": cls.cohorts,
            "archive": cls.archive, "operator_accepted_terms": True,
            "batch_size": 4, "threads": 1, "scales": (1, 8), "repeats": 1}
        owners = []
        def owner_factory(**kwargs):
            owner = FrozenRealEncoder(**kwargs)
            owners.append(owner)
            return owner
        with patch.object(runner, "FrozenRealEncoder", side_effect=owner_factory), redirect_stdout(io.StringIO()):
            cls.report = runner.run_bakeoff(**cls.arguments, output=cls.root / "first")
        cls.owner = owners[0]
        artifact = cls.report["head_artifacts"]["gated"]
        cls.trained = load_head_artifact(cls.root / "first" / artifact["directory"],
            expected_manifest_sha256=artifact["manifest_sha256"], expected_identity=cls.owner.identity)

    def test_complete_replay_is_reproducible_and_freezes_shared_encoder(self):
        first = self.report
        self.assertEqual(first["encoder"]["encoded_source_rows"], 20)
        self.assertEqual(first["encoder"]["model_forward_calls_for_dataset"], 5)
        self.assertEqual(first["encoder"]["tensor_sha256_before"], first["encoder"]["tensor_sha256_after"])
        self.assertTrue(first["encoder"]["weights_unchanged_after_fanout"])
        self.assertEqual(first["encoder"]["trainable_parameter_count"], 0)
        self.assertEqual(len(first["independently_trained_private_cells"]), 4)
        self.assertTrue(all(row["reload_prediction_exact"] for row in first["head_artifacts"].values()))
        self.assertFalse(first["scope"]["production_activation_allowed"])
        with redirect_stdout(io.StringIO()):
            second = runner.run_bakeoff(**self.arguments, output=self.root / "second")
        self.assertEqual(first["plan_sha256"], second["plan_sha256"])
        self.assertEqual(first["feature_manifests_sha256"], second["feature_manifests_sha256"])
        for mode in ("linear", "gated"):
            self.assertEqual(first["heads"][mode]["trained_tensor_sha256"],
                             second["heads"][mode]["trained_tensor_sha256"])
            self.assertEqual(first["heads"][mode]["splits"], second["heads"][mode]["splits"])
        manifest = json.loads((self.root / "first" / "plan.json").read_bytes())
        self.assertEqual(manifest["dataset_manifest_sha256"],
                         data.sha((self.cohorts / "manifest.json").read_bytes()))

    def test_precomputed_fanout_never_executes_encoder_and_allocates_n_heads(self):
        bundle = self.owner.encode_text(["class0 cached specimen"])
        calls = self.owner._calls
        before = runner.model_tensor_digest(self.owner._model)
        original = bundle.read_global()
        with patch.object(self.owner._model, "forward", side_effect=AssertionError("Encoder rerun")):
            report = measure_fanout(self.owner, bundle, self.trained, scales=(1, 8), repeats=2)
        self.assertEqual(self.owner._calls, calls)
        self.assertEqual(before, runner.model_tensor_digest(self.owner._model))
        self.assertTrue(torch.equal(original, bundle.read_global()))
        first, eighth = report["measurements"]
        self.assertGreater(first["actual_private_head_tensor_bytes"], 0)
        self.assertEqual(eighth["actual_private_head_tensor_bytes"],
                         8 * first["actual_private_head_tensor_bytes"])
        self.assertEqual(eighth["private_head_instances"], 8)
        self.assertEqual(eighth["additional_encoder_forward_calls"], 0)
        self.assertEqual(first["actual_shared_encoder_tensor_bytes"], eighth["actual_shared_encoder_tensor_bytes"])
        with patch("real_head_fanout.copy.deepcopy", side_effect=lambda head: head):
            with self.assertRaisesRegex(ValueError, "alias"):
                measure_fanout(self.owner, bundle, self.trained, scales=(1,), repeats=1)

    def test_mismatched_source_receipt_or_unfrozen_encoder_fails_before_fanout(self):
        bundle = self.owner.encode_text(["class1 cached specimen"])
        receipt = self.owner.last_receipt
        self.owner.last_receipt = {**receipt, "feature_bundle_sha256": "0" * 64}
        try:
            with self.assertRaisesRegex(ValueError, "receipt"):
                measure_fanout(self.owner, bundle, self.trained, scales=(1,), repeats=1)
        finally:
            self.owner.last_receipt = receipt
        self.owner._model.train()
        try:
            with self.assertRaisesRegex(ValueError, "frozen"):
                measure_fanout(self.owner, bundle, self.trained, scales=(1,), repeats=1)
        finally:
            self.owner._model.eval()

    def test_invalid_plan_is_rejected_before_data_or_checkpoint_access(self):
        for scales, repeats in (((2,), 1), ((1,), 0), (([1],), 1)):
            with self.subTest(scales=scales, repeats=repeats):
                with self.assertRaisesRegex(ValueError, "fanout plan"):
                    runner.run_bakeoff(candidate="granite97m", snapshot="absent",
                        inventory_sha256="0" * 64, cohorts="absent", archive="absent",
                        output="absent", operator_accepted_terms=True,
                        scales=scales, repeats=repeats)

    def test_encoder_digest_includes_scalar_buffers(self):
        model = torch.nn.Module()
        model.register_buffer("scalar", torch.tensor(1.0))
        first = runner.model_tensor_digest(model)
        model.scalar.add_(1)
        self.assertNotEqual(first, runner.model_tensor_digest(model))


class RssObservationTests(unittest.TestCase):
    def test_proc_self_rss_takes_priority_over_wrong_namespace_psutil(self):
        status = "Pid:\t136888\nVmRSS:\t233816 kB\n"
        with patch.object(runner.Path, "read_text", return_value=status), \
                patch.object(runner.os, "getpid", return_value=5), \
                patch.object(runner.psutil, "Process") as reader:
            reader.return_value.memory_info.return_value.rss = 2_125_824
            self.assertEqual(runner.rss_observation(),
                             {"bytes": 233816 * 1024, "source": "/proc/self/status"})
            reader.assert_not_called()

    def test_mismatched_proc_pid_never_reads_psutil(self):
        with patch.object(runner.Path, "read_text", return_value="Pid:\t136888\n"), \
                patch.object(runner.os, "getpid", return_value=5), \
                patch.object(runner.psutil, "Process") as reader:
            self.assertEqual(runner.rss_observation(), {"bytes": None, "source": "unavailable"})
            reader.assert_not_called()

    def test_unreadable_proc_self_has_no_unverified_fallback(self):
        with patch.object(runner.Path, "read_text", side_effect=OSError("unavailable")), \
                patch.object(runner.psutil, "Process") as reader:
            self.assertEqual(runner.rss_observation(), {"bytes": None, "source": "unavailable"})
            reader.assert_not_called()

    def test_psutil_fallback_requires_confirmed_self_pid(self):
        with patch.object(runner.Path, "read_text", return_value="Pid:\t5\n"), \
                patch.object(runner.os, "getpid", return_value=5), \
                patch.object(runner.psutil, "Process") as reader:
            reader.return_value.memory_info.return_value.rss = 123_456
            self.assertEqual(runner.rss_observation(),
                             {"bytes": 123_456, "source": "psutil-verified-self-pid"})
            reader.assert_called_once_with(5)

    def test_negative_or_malformed_proc_rss_is_not_measurement(self):
        for value in ("-1 kB", "nan kB", "123 bytes", "3.5 kB"):
            with self.subTest(value=value), \
                    patch.object(runner.Path, "read_text", return_value=f"Pid:\t136888\nVmRSS:\t{value}\n"), \
                    patch.object(runner.os, "getpid", return_value=5), \
                    patch.object(runner.psutil, "Process") as reader:
                self.assertEqual(runner.rss_observation(), {"bytes": None, "source": "unavailable"})
                reader.assert_not_called()

    def test_negative_psutil_rss_is_not_measurement(self):
        with patch.object(runner.Path, "read_text", return_value="Pid:\t5\n"), \
                patch.object(runner.os, "getpid", return_value=5), \
                patch.object(runner.psutil, "Process") as reader:
            reader.return_value.memory_info.return_value.rss = -1
            self.assertEqual(runner.rss_observation(), {"bytes": None, "source": "unavailable"})
            reader.assert_called_once_with(5)


if __name__ == "__main__":
    unittest.main()
