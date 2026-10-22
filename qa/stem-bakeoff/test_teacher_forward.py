import io
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

try:
    import torch
except ImportError:
    torch = None

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from teacher_forward import TeacherForwardError, validate_records

if torch is not None:
    from teacher_forward import mean_pool


class TeacherForwardPreflightTests(unittest.TestCase):
    def test_text_and_local_multimodal_input_is_bounded_and_digest_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            (base / "cat.png").write_bytes(b"fake image bytes; no decoder executes")
            rows = [{"text": "cat", "image": "cat.png"},
                    {"text": "dog"}]
            conversations, digest = validate_records(rows, base, "embeddinggemma2_740m")
            self.assertEqual(len(conversations), 2)
            self.assertEqual([row["type"] for row in conversations[0][0]["content"]],
                             ["text", "image"])
            self.assertEqual(len(digest), 64)
            (base / "cat.png").write_bytes(b"changed fake image bytes")
            self.assertNotEqual(validate_records(rows, base, "embeddinggemma2_740m")[1],
                                digest)

    def test_batch_media_bytes_rejected_at_preflight(self):
        import teacher_forward
        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / "clip.wav").write_bytes(b"four")
            # Two references are two processor inputs even if paths coincide.
            with mock.patch.object(teacher_forward, "MAX_MEDIA_BATCH_BYTES", 7):
                with self.assertRaisesRegex(TeacherForwardError, "batch exceeds"):
                    validate_records([{"audio": "clip.wav"}, {"audio": "clip.wav"}],
                                     tmp, "embeddinggemma2_740m")

    def test_media_growth_between_size_check_and_hash_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "frame.png"
            path.write_bytes(b"abcd")
            real_open = pathlib.Path.open

            def swapped_open(self, *args, **kwargs):
                if self == path and args and args[0] == "rb":
                    return io.BytesIO(b"abcdef")
                return real_open(self, *args, **kwargs)

            with mock.patch.object(pathlib.Path, "open", swapped_open):
                with self.assertRaisesRegex(TeacherForwardError, "changed size"):
                    validate_records([{"image": "frame.png"}],
                                     tmp, "embeddinggemma2_740m")

    def test_media_urls_absolute_and_traversal_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            (base / "valid.png").write_bytes(b"raw")
            for forbidden in ("https://example.org/image.png", "../valid.png",
                              "/etc/passwd", "file:///etc/passwd", ""):
                with self.subTest(forbidden=forbidden):
                    with self.assertRaises(TeacherForwardError):
                        validate_records([{"image": forbidden}], base,
                                         "embeddinggemma2_740m")
            (base / "alias.png").symlink_to(base / "valid.png")
            with self.assertRaises(TeacherForwardError):
                validate_records([{"image": "alias.png"}], base,
                                 "embeddinggemma2_740m")

    def test_reject_empty_unknown_modality_and_unsafe_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            for records in (
                [],
                [{}],
                [{"unknown": "x"}],
                [{"text": ""}],
                [{"text": "x" * 20000}],
                [{"text": 42}],
                [{"text": "hi"}] * 9,
            ):
                with self.subTest(records=repr(records)[:70]):
                    with self.assertRaises(TeacherForwardError):
                        validate_records(records, base, "embeddinggemma2_740m")

    def test_t5_text_and_single_image_contract_is_strictly_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            (base / "photo.png").write_bytes(b"fixture bytes; decoder not executed")
            allowed = [{"text": "<start_of_image> describe this",
                        "image": "photo.png"}]
            conversations, digest = validate_records(
                allowed, base, "t5gemma2_encoder_270m")
            self.assertEqual([part["type"] for part in conversations[0][0]["content"]],
                             ["text", "image"])
            self.assertEqual(len(digest), 64)
            self.assertEqual(len(validate_records([{"text": "hi"}], base,
                                                   "t5gemma2_encoder_270m")[0]), 1)
            for disallowed in (
                [{"text": "hi", "image": "photo.png"}],
                [{"text": "<start_of_image><start_of_image>", "image": "photo.png"}],
                [{"text": "<start_of_image> no image"}],
                [{"text": "hi", "audio": "clip.wav"}],
                [{"image": "photo.png"}],
                [{"text": "hi", "video": "clip.mp4"}],
                allowed + [{"text": "hi"}],
            ):
                with self.subTest(records=disallowed):
                    with self.assertRaises(TeacherForwardError):
                        validate_records(disallowed, base, "t5gemma2_encoder_270m")


@unittest.skipUnless(torch is not None, "optional PyTorch local feature tests")
class TeacherPoolingTests(unittest.TestCase):
    def test_mask_aware_pooling_and_matryoshka_renormalize(self):
        t = torch.zeros(2, 3, 768)
        t[0, 0, 0] = 3.0
        t[0, 0, 1] = 4.0
        t[0, 1, :] = 999.0  # padded token must have zero influence
        t[1, 0, 2] = 1.0
        t[1, 1, 2] = 1.0
        mask = torch.tensor([[1, 0, 0], [1, 1, 0]])
        pooled = mean_pool(t, mask, truncate_dim=256)
        self.assertEqual(pooled.shape, (2, 256))
        self.assertTrue(torch.allclose(pooled.norm(dim=1), torch.ones(2)))
        self.assertAlmostEqual(float(pooled[0, 0]), 0.6, places=5)
        self.assertAlmostEqual(float(pooled[0, 1]), 0.8, places=5)

    def test_invalid_mask_nonfinite_and_bad_dimension_refused(self):
        tokens = torch.randn(2, 3, 768)
        for mask in (torch.tensor([[1, 0, 0], [0, 0, 0]]),
                     torch.tensor([[1, 0, 2], [1, 0, 0]])):
            with self.assertRaises(TeacherForwardError):
                mean_pool(tokens, mask)
        tokens[0, 0, 0] = float("nan")
        with self.assertRaises(TeacherForwardError):
            mean_pool(tokens, torch.ones(2, 3))
        with self.assertRaises(TeacherForwardError):
            mean_pool(torch.zeros(2, 2, 32), torch.ones(2, 2), truncate_dim=256)



    def test_t5_processor_rejects_extra_fields_and_misaligned_rows(self):
        from teacher_forward import _validate_t5_encoder_inputs
        good = {
            "input_ids": torch.tensor([[1, 2], [3, 4]], dtype=torch.int64),
            "attention_mask": torch.tensor([[1, 1], [1, 0]], dtype=torch.int64),
            "pixel_values": torch.ones(2, 3, 2, 2),
        }
        bounded = _validate_t5_encoder_inputs(good, batch_size=2, with_image=True)
        self.assertEqual(set(bounded), set(good))
        # The original path moved every returned tensor to CUDA even if the
        # Encoder never consumed it.
        unexpected = dict(good, unused_tensor=torch.ones(1))
        wrong_batch = dict(good, input_ids=torch.tensor([[1, 2]]))
        wrong_mask = dict(good, attention_mask=torch.ones(2, 3, dtype=torch.long))
        bad_channels = dict(good, pixel_values=torch.ones(2, 1, 2, 2))
        bad_pixel_batch = dict(good, pixel_values=torch.ones(1, 3, 2, 2))
        too_large = dict(good, pixel_values=torch.empty(1, 3, 1, 1)
                         .expand(2, 3, 4096, 4096))
        for rejected in (unexpected, wrong_batch, wrong_mask, bad_channels,
                         bad_pixel_batch, too_large):
            with self.subTest(fields=list(rejected)):
                with self.assertRaises(TeacherForwardError):
                    _validate_t5_encoder_inputs(rejected, batch_size=2,
                                                with_image=True)

    def test_t5_processor_rejects_empty_nonbinary_and_noninteger_tokens(self):
        from teacher_forward import _validate_t5_encoder_inputs
        ids = torch.tensor([[1, 2], [3, 4]])
        mask = torch.tensor([[1, 1], [1, 0]])
        good = {"input_ids": ids, "attention_mask": mask}
        self.assertEqual(set(_validate_t5_encoder_inputs(
            good, batch_size=2, with_image=False)), set(good))
        for rejected in (
            dict(good, attention_mask=torch.tensor([[1, 1], [0, 0]])),
            dict(good, attention_mask=torch.tensor([[1, 2], [1, 0]])),
            dict(good, input_ids=ids.float()),
            dict(good, input_ids=ids - 8),
            dict(good, input_ids=torch.empty(2, 0, dtype=torch.long)),
            dict(good, pixel_values=torch.ones(2, 3, 2, 2)),
        ):
            with self.assertRaises(TeacherForwardError):
                _validate_t5_encoder_inputs(rejected, batch_size=2,
                                            with_image=False)

    def test_t5_processor_rejects_nonfinite_and_wrong_dtype_pixels(self):
        from teacher_forward import _validate_t5_encoder_inputs
        good = {
            "input_ids": torch.tensor([[1, 2]]),
            "attention_mask": torch.tensor([[1, 1]]),
            "pixel_values": torch.ones(1, 3, 2, 2),
        }
        for pixels in (
            torch.full((1, 3, 2, 2), float("nan")),
            torch.full((1, 3, 2, 2), float("inf")),
            torch.ones(1, 3, 2, 2, dtype=torch.int64),
        ):
            with self.assertRaises(TeacherForwardError):
                _validate_t5_encoder_inputs(
                    dict(good, pixel_values=pixels), batch_size=1,
                    with_image=True)

if __name__ == "__main__":
    unittest.main()
