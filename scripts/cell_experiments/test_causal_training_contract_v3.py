"""Training contract tests; tiny random Qwen numerics are not model capability."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import causal_training_contract_v3 as contract
from . import chat_protocol, data, repo_execution
from .protocol_v3 import prepare_record, verify_reference
from .test_chat_protocol import ChatTokenizer
from .test_data import record
from .test_repo_execution import answer


VERSIONS = {
    name: "test-fixture"
    for name in ("torch", "transformers", "tokenizers", "safetensors")
}


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        repo_execution.load_catalog()
        row = record()
        row["task"] = {
            "input": "Test subject(state, name), which increments the named counter; cover zero and nonzero.",
            "verifier": {
                "name": "repo_patch",
                "version": "1",
                "parameters": {
                    "fixture_id": "A-counter",
                    "fixture_sha256": data.digest(repo_execution._CATALOG["A-counter"]),
                },
            },
        }
        row["final_answer"] = answer(
            '    assert subject({"calls": 0}, "calls") == {"calls": 1}\n    assert subject({"calls": 8}, "calls") == {"calls": 9}'
        )
        row["trajectory"] = []
        row.pop("verified_outcome")
        cls.row = verify_reference(prepare_record(row))
        cls.parent = {
            "schema": "test-fixture",
            "runtime": {
                "device": "cuda:0",
                "dtype": "bfloat16",
                "max_input_tokens": 2048,
            },
            "backend_versions": VERSIONS,
        }

    def readiness(self, verification=None):
        verification = verification or self.row["protocol_reference_receipt"]
        raw = self.row["final_answer"]
        result = {
            "schema": "hepta.development-readiness.v3",
            "model_digest": data.digest(self.parent),
            "fixture_actor": "scripted, never model evidence",
            "successful_tasks": 1,
            "rows": [
                {
                    key: self.row[key]
                    for key in ("record_id", "task_id", "source_id", "lineage_id")
                }
                | {
                    "steps": [
                        {
                            "output": {
                                "answer": raw,
                                "loaded_model_digest": data.digest(self.parent),
                            },
                            "verification": verification,
                        }
                    ]
                }
            ],
        }
        result["receipt_sha256"] = data.digest(result)
        return result

    def test_positive_counts_cannot_replace_bound_real_business_evidence(self):
        result = self.readiness()
        witness = contract.readiness_witness([self.row], self.parent, result)
        self.assertEqual(
            witness,
            {
                "task_id": self.row["task_id"],
                "semantic_receipt_sha256": self.row["protocol_reference_receipt"][
                    "receipt_sha256"
                ],
            },
        )
        wrong = answer("    assert subject(1, 0, 0) == 1")
        failed = self.readiness(data.verify_answer(self.row, wrong))
        failed["rows"][0]["steps"][0]["output"]["answer"] = wrong
        failed["receipt_sha256"] = data.digest(
            {k: v for k, v in failed.items() if k != "receipt_sha256"}
        )
        with self.assertRaisesRegex(ValueError, "no recorded real business success"):
            contract.readiness_witness([self.row], self.parent, failed)
        for field in ("source_id", "lineage_id"):
            transplanted = copy.deepcopy(self.row)
            transplanted[field] += "-different"
            with self.assertRaisesRegex(
                ValueError, "no recorded real business success"
            ):
                contract.readiness_witness([transplanted], self.parent, result)
        transplanted = copy.deepcopy(self.row)
        transplanted["task"]["verifier"]["parameters"]["fixture_id"] = "another"
        with self.assertRaisesRegex(ValueError, "no recorded real business success"):
            contract.readiness_witness([transplanted], self.parent, result)

    def test_A_authorization_and_student_target_masks_are_enforced(self):
        for field, value in (("split", "selection"), ("split", "confirmation")):
            changed = copy.deepcopy(self.row)
            changed[field] = value
            with self.assertRaisesRegex(ValueError, "authorized successful A"):
                contract.admit([changed], "final_answer")
        changed = copy.deepcopy(self.row)
        changed["trajectory"] = [
            {
                "index": 0,
                "actor": "student",
                "kind": "action",
                "content": "unverified",
                "executed": False,
                "trainable": True,
            }
        ]
        with self.assertRaisesRegex(ValueError, "masks student actions"):
            contract.admit([changed], "trajectory")
        changed["trajectory"][0]["trainable"] = False
        changed["trajectory"] += [
            {
                "index": 1,
                "actor": "environment",
                "kind": "observation",
                "content": "Actual test failed",
                "executed": False,
            },
            {
                "index": 2,
                "actor": "curator",
                "kind": "correction",
                "content": changed["final_answer"],
                "executed": False,
                "trainable": True,
            },
        ]
        contract.admit([changed], "trajectory")
        example = chat_protocol.native_examples([changed], "trajectory")[0]
        encoded = chat_protocol.encode_native_turns(ChatTokenizer(), example, 4096)
        self.assertEqual(len(encoded), 1)
        text = bytes(encoded[0]["input_ids"][: encoded[0]["prefix_tokens"]]).decode()
        self.assertIn("unverified", text)
        self.assertIn("Actual test failed", text)
        self.assertTrue(
            all(
                label == -100
                for label in encoded[0]["labels"][: encoded[0]["prefix_tokens"]]
            )
        )

    def test_plan_binds_data_sources_readiness_and_runtime(self):
        with (
            patch.object(contract.metadata, "version", return_value="test-peft"),
            patch.object(contract.probe, "_versions", return_value=VERSIONS),
        ):
            readiness = self.readiness()
            plan = contract.make_plan(
                [self.row],
                self.parent,
                readiness,
                mode="final_answer",
                operation_id="scripted-contract-fixture",
                steps=2,
            )
            contract.validate_plan([self.row], self.parent, readiness, plan)
            changed = copy.deepcopy(self.row)
            changed["available_at"] += 1
            with self.assertRaisesRegex(ValueError, "data or parent"):
                contract.validate_plan([changed], self.parent, readiness, plan)
            changed_plan = copy.deepcopy(plan)
            changed_plan["training"]["rank"] = 8
            with self.assertRaisesRegex(ValueError, "profile constants"):
                contract.validate_plan([self.row], self.parent, readiness, changed_plan)
            changed_plan = copy.deepcopy(plan)
            changed_plan["source_inventory"] = {}
            with self.assertRaisesRegex(ValueError, "source inventory"):
                contract.validate_plan([self.row], self.parent, readiness, changed_plan)

    def test_adapter_byte_and_generation_changes_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, adapter = Path(temporary), Path(temporary) / "adapter"
            adapter.mkdir()
            config = {
                "peft_type": "LORA",
                "task_type": "CAUSAL_LM",
                "r": 4,
                "lora_alpha": 8,
                "lora_dropout": 0.0,
                "bias": "none",
                "inference_mode": True,
                "target_modules": ["v_proj", "q_proj"],
            }
            (adapter / "adapter_config.json").write_text(json.dumps(config))
            (adapter / "adapter_model.safetensors").write_bytes(
                b"not a real model; file-binding test only"
            )
            manifest = {
                "schema": contract.SCHEMA,
                "family": contract.FAMILY,
                "model_id": contract.probe.MODEL_ID,
                "parent_model_digest": data.digest(self.parent),
                "base_manifest": self.parent,
                "runtime": self.parent["runtime"],
                "backend_versions": VERSIONS,
                "adapter_directory": "adapter",
                "adapter_files": contract.probe._inventory(adapter),
                "peft_version": "test-peft",
            }
            with (
                patch.object(
                    contract.probe,
                    "verify_model",
                    return_value=data.digest(self.parent),
                ),
                patch.object(contract.metadata, "version", return_value="test-peft"),
            ):
                self.assertEqual(
                    contract.verify_candidate(manifest, root), data.digest(manifest)
                )
                changed = copy.deepcopy(manifest)
                changed["runtime"] = copy.deepcopy(changed["runtime"])
                changed["runtime"]["max_input_tokens"] = 1024
                with self.assertRaisesRegex(ValueError, "base or generation"):
                    contract.verify_candidate(changed, root)
                (adapter / "adapter_model.safetensors").write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "immutable standalone adapter"):
                    contract.verify_candidate(manifest, root)


if __name__ == "__main__":
    unittest.main()
