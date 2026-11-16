"""Adversarial checks for the independent evidence reader, without a model."""

import copy
import hashlib
import json
from pathlib import Path
import random
import struct
import tempfile
import unittest

from population_audit import _exact, _gates
from population_audit_core import (
    _bytes,
    _checkpoint,
    _digest,
    _hash,
    _route,
    _router,
    _write_receipt,
)
from population_audit_reads import (
    _assessment,
    _capability,
    _metrics,
    _quantized_payload,
)
from population_fixtures import dataset


class IndependentAuditTests(unittest.TestCase):
    def test_checkpoint_hash_covers_actual_tensor_bytes_and_state(self):
        name, shape, payload = (
            "layer.lora_A.weight",
            [4, 2],
            struct.pack("<8f", *range(8)),
        )
        header = _bytes(
            {name: {"dtype": "F32", "shape": shape, "data_offsets": [0, len(payload)]}}
        )
        safetensor = struct.pack("<Q", len(header)) + header + payload
        state = hashlib.sha256(
            _digest([name, shape, "torch.float32"]).encode() + payload
        ).hexdigest()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            config = _bytes({"r": 4, "lora_alpha": 8})
            manifest = {
                "adapter_sha256": _hash(safetensor),
                "config_sha256": _hash(config),
                "roots": ["source"],
                "training": {"adapter_state_sha256": state},
                "production_accepted": False,
                "model_install_authority": False,
            }
            (path / "adapter_model.safetensors").write_bytes(safetensor)
            (path / "adapter_config.json").write_bytes(config)
            (path / "lineage.json").write_bytes(_bytes(manifest))
            version = {
                "directory": temp,
                "manifest_sha256": _hash(_bytes(manifest)),
                "rank": 4,
                "roots": ["source"],
            }
            self.assertEqual(_checkpoint(version)["private_bytes"], 32)
            (path / "adapter_model.safetensors").write_bytes(
                safetensor[:-1] + bytes([safetensor[-1] ^ 1])
            )
            with self.assertRaisesRegex(ValueError, "payload pins"):
                _checkpoint(version)

    def test_writer_schedule_and_actual_token_totals_are_independent(self):
        facts = dataset(1907)["parent_facts"][:1]
        templates = dataset(1907)["train_templates"]
        schedule = list(range(4))
        random.Random(11907).shuffle(schedule)
        root = facts[0]["source_digest"]
        receipt = {
            "steps": 4,
            "objective": "completion_ce",
            "writer_seed": 11907,
            "schedule": "seeded_epoch_permutation_v1",
            "schedule_indices": schedule,
            "schedule_sha256": _digest(schedule),
            "example_visits": [1] * 4,
            "fact_visits": [4],
            "source_facts_sha256": _digest(facts),
            "templates_sha256": _digest(templates),
            "source_digests": [root],
            "inherited_roots": [],
            "accessed_roots": [root],
            "roots": [root],
            "actual_model_forwards": 4,
            "learning_rate": 0.001,
            "parameter_bytes": 32,
            "trainable_parameters": 8,
            "gradient_bytes": 32,
            "base_unchanged": True,
            "evaluation_targets_used": False,
            "production_accepted": False,
            "learned_parent_manifest_sha256": None,
            "negative_fact_visits": [0],
            "negative_fact_indices": [],
            "losses": [1.0] * 4,
            "adapter_delta_squared_norm": 0.2,
            "input_tokens": 46,
            "supervised_tokens": 8,
        }
        point = {"private_bytes": 32, "manifest": {"training": receipt}}
        tokens = [{"input_tokens": n, "supervised_tokens": 2} for n in (10, 11, 12, 13)]
        _write_receipt(receipt, facts, templates, 4, 1907, point, [], None, tokens)
        swapped = copy.deepcopy(receipt)
        swapped["schedule_indices"][0], swapped["schedule_indices"][1] = (
            swapped["schedule_indices"][1],
            swapped["schedule_indices"][0],
        )
        swapped["schedule_sha256"] = _digest(swapped["schedule_indices"])
        with self.assertRaisesRegex(ValueError, "schedule_indices"):
            _write_receipt(
                swapped,
                facts,
                templates,
                4,
                1907,
                {"private_bytes": 32, "manifest": {"training": swapped}},
                [],
                None,
                tokens,
            )
        receipt["input_tokens"] -= 1
        with self.assertRaisesRegex(ValueError, "token accounting"):
            _write_receipt(receipt, facts, templates, 4, 1907, point, [], None, tokens)

    def test_temporal_dependencies_and_unsupported_answers_cannot_inflate_score(self):
        data = dataset(1907)
        probe = data["transfer_final"][0]
        version = {"roots": probe["source_roots"], "manifest_sha256": "version"}
        self.assertTrue(
            _capability(probe, version, data["sources"])["capability_allowed"]
        )
        partial = {**version, "roots": version["roots"][:1]}
        scored = _assessment(probe, {"text": probe["value"]}, partial, data["sources"])
        self.assertTrue(scored["raw_correct"])
        self.assertFalse(scored["supported_correct"])
        before = data["ood_final"][-1]
        self.assertFalse(
            _capability(before, {"roots": before["source_roots"]}, data["sources"])[
                "capability_allowed"
            ]
        )

    def test_raw_rejection_and_decoder_unknown_remain_distinct(self):
        data = dataset(1907)
        probe = data["ood_final"][0]
        version = {
            "roots": [r["source_digest"] for r in data["sources"]],
            "manifest_sha256": "version",
        }
        action = _assessment(probe, None, None, data["sources"])
        decoder = _assessment(probe, {"text": "unknown"}, version, data["sources"])
        self.assertTrue(action["correct"] and decoder["correct"])
        summary = _metrics([action, decoder])["unknown"]
        self.assertEqual(
            (
                summary["correct"],
                summary["raw_correct"],
                summary["action_abstentions"],
                summary["decoder_unknown"],
            ),
            (2, 1, 1, 1),
        )

    def test_router_replay_handles_positive_expert_ties_without_fake_rejection(self):
        config = {
            "dimension": 64,
            "seed": 2718,
            "min_confidence": 0.55,
            "min_margin": 0.05,
        }
        weights = [0.0] * (65 * 3)
        weights[-1] = -2.0
        slot, probabilities = _route(
            "What is the color for person N00?", ({"config": config}, weights)
        )
        self.assertEqual(slot, 0)
        self.assertLess(probabilities[0], 0.55)
        self.assertGreater(sum(probabilities[:2]), 0.55)
        weights[-1] = 2.0
        self.assertIsNone(
            _route("What is the color for person N00?", ({"config": config}, weights))[
                0
            ]
        )

    def test_router_serialized_weights_are_hash_bound(self):
        weights = struct.pack("<195f", *([0.0] * 195))
        header = _bytes(
            {
                "weight_sha256": _hash(weights),
                "weight_shape": [65, 3],
                "config": {"dimension": 64},
            }
        )
        payload = (
            b"HEPTA_ROUTER_V2\n" + struct.pack("<I", len(header)) + header + weights
        )
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "router.bin"
            path.write_bytes(payload)
            self.assertEqual(len(_router(path, _hash(payload))[1]), 195)
            path.write_bytes(payload[:-1] + b"\x01")
            with self.assertRaisesRegex(ValueError, "pinned learned router"):
                _router(path, _hash(payload))

    def test_packed_values_must_derive_from_source_and_materialize_exactly(self):
        name, shape = "layer.lora_A.weight", [1, 3]
        for bits in (4, 8):
            bound = (1 << (bits - 1)) - 1
            source = struct.pack("<3f", -1.0, 0.0, 1.0)
            scale = 1.0 / bound
            chunk = bytes([0, bound, 2 * bound, 0])
            chunk = (
                bytes([chunk[0] | (chunk[1] << 4), chunk[2]])
                if bits == 4
                else struct.pack("<3b", -bound, 0, bound)
            )
            header = _bytes(
                {
                    "bits": bits,
                    "decoded_dtype": "torch.float32",
                    "tensors": [
                        {
                            "name": name,
                            "shape": shape,
                            "scale": scale,
                            "offset": 0,
                            "bytes": len(chunk),
                        }
                    ],
                }
            )
            payload = b"HEPTAQ01" + struct.pack("<Q", len(header)) + header + chunk
            checkpoint = {"tensors": {name: (shape, source)}}
            _quantized_payload(payload, bits, checkpoint, checkpoint)
            wrong = {"tensors": {name: (shape, struct.pack("<3f", -1.0, 0.1, 1.0))}}
            with self.assertRaises(ValueError):
                _quantized_payload(payload, bits, wrong, checkpoint)

    def test_exact_program_and_temporal_baseline_does_not_use_probe_gold(self):
        data = dataset(2719)
        for probe in data["transfer_final"] + data["ood_final"]:
            expected = probe["value"], probe["source_roots"]
            probe["value"] = "tampered gold"
            self.assertEqual(_exact(data["sources"], probe["operation"]), expected)

    def test_failed_research_gate_cannot_be_promoted_to_pass(self):
        families = (
            "semantic",
            "episode",
            "procedure",
            "event_interpolation",
            "procedure_extrapolation",
        )
        policies = (
            "split_learned_guarded",
            "single",
            "oracle",
            "uniform_random",
            "split_metadata_only",
            "parent",
            "selected",
        )
        metrics = {
            p: {g: {"accuracy": 0.0} for g in (*families, "retention", "known")}
            for p in policies
        }
        gates = dict.fromkeys(
            (
                "parent_source_quality",
                "split_preserves_parent_correct_semantic",
                "parent_final_quality",
                "split_preserves_parent_correct_final_semantic",
                "router_supported_coverage",
                "router_eligible_oracle_quality",
                "router_beats_expected_uniform_random",
                "router_beats_metadata_capability",
                "router_raw_ood_rejection",
                "selected_heterogeneous_retention",
                "selected_heterogeneous_transfer",
                "int8_storage_and_quality",
                "net_compression_advantage",
            ),
            False,
        )
        gates.update(
            split_retention_nonnegative=True, router_eligible_oracle_regret=True
        )
        engineering = dict.fromkeys(
            (
                "matched_adapter_budget",
                "matched_candidate_updates",
                "parent_unchanged",
                "source_groups_preserved",
                "final_owner_admission",
                "selection_unchanged",
                "selection_preceded_final_reads",
                "exact_typed_baseline",
                "both_precommitted_codecs_measured",
                "source_identity_unchanged",
                "selection_bytes_unchanged_after_codecs",
                "router_overhead_within_one_percent",
            ),
            True,
        )
        summary = dict.fromkeys(
            (
                "single_retention",
                "split_retention",
                "split_retention_gain",
                "oracle_retention",
                "oracle_representation_gain",
                "expected_uniform_random_retention",
                "metadata_retention",
                "router_regret",
                "router_gain_over_random",
                "router_gain_over_metadata",
                "supported_retention_coverage",
                "raw_ood_reject_rate",
            ),
            0.0,
        )
        summary.update(
            chosen_arm="parent",
            retention_by_family=dict.fromkeys(families[:3], 0.0),
            transfer_by_family=dict.fromkeys(families[3:], 0.0),
        )
        result = {
            "final": {
                "metrics": metrics,
                "routing": {
                    "supported_retention_coverage": 0.0,
                    "raw_ood_reject_rate": 0.0,
                },
                "parent_correct_semantic_preserved": {"split": False},
            },
            "selection": {
                "choice": {
                    "parent_recall_gate": False,
                    "parent_correct_semantic_preserved": {"split": False},
                    "chosen_arm": "parent",
                    "router_within_one_percent": True,
                }
            },
            "codec": {"primary_gate_passed": False},
            "costs": {
                "retained_data_and_model_lower_bound_bytes": 1,
                "full_system_costs_and_comparable_baseline_accounted": False,
            },
            "baseline": {
                "smallest_complete_exact_representation": {"bytes": 100},
                "typed_operation_exact": 1.0,
            },
            "research_gates": gates,
            "engineering_gates": engineering,
            "summary": summary,
            "general_memory_proven": False,
            "production_accepted": False,
        }
        _gates(result)
        result["research_gates"]["int8_storage_and_quality"] = True
        with self.assertRaisesRegex(ValueError, "research gates preserved"):
            _gates(result)


if __name__ == "__main__":
    unittest.main()
