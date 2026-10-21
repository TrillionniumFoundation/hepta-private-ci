"""No-weight adversarial tests for the teacher media byte snapshot."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
from teacher_media_seal import TeacherMediaSealError, sealed_media_inputs

try:
    import torch
except ImportError:
    torch = None


def _fake_validator(records, root, candidate):
    if candidate != "embeddinggemma2_740m":
        raise ValueError("unexpected candidate")
    conversations, receipts = [], []
    for row in records:
        content, source = [], []
        for modality in ("text", "image", "audio", "video"):
            if modality not in row:
                continue
            if modality == "text":
                value = row[modality]
                content.append({"type": "text", "text": value})
                source.append((modality, hashlib.sha256(value.encode()).hexdigest()))
            else:
                path = Path(root) / row[modality]
                content.append({"type": modality, "url": str(path)})
                source.append((modality, hashlib.sha256(path.read_bytes()).hexdigest()))
        conversations.append([{"role": "user", "content": content}])
        receipts.append(source)
    digest = hashlib.sha256(json.dumps(
        receipts, separators=(",", ":"), sort_keys=True).encode()).hexdigest()
    return conversations, digest


class TeacherMediaSealTests(unittest.TestCase):
    def test_copy_retains_exact_digest_and_survives_source_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "photo.png"
            source.write_bytes(b"frame-at-t0")
            rows = [{"text": "caption", "image": "photo.png"}, {"text": "plain"}]
            conversations, digest = _fake_validator(rows, root, "embeddinggemma2_740m")
            with sealed_media_inputs(
                records=rows, media_root=root, candidate="embeddinggemma2_740m",
                expected_source_digest=digest, original_conversations=conversations,
                validate_records=_fake_validator,
            ) as frozen:
                snapshot = Path(frozen[0][0]["content"][1]["url"])
                self.assertNotEqual(snapshot, source)
                self.assertEqual(snapshot.read_bytes(), b"frame-at-t0")
                source.write_bytes(b"mutated frame")
                self.assertEqual(snapshot.read_bytes(), b"frame-at-t0")
                self.assertEqual(_fake_validator([
                    {"text": "caption", "image": snapshot.name}, {"text": "plain"}
                ], snapshot.parent, "embeddinggemma2_740m")[1], digest)
            self.assertFalse(snapshot.exists())

    def test_mutation_between_preflight_and_copy_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "audio.wav"
            source.write_bytes(b"before")
            rows = [{"audio": "audio.wav"}]
            conversations, digest = _fake_validator(rows, tmp, "embeddinggemma2_740m")
            source.write_bytes(b"after")
            with self.assertRaisesRegex(TeacherMediaSealError, "changed after digest"):
                with sealed_media_inputs(
                    records=rows, media_root=tmp, candidate="embeddinggemma2_740m",
                    expected_source_digest=digest, original_conversations=conversations,
                    validate_records=_fake_validator,
                ):
                    pass

    def test_hardlink_and_symlink_not_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "frame.mp4"
            source.write_bytes(b"frame")
            rows = [{"video": "frame.mp4"}]
            conversations, digest = _fake_validator(rows, tmp, "embeddinggemma2_740m")
            alias = root / "alias.mp4"
            try:
                alias.hardlink_to(source)
            except (OSError, NotImplementedError):
                self.skipTest("hardlinks unsupported")
            with self.assertRaisesRegex(TeacherMediaSealError, "single-link"):
                with sealed_media_inputs(
                    records=rows, media_root=tmp, candidate="embeddinggemma2_740m",
                    expected_source_digest=digest, original_conversations=conversations,
                    validate_records=_fake_validator,
                ):
                    pass
            alias.unlink()
            source.unlink()
            source.symlink_to(root / "outside")
            with self.assertRaises(TeacherMediaSealError):
                with sealed_media_inputs(
                    records=rows, media_root=tmp, candidate="embeddinggemma2_740m",
                    expected_source_digest=digest, original_conversations=conversations,
                    validate_records=_fake_validator,
                ):
                    pass

    def test_text_only_reuses_materialized_strings(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = [{"text": "context"}]
            conversations, digest = _fake_validator(rows, tmp, "embeddinggemma2_740m")
            with sealed_media_inputs(
                records=rows, media_root=tmp, candidate="embeddinggemma2_740m",
                expected_source_digest=digest, original_conversations=conversations,
                validate_records=_fake_validator,
            ) as frozen:
                self.assertIs(frozen, conversations)

    def test_batch_resource_limit_is_enforced(self):
        import teacher_media_seal
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "image.png").write_bytes(b"data")
            rows = [{"image": "image.png"}]
            conversations, digest = _fake_validator(rows, tmp, "embeddinggemma2_740m")
            with mock.patch.object(teacher_media_seal, "MAX_MEDIA_BATCH_BYTES", 3):
                with self.assertRaisesRegex(TeacherMediaSealError, "batch exceeds"):
                    with sealed_media_inputs(
                        records=rows, media_root=tmp, candidate="embeddinggemma2_740m",
                        expected_source_digest=digest, original_conversations=conversations,
                        validate_records=_fake_validator,
                    ):
                        pass


@unittest.skipUnless(torch is not None, "optional CPU Torch processor integration")
class TeacherMediaSealIntegrationTests(unittest.TestCase):
    def test_processor_consumes_snapshot_even_if_source_changes(self):
        from types import SimpleNamespace
        import types
        import teacher_forward

        class FakeModel(torch.nn.Module):
            def forward(self, **_kwargs):
                values = torch.zeros(1, 2, 768)
                values[:, :, 0] = 1.0
                return SimpleNamespace(last_hidden_state=values)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "camera.png"
            source.write_bytes(b"camera-at-t0")
            records = [{"text": "camera", "image": "camera.png"}]
            _, expected = teacher_forward.validate_records(
                records, root, "embeddinggemma2_740m")
            observed = []

            class FakeProcessor:
                def apply_chat_template(self, conversations, **_kwargs):
                    path = Path(conversations[0][0]["content"][1]["url"])
                    observed.append(path)
                    assert path != source
                    assert path.read_bytes() == b"camera-at-t0"
                    source.write_bytes(b"changed-while-processing")
                    assert path.read_bytes() == b"camera-at-t0"
                    return {"input_ids": torch.tensor([[4, 5]]),
                            "attention_mask": torch.tensor([[1, 1]])}

            modules = types.ModuleType("transformers")
            modules.AutoProcessor = SimpleNamespace(
                from_pretrained=lambda *a, **kw: FakeProcessor())
            modules.AutoModel = SimpleNamespace(
                from_pretrained=lambda *a, **kw: FakeModel())
            modules.AutoModelForSeq2SeqLM = object()
            modules.AutoTokenizer = object()
            with (mock.patch.dict(sys.modules, {"transformers": modules}),
                  mock.patch.object(teacher_forward, "verify_snapshot",
                                    return_value={"revision": "a" * 40,
                                                  "inventory_sha256": "b" * 64})):
                report = teacher_forward.run_forward(
                    candidate="embeddinggemma2_740m", snapshot=root,
                    media_root=root, records=records, revision="a" * 40,
                    expected_inventory_sha256="b" * 64,
                    operator_accepted_terms=True, device="cpu")
            self.assertEqual(report["ordered_source_manifest_sha256"], expected)
            self.assertEqual(report["owner_model_forward_hook_calls"], 1)
            self.assertFalse(report["production_activation_allowed"])
            self.assertEqual(len(observed), 1)
            self.assertFalse(observed[0].exists())


if __name__ == "__main__":
    unittest.main()
