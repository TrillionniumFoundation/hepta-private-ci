from dataclasses import replace
import hashlib
import pathlib
import sys
import unittest

import torch
from torch import nn

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from feature_bundle import FeatureBundleError, FeatureBundleV1, FeatureIdentityV1
from native_latent import CellRequest, LightCellHead, SharedStemServer, StemContractError


def identity():
    return FeatureIdentityV1("a" * 64, "b" * 40, "c" * 64, generation=7)


def pooled(values=None, **changes):
    values = torch.arange(16, dtype=torch.float32).reshape(2, 8) / 16 if values is None else values
    args = {"global_features": values, "identity": identity(),
            "source_record_digests": tuple(hashlib.sha256(str(i).encode()).hexdigest()
                                            for i in range(values.shape[0])),
            "missing_mask": torch.tensor([[False, True, True, True, True]] * values.shape[0])}
    args.update(changes)
    return FeatureBundleV1.from_tensors(**args)


class FeatureBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_sources_and_readers_cannot_mutate_the_snapshot(self):
        source = torch.arange(16, dtype=torch.float32).reshape(2, 8)
        expected = source.clone()
        bundle = pooled(source)
        receipt = bundle.bundle_digest
        source.zero_()
        bundle.read_global().fill_(100)
        bundle.snapshot()["missing_mask"].fill_(True)
        manifest = bundle.manifest()
        manifest["identity"]["scope_id"] = "another-scope"
        self.assertTrue(torch.equal(bundle.read_global(), expected))
        self.assertEqual(bundle.bundle_digest, receipt)
        self.assertEqual(bundle.identity.scope_id, "research-local")
        bundle.verify_integrity()

    def test_real_tokens_preserve_row_masks_regions_and_times(self):
        tokens = torch.randn(2, 3, 8)
        valid = torch.tensor([[True, True, False], [True, True, True]])
        modalities = torch.tensor([[1, 3, -1], [0, 2, 2]])
        missing = torch.tensor([[True, False, True, False, True],
                                [False, True, False, True, True]])
        regions = torch.zeros(2, 3, 4)
        region_valid = torch.tensor([[True, True, False], [False, False, False]])
        regions[0, 0] = torch.tensor([0.0, 0.1, 0.4, 0.6])
        regions[0, 1] = torch.tensor([0.2, 0.2, 0.8, 0.9])
        times = torch.zeros(2, 3, 2)
        time_valid = torch.tensor([[False, True, False], [False, True, True]])
        times[0, 1] = torch.tensor([1.0, 1.1])
        times[1, 1:] = torch.tensor([[2.0, 3.0], [3.0, 4.0]])
        bundle = pooled(token_features=tokens, token_valid=valid,
                        modality_ids=modalities, missing_mask=missing,
                        region_boxes=regions, region_valid=region_valid,
                        time_spans=times, time_valid=time_valid)
        snapshot = bundle.snapshot()
        self.assertTrue(torch.equal(snapshot["modality_ids"], modalities))
        self.assertTrue(torch.equal(snapshot["region_boxes"], regions))
        self.assertTrue(torch.equal(snapshot["time_spans"], times))
        times.zero_()
        tokens.zero_()
        self.assertGreater(float(bundle.read_tokens().abs().sum()), 0)
        self.assertEqual(float(bundle.snapshot()["time_spans"][1, 2, 1]), 4.0)

    def test_pooled_features_do_not_invent_spatial_or_temporal_tokens(self):
        bundle = pooled()
        self.assertIsNone(bundle.read_tokens())
        self.assertNotIn("region_boxes", bundle.manifest()["views"])
        with self.assertRaisesRegex(FeatureBundleError, "pooled-only"):
            pooled(region_boxes=torch.zeros(2, 1, 4))

    def test_cache_identity_distinguishes_effective_requests_and_outputs(self):
        baseline = pooled()
        other_values = pooled(torch.ones(2, 8))
        self.assertEqual(baseline.cache_key, other_values.cache_key)
        self.assertNotEqual(baseline.bundle_digest, other_values.bundle_digest)
        for change in ({"preprocess_sha256": "d" * 64}, {"scope_id": "other"},
                       {"generation": 8}, {"revocation_epoch": 1}, {"purpose": "indexing"}):
            selected = replace(identity(), **change)
            self.assertNotEqual(pooled(identity=selected).cache_key, baseline.cache_key)
            with self.assertRaises(FeatureBundleError):
                baseline.require_identity(selected)
        reversed_rows = pooled(source_record_digests=tuple(reversed(baseline.source_record_digests)))
        self.assertNotEqual(reversed_rows.cache_key, baseline.cache_key)

    def test_nonfinite_trainable_and_unbounded_tensors_are_rejected(self):
        invalid = [torch.ones(2, 8, requires_grad=True),
                   torch.full((2, 8), float("nan")),
                   torch.ones(513, 8), torch.ones(2, 8, dtype=torch.float16)]
        for value in invalid:
            with self.subTest(shape=tuple(value.shape)), self.assertRaises(FeatureBundleError):
                pooled(value)
        with self.assertRaisesRegex(FeatureBundleError, "budget"):
            pooled(token_features=torch.ones(2, 512, 4096),
                   token_valid=torch.ones(2, 512, dtype=torch.bool),
                   modality_ids=torch.zeros(2, 512, dtype=torch.int64))
        with self.assertRaisesRegex(FeatureBundleError, "source digest"):
            pooled(source_record_digests=("a" * 64,))

    def test_missing_modalities_and_invalid_regions_fail_before_readout(self):
        args = {"token_features": torch.ones(2, 2, 8),
                "token_valid": torch.ones(2, 2, dtype=torch.bool),
                "modality_ids": torch.ones(2, 2, dtype=torch.int64)}
        with self.assertRaisesRegex(FeatureBundleError, "missing modality"):
            pooled(**args)
        args["missing_mask"] = torch.tensor([[True, False, True, True, True]] * 2)
        args["region_boxes"] = torch.tensor([[[0.7, 0.0, 0.2, 1.0]] * 2] * 2)
        args["region_valid"] = torch.ones(2, 2, dtype=torch.bool)
        with self.assertRaisesRegex(FeatureBundleError, "regions"):
            pooled(**args)

    def test_bfloat16_bytes_and_explicit_q24_rounding(self):
        bf16 = pooled(torch.ones(2, 8, dtype=torch.bfloat16))
        self.assertEqual(bf16.read_global().dtype, torch.bfloat16)
        q = float(1 << 24)
        values = torch.tensor([[0.5 / q, 1.5 / q, -0.5 / q, -1.5 / q]])
        converted = pooled(values).q24_global()
        self.assertEqual(converted["feature_vector_q24"], [0, 2, 0, -2])
        self.assertEqual(converted["source_record_digest"], pooled(values).source_record_digests[0])
        with self.assertRaisesRegex(FeatureBundleError, "bounds"):
            pooled(torch.full((1, 8), 8.1)).q24_global()

    def test_precomputed_bundle_fans_out_without_reexecuting_encoder(self):
        class RefuseEncoder(nn.Module):
            def forward(self, _values):
                raise AssertionError("the real backend already encoded this bundle")
        server = SharedStemServer(RefuseEncoder(), generation=7, width=8, encoder_sha256="a" * 64)
        heads = [LightCellHead(8) for _ in range(3)]
        requests = [CellRequest(f"cell.{i}", 7, head, torch.zeros(2, 8), "d" * 64)
                    for i, head in enumerate(heads)]
        bundle = pooled()
        output = server.evaluate_bundle(bundle, requests, expected_identity=identity())
        self.assertEqual(len(output["cell_results"]), 3)
        self.assertEqual(server.owner_forward_calls, 0)
        self.assertEqual(output["feature_bundle_sha256"], bundle.bundle_digest)
        self.assertEqual(output["copy_accounting"]["head_input_scratch_bytes"],
                         3 * (2 * 8 * 4 + 2 * 8 * 4))
        with self.assertRaises(FeatureBundleError):
            server.evaluate_bundle(bundle, requests,
                                   expected_identity=replace(identity(), scope_id="other"))

    def test_hostile_first_head_does_not_change_later_cell_or_source(self):
        server = SharedStemServer(nn.Identity(), generation=7, width=8, encoder_sha256="a" * 64)
        first, second = LightCellHead(8), LightCellHead(8)
        state = torch.zeros(2, 8)
        slots = torch.ones(2, 3, 8)
        baseline = second(slots.mean(dim=1), state)["task_logits"].detach()
        def rewrite_inputs(_module, args):
            args[0].zero_()
            args[1].fill_(12)
        handle = first.register_forward_pre_hook(rewrite_inputs)
        try:
            output = server.evaluate(slots, [CellRequest("cell.first", 7, first, state, "d" * 64),
                                             CellRequest("cell.second", 7, second, state, "d" * 64)])
        finally:
            handle.remove()
        self.assertTrue(torch.equal(output["cell_results"][1]["advisory"]["task_logits"], baseline))
        self.assertTrue(torch.equal(slots, torch.ones_like(slots)))
        self.assertTrue(torch.equal(state, torch.zeros_like(state)))
        self.assertEqual(server.owner_forward_calls, 1)

    def test_post_forward_hook_cannot_smuggle_nonfinite_output(self):
        server = SharedStemServer(nn.Identity(), generation=7, width=8, encoder_sha256="a" * 64)
        head = LightCellHead(8)
        def poison_output(_module, _args, output):
            output["task_logits"].fill_(float("nan"))
        handle = head.register_forward_hook(poison_output)
        try:
            with self.assertRaisesRegex(StemContractError, "module hooks"):
                server.evaluate(torch.ones(1, 2, 8),
                                [CellRequest("cell", 7, head, torch.zeros(1, 8), "d" * 64)])
        finally:
            handle.remove()

    def test_bundle_row_count_times_fanout_is_bounded_before_head_execution(self):
        server = SharedStemServer(nn.Identity(), generation=7, width=8, encoder_sha256="a" * 64)
        head = LightCellHead(8, task_count=256, action_count=256)
        requests = [CellRequest(f"cell.{i}", 7, head, torch.zeros(64, 8), "d" * 64)
                    for i in range(65)]
        bundle = pooled(torch.ones(64, 8))
        with self.assertRaisesRegex(StemContractError, "combined Cell"):
            server.evaluate_bundle(bundle, requests, expected_identity=identity())
        self.assertEqual(server.owner_forward_calls, 0)


if __name__ == "__main__":
    unittest.main()
