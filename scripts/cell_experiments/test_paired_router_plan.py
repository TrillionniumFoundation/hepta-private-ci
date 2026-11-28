"""Refit router coordinates from pinned original graph outputs, without generation.

The archived outputs are replayed verbatim. No model/teacher runs, tensor updates,
fresh inference timings, independent examples or native authorization are claimed.
The original business verifier, ridge fit and router-source readback still run.
"""

from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np

from . import coding_sft, data, paired_cold, paired_router_source, paired_source
from .online_v4 import circuit_bundle as circuit, circuit_router


class RecordedTokenizer:
    """Read only the exact tokenizations in the pinned historical observations."""

    def __init__(self, inputs, outputs):
        self.inputs, self.outputs = inputs, outputs
        self.eos_token_id = 2

    def __len__(self):
        return 8

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        if tokenize or not add_generation_prompt:
            raise AssertionError("unexpected retained template mode")
        return " ".join(message["content"] for message in messages)

    def encode(self, text, *, add_special_tokens):
        if add_special_tokens:
            raise AssertionError("unexpected additional tokens")
        return list(self.inputs[text])

    def decode(self, ids, *, skip_special_tokens):
        if not skip_special_tokens:
            raise AssertionError("unexpected retained decode mode")
        return self.outputs[tuple(ids)]


class PairedRouterPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "materials"
        self.root.mkdir()
        repo = Path(__file__).resolve().parents[2]
        fixtures = repo / "qualification"
        archives = [
            (
                fixtures / "paired-router-source-20261123/ROUTER_CONTROL.zip",
                "9b68d105fcba0d8c55283e8bce27457928acbb851c595535633b9eadca3e447f",
            ),
            (
                fixtures
                / "paired-consumer-circuit-20261123/CONSUMER_CIRCUIT_ORIGINALS.zip",
                "08640f268030dbb74b97cc63f1631e510848c99b8522231314b1f2a9b5c83099",
            ),
        ]
        self.observations, inputs, outputs = {}, {}, {}

        def retain(value):
            if isinstance(value, dict):
                if "rendered_input" in value and "input_ids" in value:
                    self.assertEqual(
                        data.digest(value["input_ids"]), value["input_ids_sha256"]
                    )
                    text, ids = value["rendered_input"], tuple(value["input_ids"])
                    self.assertEqual(inputs.setdefault(text, ids), ids)
                    tokens, answer = tuple(value["output_ids"]), value["answer"]
                    self.assertEqual(outputs.setdefault(tokens, answer), answer)
                for item in value.values():
                    retain(item)
            elif isinstance(value, list):
                for item in value:
                    retain(item)

        for index, (path, expected) in enumerate(archives):
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected)
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    if name.endswith("/"):
                        continue
                    raw = archive.read(name)
                    if name.endswith(".json"):
                        retain(json.loads(raw))
                    prefix = (
                        "reader/materials/" if index == 0 else "original/materials/"
                    )
                    if not name.startswith(prefix):
                        continue
                    relative = Path(name.removeprefix(prefix))
                    if index == 0:
                        allowed = relative.parts[0] == "originals" or str(relative) in (
                            "failure.json",
                            "correction.json",
                            "retention.json",
                        )
                    else:
                        allowed = relative.parts[0] in ("base", "reader", "source")
                    if allowed:
                        target = self.root / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(raw)
                if index == 0:
                    self.parent = json.loads(
                        archive.read("reader/materials/parent.json")
                    )
                    self.examples = {}
                    for case in ("source", "reader"):
                        original_dir = Path(self.temp.name) / (case + "-originals")
                        original_dir.mkdir()
                        prefix = case + "/materials/originals/"
                        for name in archive.namelist():
                            if name.startswith(prefix) and not name.endswith("/"):
                                (original_dir / name.removeprefix(prefix)).write_bytes(
                                    archive.read(name)
                                )
                        pair = [
                            json.loads(
                                archive.read(case + "/materials/" + part + ".json")
                            )
                            for part in ("failure", "correction")
                        ]
                        self.examples[case] = paired_source.derive(*pair, original_dir)
                        search = next(
                            name
                            for name in archive.namelist()
                            if name.startswith(case + "/")
                            and name.endswith("/router-search/SEARCH.json")
                        )
                        report = json.loads(archive.read(search))
                        for row in report["observations"]:
                            result = json.loads(
                                archive.read(
                                    search.removesuffix("SEARCH.json")
                                    + row["result_path"]
                                )
                            )
                            self.assertEqual(data.digest(result), row["result_digest"])
                            for node in result["nodes"]:
                                key = (node["cell_id"], data.digest(node["request"]))
                                self.observations.setdefault(key, []).append(
                                    node["output"]
                                )
        template = json.loads((self.root / "base/tokenizer_config.json").read_bytes())[
            "chat_template"
        ]
        self.assertEqual(
            template,
            "{% for m in messages %}{{ m.content }}{% if not loop.last %} {% endif %}{% endfor %}",
        )
        self.tokenizer = RecordedTokenizer(inputs, outputs)
        self.replayed = []

        def tokenizer(model, materials):
            paired_cold.verify_materials(model, materials)
            return self.tokenizer

        def predictor(model, materials):
            coding_sft.verify_model(model, materials)
            cell = next(
                key for key, value in self.parent["models"].items() if value == model
            )
            pending = deepcopy(self.observations)
            owner = self

            class Replay:
                def predict(self, record, *, retain_encoding):
                    owner.assertTrue(retain_encoding)
                    key = (cell, data.digest(record["task"]))
                    output = pending[key].pop(0)
                    owner.assertEqual(output["loaded_model_digest"], data.digest(model))
                    owner.replayed.append((cell, key[1]))
                    return deepcopy(output)

                def close(self):
                    pass

            return Replay()

        self.addCleanup(patch.stopall)
        patch.object(paired_cold, "frozen_tokenizer", tokenizer).start()
        self.loader = patch.object(
            coding_sft, "load_predictor", side_effect=predictor
        ).start()
        self.plan = circuit_router.RouterPlan(
            circuit.execution_binding(), 8, 0.375, 0.125, 0.25
        )
        graphs = [circuit._graph(row) for row in self.parent["router"]["graphs"]]
        budget = circuit.Budget(**self.parent["budget"])
        cells = circuit._registry(self.parent["models"], budget)
        backend = circuit.LocalCells(self.parent["models"], self.root)
        try:
            router, _ = circuit_router.fit_router(
                [self.examples["source"]],
                graphs,
                cells,
                budget,
                backend.generate,
                data.verify_answer,
                Path(self.temp.name) / "parent-search",
                plan=self.plan,
                execution_profile=circuit.PROFILE,
            )
        finally:
            backend.close()
        self.parent.update(router=router.record, router_sha256=router.expected_digest)
        self.parent["router_training_inputs"] = [
            {
                "record_sha256": data.digest(self.examples["source"]),
                "input_ids_sha256": data.digest(
                    self.tokenizer.encode("train", add_special_tokens=False)
                ),
            }
        ]
        circuit.checked_bundle(self.parent, self.root)
        coding_sft.write_new(self.root / "parent.json", self.parent)
        self.parent = json.loads((self.root / "parent.json").read_bytes())

    def test_source_refit_preserves_custom_plan_and_independent_ridge(self):
        before = {
            str(path.relative_to(self.root)): coding_sft.file_hash(path)
            for path in self.root.rglob("*")
            if path.is_file()
        }
        read = paired_router_source.read
        plan = dict(
            schema=paired_router_source.POLICY,
            study=data.digest("router-plan-regression"),
            delivery=data.digest("engineering-fixture"),
            failure=data.digest(read(self.root / "failure.json")),
            correction=data.digest(read(self.root / "correction.json")),
            parent=data.digest(self.parent),
            retention=data.digest(read(self.root / "retention.json")),
            trainer_source_sha256=paired_router_source.source_hash(),
            timeout_seconds=180,
        )
        result, operation = paired_router_source._fit(
            self.root,
            plan,
            {"schema": "engineering_fixture"},
            engineering=True,
        )
        raw, verified = paired_router_source.review_search(
            self.root,
            operation / "router-search",
            self.parent,
            self.examples["reader"],
        )
        self.assertEqual(raw["router"]["plan"], asdict(self.plan))
        self.assertEqual(raw["models"], self.parent["models"])
        self.assertEqual([row["utility"] for row, _ in verified], [-0.375, 0.625])
        x, _ = circuit_router.prompt_features(self.examples["reader"], 8)
        # Independent one-sample ridge identity, not another normal-equation solve.
        expected = np.asarray([-0.375, 0.625])[:, None] * x / (0.375 + float(x @ x))
        np.testing.assert_allclose(
            raw["router"]["weights"], expected, rtol=1e-12, atol=1e-12
        )
        self.assertEqual(np.asarray(raw["router"]["weights"]).shape, (2, 9))
        self.assertEqual(result["update_scope"], paired_router_source.POLICY)
        frozen = read(operation / "FROZEN.json")
        paired_router_source.verify_originals(operation, frozen, result)
        self.assertEqual(frozen["candidate"]["router"]["plan"], asdict(self.plan))
        self.assertEqual(len(self.replayed), 8)
        self.assertEqual(
            before, {name: coding_sft.file_hash(self.root / name) for name in before}
        )

    def test_stale_execution_plan_is_rejected_before_model_loading(self):
        self.loader.reset_mock()
        with self.assertRaisesRegex(ValueError, "execution binding"):
            circuit.fit_bundle(
                [self.examples["reader"]],
                self.parent["models"],
                [circuit._graph(row) for row in self.parent["router"]["graphs"]],
                circuit.Budget(**self.parent["budget"]),
                self.root,
                Path(self.temp.name) / "wrong-plan",
                router_plan=replace(self.plan, execution_binding_digest="f" * 64),
            )
        self.loader.assert_not_called()

    def test_default_fit_stays_default_and_cannot_relabel_custom_parent(self):
        folder = Path(self.temp.name) / "default-plan"
        raw = circuit.fit_bundle(
            [self.examples["reader"]],
            self.parent["models"],
            [circuit._graph(row) for row in self.parent["router"]["graphs"]],
            circuit.Budget(**self.parent["budget"]),
            self.root,
            folder,
            parent=data.digest(self.parent),
        )
        self.assertEqual(
            raw["router"]["plan"],
            asdict(circuit_router.RouterPlan(circuit.execution_binding())),
        )
        with self.assertRaisesRegex(ValueError, "original router study"):
            paired_router_source.review_search(
                self.root, folder, self.parent, self.examples["reader"]
            )


if __name__ == "__main__":
    unittest.main()
