"""Local PNG execution parity on handmade arrays; no dataset or speed claim."""

import base64
import io
import itertools
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from control import Controller
from model import JointModel
from independent.accounting import BudgetExceeded, WorkLedger
from independent.evaluation import _outputs, measure
from independent.inference import FrozenGenerator
from independent.output_codec import (CODEBOOK, ROWWISE, prepare_codec,
                                      preparation_work, request_work)


class FixedDraws:
    def __init__(self, values):
        self.values, self.calls = np.asarray(values), 0

    def random(self, shape):
        if shape != self.values.shape:
            raise AssertionError("sampling shape/order changed")
        self.calls += 1
        return self.values.copy()


class OutputCodecTests(unittest.TestCase):
    def setUp(self):
        self.model = JointModel(202, 12, 192, hidden=4, seed=471)
        self.gen = FrozenGenerator(self.model, prepare_low=False)

    def prepare(self, generator=None, ledger=None):
        ledger = WorkLedger("codec-prepare") if ledger is None else ledger
        return prepare_codec(self.gen if generator is None else generator, CODEBOOK, ledger), ledger

    def test_default_is_unprepared_and_unknown_profiles_reject(self):
        ledger = WorkLedger("default")
        with patch.object(JointModel, "decode_images", side_effect=AssertionError("unused decode")):
            self.assertIsNone(prepare_codec(self.gen, ROWWISE, ledger))
            for profile in (None, True, "global-cache"):
                with self.subTest(profile=profile), self.assertRaises(ValueError):
                    prepare_codec(self.gen, profile, ledger)
        self.assertEqual(ledger.consumed_units, 0)

    def test_chunks_preserve_bytes_sizes_rng_and_actual_work_under_custom_prices(self):
        prices = {**dict(WorkLedger("prices").prices), "exp_ops": 37, "compare_ops": 3}
        prep = WorkLedger("prepare", prices=prices)
        codec, _ = self.prepare(ledger=prep)
        p = (1 + np.arange(72 * 12).reshape(72, 12) % 17).astype(float)
        p /= p.sum(axis=1, keepdims=True)
        p, q = p[:, ::-1], np.roll(p, 3, axis=1)[::-1]
        p.flags.writeable = q.flags.writeable = False
        copies, digest = (p.copy(), q.copy()), self.model.digest()
        old_rng, new_rng = np.random.default_rng(901), np.random.default_rng(901)
        old, new = WorkLedger("rowwise", prices=prices), WorkLedger("cached", prices=prices)
        for start, stop in ((0, 64), (64, 71), (71, 72)):
            reference = _outputs(self.gen, p[start:stop], q[start:stop], old, old_rng)
            with patch.object(JointModel, "decode_images", side_effect=AssertionError("request decode")), \
                 patch.object(Image.Image, "save", side_effect=AssertionError("request PNG")), \
                 patch("independent.output_codec.base64.b64encode", side_effect=AssertionError("request base64")):
                observed = _outputs(self.gen, p[start:stop], q[start:stop], new, new_rng, codec)
            self.assertEqual(observed, reference)
        self.assertEqual(new_rng.bit_generator.state, old_rng.bit_generator.state)
        np.testing.assert_array_equal(new_rng.random(9), old_rng.random(9))
        np.testing.assert_array_equal(p, copies[0]); np.testing.assert_array_equal(q, copies[1])
        self.assertEqual(self.model.digest(), digest)
        self.assertEqual(new.consumed_units, new.estimate_kernel(**request_work(72)))
        self.assertEqual(prep.consumed_units, prep.estimate_kernel(**preparation_work()))
        self.assertEqual(prep.totals["decoder_elements"], 12 * 192)
        self.assertEqual(prep.totals["decoder_calls"], 1)
        self.assertEqual(prep.totals["png_encodes"], 12)
        self.assertEqual(new.totals.get("decoder_elements", 0), 0)
        self.assertEqual(new.totals["png_codebook_lookups"], 72)
        self.assertEqual(new.totals["output_bytes"], old.totals["output_bytes"])
        self.assertEqual(new.totals["serialized_requests"], 72)
        self.assertEqual(codec.storage["entries"], 12)
        self.assertEqual(codec.storage["retained_png_bytes"], 0)
        self.assertEqual(codec.storage["retained_decoded_array_bytes"], 0)
        self.assertLessEqual(codec.storage["retained_encoded_ascii_bytes"], codec.storage["payload_bound_bytes"])

    def test_nonuniform_zero_probabilities_cdf_ties_and_final_clamp(self):
        codec, _ = self.prepare()
        p = np.zeros((4, 12))
        p[0, 1] = 1
        p[1, :3] = (0.25, 0.25, 0.5)
        p[2, -1] = np.nextafter(1.0, 0.0)
        p[3, 0] = 1
        draws = [[0., 0.], [.25, .5], [1., np.nextafter(1., 0.)], [1., .99]]
        old_rng, new_rng = FixedDraws(draws), FixedDraws(draws)
        reference = _outputs(self.gen, p, p, WorkLedger("old"), old_rng)
        observed = _outputs(self.gen, p, p, WorkLedger("new"), new_rng, codec)
        self.assertEqual(observed, reference)
        self.assertEqual([row["choices"] for row in observed[0]], [
            {"text": 0, "image": 0}, {"text": 0, "image": 1},
            {"text": 11, "image": 11}, {"text": 0, "image": 0}])
        self.assertEqual((old_rng.calls, new_rng.calls), (1, 1))

    def test_one_request_preparation_has_more_declared_work_than_rowwise(self):
        codec, preparation = self.prepare()
        rowwise, cached = WorkLedger("rowwise"), WorkLedger("cached")
        p = np.eye(12)[:1]
        expected = _outputs(self.gen, p, p, rowwise, np.random.default_rng(77))
        observed = _outputs(self.gen, p, p, cached, np.random.default_rng(77), codec)
        self.assertEqual(observed, expected)
        self.assertGreater(preparation.consumed_units + cached.consumed_units, rowwise.consumed_units)

    def test_prepare_preserves_actual_decoder_clipping_rounding_and_png_pixels(self):
        pixels = np.resize(np.array([-.1, 0., .5 / 255, 1.5 / 255, 127.5 / 255, 1., 1.1]), 12 * 192).reshape(12, 192)
        def decoder(generator, ids):
            return pixels[np.asarray(ids)]
        p = np.eye(12)
        with patch.object(JointModel, "decode_images", decoder):
            codec, _ = self.prepare()
            reference = _outputs(self.gen, p, p, WorkLedger("old"), FixedDraws(np.full((12, 2), .5)))
            observed = _outputs(self.gen, p, p, WorkLedger("new"), FixedDraws(np.full((12, 2), .5)), codec)
        self.assertEqual(observed, reference)
        for index, output in enumerate(observed[0]):
            with Image.open(io.BytesIO(base64.b64decode(output["png_base64"]))) as image:
                np.testing.assert_array_equal(np.asarray(image).reshape(192),
                    np.rint(np.clip(pixels[index], 0, 1) * 255).astype(np.uint8))

    def test_insufficient_prepare_rejects_before_decode_png_or_rng_with_zero_units(self):
        required = WorkLedger("quote").estimate_kernel(**preparation_work())
        ledger = WorkLedger("short", total_cap=required - 1)
        with patch.object(JointModel, "decode_images", side_effect=AssertionError("unadmitted decode")), \
             patch.object(Image.Image, "save", side_effect=AssertionError("unadmitted PNG")), \
             patch("independent.output_codec.np.random.default_rng", side_effect=AssertionError("unused RNG")):
            with self.assertRaises(BudgetExceeded):
                self.prepare(ledger=ledger)
        self.assertEqual(ledger.consumed_units, 0)
        self.assertEqual(ledger.totals.get("decoder_elements", 0), 0)

    def test_insufficient_request_rejects_before_rng_with_zero_units(self):
        codec, _ = self.prepare()
        required = WorkLedger("quote").estimate_kernel(**request_work(7))
        ledger, rng = WorkLedger("short", total_cap=required - 1), Mock()
        rng.random.side_effect = AssertionError("unadmitted RNG")
        with self.assertRaises(BudgetExceeded):
            _outputs(self.gen, np.eye(12)[:7], np.eye(12)[:7], ledger, rng, codec)
        self.assertEqual(ledger.consumed_units, 0)
        rng.random.assert_not_called()

    def test_instance_binding_unlock_and_relocked_mutation_reject_before_sampling(self):
        for change in ("other-instance", "other-model", "unlocked", "mutated"):
            generator = FrozenGenerator(self.model, prepare_low=False)
            codec, _ = self.prepare(generator)
            if change == "other-instance":
                generator = FrozenGenerator(self.model, prepare_low=False)
            elif change == "other-model":
                generator = FrozenGenerator(JointModel(202, 12, 192, hidden=4, seed=909), prepare_low=False)
            else:
                generator.params["decoder"].flags.writeable = True
                if change == "mutated":
                    generator.params["decoder"][0, 0] += .1
                    generator.params["decoder"].flags.writeable = False
            rng, ledger = Mock(), WorkLedger("rejected")
            rng.random.side_effect = AssertionError("invalid binding sampled")
            with self.subTest(change=change), self.assertRaises(ValueError):
                _outputs(generator, np.eye(12)[:1], np.eye(12)[:1], ledger, rng, codec)
            rng.random.assert_not_called()
            self.assertEqual(ledger.consumed_units, 0)

    def test_nonfinite_decoder_preparation_bills_only_validation(self):
        self.gen.params["decoder_bias"].flags.writeable = True
        self.gen.params["decoder_bias"][0] = np.nan
        self.gen.params["decoder_bias"].flags.writeable = False
        ledger = WorkLedger("invalid")
        with patch.object(JointModel, "decode_images", side_effect=AssertionError("invalid decoder ran")):
            with self.assertRaises(ValueError):
                self.prepare(ledger=ledger)
        self.assertEqual(ledger.consumed_units, ledger.estimate_kernel(compare_ops=13 * 192))
        self.assertEqual(ledger.totals.get("decoder_elements", 0), 0)

    def test_handmade_measure_full_low_and_controller_preserve_outputs_and_reference(self):
        full = np.zeros((5, 202))
        full[:, :192] = np.linspace(0, 1, 5 * 192).reshape(5, 192)
        full[:, [192, 196, 199]] = 1
        inputs = {"full": full}  # observe=False: no labels, source fold or dataset.
        plan = {"compute_price": .02, "service_horizon": 100000,
                "runtime_backend": "python", "runtime_batch_size": 64,
                "inference_cap_full_equivalents": 2}
        critic = Controller(12, np.zeros(31), np.ones(31), np.zeros(31), 1., np.array([1., 1.]))
        digest = self.model.digest()
        for mode in ("full", "low", "continuation"):
            reports = []
            for profile in (ROWWISE, CODEBOOK):
                with patch("independent.evaluation.time.process_time_ns", side_effect=itertools.count(1000, 100).__next__), \
                     patch("independent.evaluation.time.perf_counter_ns", side_effect=itertools.count(2000, 100).__next__):
                    reports.append(measure(self.model, critic if mode == "continuation" else None,
                        mode, inputs, {**plan, "output_codec_profile": profile}, 100000, seed=11, observe=False))
            old, cached = reports
            self.assertEqual(old["sampled_output"], cached["sampled_output"])
            self.assertEqual(old["model_forwards"], cached["model_forwards"])
            self.assertEqual(old["per_row_cost"]["output_bytes"], cached["per_row_cost"]["output_bytes"])
            self.assertEqual((old["budget_violations"], cached["budget_violations"]), (0, 0))
            for field in ("reference_full_work_units", "request_cap_units"):
                self.assertEqual(old["cost"][field], cached["cost"][field])
            self.assertEqual(cached["cost"]["output_codec_profile"], CODEBOOK)
            self.assertEqual(cached["cost"]["prepare"]["totals"]["decoder_elements"], 12 * 192)
            self.assertEqual(cached["cost"]["operator_totals"].get("decoder_elements", 0), 0)
        self.assertEqual(self.model.digest(), digest)

    def test_opted_in_native_export_rejects_before_artifacts_copy_or_output_directory(self):
        from independent import serve
        from multimodal_contract import UnsupportedCapability
        selection = {"schema": "hepta.joint-generation.efficient-selection.v2",
                     "selected": [{"system": "ndu", "seed": 11}],
                     "plan": {"runtime_backend": "native", "output_codec_profile": CODEBOOK}}
        with patch.object(serve, "_artifact", return_value=Path("/manual/selection.json")), \
             patch.object(serve, "_json", return_value=selection), \
             patch.object(serve, "_file", side_effect=AssertionError("artifact access")) as artifact, \
             patch.object(serve.shutil, "copyfile", side_effect=AssertionError("copy")) as copy, \
             patch.object(Path, "mkdir", side_effect=AssertionError("output directory")) as mkdir:
            with self.assertRaises(UnsupportedCapability):
                serve.export_bundle("/manual/run", "ndu", 11, "/manual/out")
            artifact.assert_not_called(); copy.assert_not_called(); mkdir.assert_not_called()

    def test_native_batches_64_plus_1_conserve_cached_output_quote_and_actual_work(self):
        from independent.native import NativeGenerator, compile_native
        full = np.zeros((65, 202))
        full[:, :192] = np.linspace(0, 1, 65 * 192).reshape(65, 192)
        full[:, [192, 196, 199]] = 1
        critic = Controller(12, np.zeros(31), np.ones(31), np.zeros(31), 1., np.array([1., 1.]))
        quote = WorkLedger("quote")
        output_units = quote.estimate_kernel(**request_work())
        digest, original_batch = self.model.digest(), NativeGenerator.batch
        with tempfile.TemporaryDirectory() as directory:
            library = Path(directory) / "manual-codec.so"
            self.assertEqual(compile_native(library)["exit_code"], 0)
            plan = {"compute_price": .02, "service_horizon": 100000, "runtime_backend": "native",
                    "native_library": str(library), "runtime_batch_size": 64,
                    "inference_cap_full_equivalents": 2}
            for mode in ("full", "low", "continuation"):
                reports = []
                for profile in (ROWWISE, CODEBOOK):
                    calls = []
                    def record_batch(generator, *args, **kwargs):
                        result = original_batch(generator, *args, **kwargs)
                        calls.append((len(args[0]), kwargs["per_request_cap"], result[2]))
                        return result
                    with patch.object(NativeGenerator, "batch", record_batch), \
                         patch("independent.evaluation.time.process_time_ns", side_effect=itertools.count(1000, 100).__next__), \
                         patch("independent.evaluation.time.perf_counter_ns", side_effect=itertools.count(2000, 100).__next__):
                        report = measure(self.model, critic if mode == "continuation" else None,
                            mode, {"full": full}, {**plan, "output_codec_profile": profile},
                            100000, seed=11, observe=False)
                    reports.append((report, calls))
                (old, _), (cached, calls) = reports
                self.assertEqual(old["sampled_output"], cached["sampled_output"])
                self.assertEqual(old["per_row_cost"]["output_bytes"], cached["per_row_cost"]["output_bytes"])
                self.assertEqual((old["model_forwards"], cached["model_forwards"]), (130, 130) if mode == "continuation" else (65, 65))
                self.assertEqual([batch["rows"] for batch in cached["cost"]["batches"]], [64, 1])
                self.assertEqual([n for n, _, _ in calls], [64, 1])
                self.assertTrue(all(batch["native_batch"] for batch in cached["cost"]["batches"]))
                for field in ("reference_full_work_units", "request_cap_units"):
                    self.assertEqual(old["cost"][field], cached["cost"][field])
                forward = self.gen.full_work(1) if mode == "full" else self.gen.low_work(1)
                expected = quote.estimate_kernel(**forward) + output_units
                if mode == "continuation":
                    expected += quote.estimate_kernel(**self.gen.full_work(1)) + quote.estimate_kernel(**self.gen.critic_work(1, critic))
                self.assertEqual(cached["per_row_cost"]["work_units"], [expected] * 65)
                self.assertEqual(cached["cost"]["operator_totals"]["consumed_units"], expected * 65)
                prepare_units = quote.estimate_kernel(**preparation_work())
                if mode != "full": prepare_units += quote.estimate_kernel(**self.gen.prepare_work())
                self.assertEqual(cached["cost"]["prepare"]["consumed_units"], prepare_units)
                self.assertEqual(cached["cost"]["prepare"]["totals"]["decoder_elements"], 12 * 192)
                self.assertEqual(cached["cost"]["operator_totals"].get("decoder_elements", 0), 0)
                self.assertEqual(cached["budget_violations"], 0)
                for (n, cap, receipt), batch in zip(calls, cached["cost"]["batches"]):
                    self.assertEqual(cap, cached["cost"]["request_cap_units"] - output_units)
                    self.assertEqual(receipt["charged_units"], receipt["actual_units"])
                    self.assertEqual(sum(receipt["per_row_work_units"]) + n * output_units, batch["work_units"])
                    self.assertTrue(all(work <= cap for work in receipt["per_row_work_units"]))
        self.assertEqual(self.model.digest(), digest)


if __name__ == "__main__":
    unittest.main()
