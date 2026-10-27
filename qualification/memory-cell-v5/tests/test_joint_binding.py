"""Artificial binding fixtures only; no independent held query is opened."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sklearn.linear_model import LogisticRegression

from v5.config import CANDIDATES
from v5.contracts import LABELS, canonical, file_identity, sha256, write_json
from v5.features import FeatureBlock
from v5.joint_binding import GATES, SEEDS, verify_freeze
from v5.joint_cases import load_held
from v5.joint_evaluation import access_held
from v5.joint_selection import (
    SEALED_ROUTER_FIELDS,
    selected_identity,
    verify_selected_models,
)
from v5.router import Router, parameter_digest


def source_fixture(root):
    files = {}
    for name in (
        "run.py",
        "v5/reader.py",
        "legacy_v3/reader.py",
        "maintenance/freeze.py",
        "PROTOCOL.json",
        "VENDOR.json",
        "assets/ASSETS.json",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# artificial mechanism source\n" if name.endswith(".py") else "{}\n"
        )
        files[name] = file_identity(path)
    frozen = {
        "frozen": True,
        "source_commit": "1" * 40,
        "seeds": list(SEEDS),
        "gates": GATES,
        "source_files": files,
        "assets_binding_sha256": files["assets/ASSETS.json"]["sha256"],
    }
    write_json(root / "FREEZE.json", frozen)
    return frozen


def selected_fixture(root, frozen, seed, candidate):
    """Fit seven hand-authored tokens, with a one-candidate unit-test scope."""
    words = [
        "current",
        "earlier",
        "subtract",
        "average",
        "range",
        "maximum",
        "forecast",
    ]
    block, matrix = FeatureBlock.fit("word", words)
    learned = LogisticRegression(C=1.0, solver="lbfgs").fit(matrix, list(LABELS))
    reorder = [list(learned.classes_).index(label) for label in LABELS]
    training_root = root / "artificial-training"
    training_root.mkdir()
    source = {
        "source_commit": frozen["source_commit"],
        "development": False,
        "files": frozen["source_files"],
    }
    write_json(training_root / "SOURCE.json", source)
    identity = {
        "seed": seed,
        "source_commit": frozen["source_commit"],
        "source_inventory_sha256": sha256(canonical(source["files"])),
        "artificial_mechanism_fixture": True,
    }
    calibration = {
        "minimum_confidence": 0.0,
        "minimum_margin": 0.0,
        "reject_all": False,
    }
    router = Router(
        [block],
        learned.coef_[reorder],
        learned.intercept_[reorder],
        calibration,
        candidate,
        identity,
    )
    seed_path = training_root / f"seed-{seed}"
    selected = seed_path / "selected"
    artifact = router.save(selected)
    metrics = {
        "known_correct_accepted": 6,
        "known_wrong_accepted": 0,
        "ood_false_accepted": 0,
        "ood_risk_gate": True,
    }
    receipt = {
        "name": candidate["name"],
        "candidate": candidate,
        "seed": seed,
        "training_identity": identity,
        "calibration": calibration,
        "artifact": artifact,
        "parameter_digest": parameter_digest(router),
        "selection": metrics,
        "development_diagnostic_only": {"fixture": True},
    }
    diagnostics = seed_path / "candidate-diagnostics" / candidate["name"]
    diagnostics.mkdir(parents=True)
    write_json(diagnostics / "RECEIPT.json", receipt)
    write_json(seed_path / "CANDIDATES.json", [receipt])
    primary = {
        key: receipt[key]
        for key in (
            "calibration",
            "artifact",
            "parameter_digest",
            "selection",
            "development_diagnostic_only",
        )
    }
    primary.update(
        schema="memory-cell-v5.primary-router.v1",
        seed=seed,
        candidate=candidate["name"],
        selected_using_new_held=False,
    )
    write_json(seed_path / "PRIMARY.json", primary)
    return selected


class FrozenBindingMechanisms(unittest.TestCase):
    def test_freeze_requires_actual_complete_inventory_commit_and_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frozen = source_fixture(root)
            with patch("v5.joint_binding.PROJECT", root):
                self.assertEqual(verify_freeze(root / "FREEZE.json")[0], frozen)
                for omitted in (
                    "run.py",
                    "v5/reader.py",
                    "legacy_v3/reader.py",
                    "maintenance/freeze.py",
                    "assets/ASSETS.json",
                ):
                    bad = deepcopy(frozen)
                    del bad["source_files"][omitted]
                    (root / "FREEZE.json").write_bytes(canonical(bad))
                    with (
                        self.subTest(omitted=omitted),
                        self.assertRaisesRegex(ValueError, "omits required"),
                    ):
                        verify_freeze(root / "FREEZE.json")
                for field, value in (
                    ("source_commit", "not-a-commit"),
                    ("assets_binding_sha256", "0" * 64),
                ):
                    bad = {**frozen, field: value}
                    (root / "FREEZE.json").write_bytes(canonical(bad))
                    with self.subTest(field=field), self.assertRaises(ValueError):
                        verify_freeze(root / "FREEZE.json")
                (root / "FREEZE.json").write_bytes(canonical(frozen))
                linked = root / "alias.json"
                linked.symlink_to(root / "FREEZE.json")
                with self.assertRaisesRegex(ValueError, "symbolic link"):
                    verify_freeze(linked)
                source = root / "v5/reader.py"
                source.rename(root / "original.py")
                source.symlink_to(root / "original.py")
                with self.assertRaises(ValueError):
                    verify_freeze(root / "FREEZE.json")

    def test_all_held_files_checked_and_parse_failure_retains_access_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            corpus = root / "queries.en.json"
            corpus.write_text("{malformed artificial JSON")
            annotation = root / "review.json"
            annotation.write_text("{}")
            seal = {
                "schema": "hepta.memory.v5.held-seal.v1",
                "sealed": True,
                "evaluated_by_any_router": False,
                "corpus_file": corpus.name,
                "files": {
                    path.name: file_identity(path) for path in (corpus, annotation)
                },
                "inference_fields": ["utterance", "series_name", "date"],
            }
            write_json(root / "SEAL.json", seal)
            frozen = {"held_seal_sha256": file_identity(root / "SEAL.json")["sha256"]}
            annotation.write_text('{"changed":true}')
            with self.assertRaisesRegex(ValueError, "seal file bytes differ"):
                load_held(corpus, frozen)
            annotation.write_text("{}")
            output = root / "output"
            output.mkdir()
            with self.assertRaises(json.JSONDecodeError):
                access_held(corpus, frozen, output)
            record = json.loads((output / "held-access-attempt.json").read_bytes())
            self.assertTrue(record["held_access_attempted"])
            self.assertTrue(record["written_before_loading_any_held_file"])

    def test_preheld_model_seal_binds_fitted_state_source_and_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frozen = source_fixture(root)
            seed, candidate = 23, CANDIDATES[0]
            selected = selected_fixture(root, frozen, seed, candidate)
            options = {
                "expected_seed": seed,
                "expected_source_commit": frozen["source_commit"],
                "frozen_source_files": frozen["source_files"],
            }
            with (
                patch("v5.joint_selection.PROJECT", root),
                patch("v5.joint_selection.SEEDS", (seed,)),
                patch("v5.joint_selection.CANDIDATES", (candidate,)),
            ):
                identity = selected_identity(selected, **options)
                freeze_identity = file_identity(root / "FREEZE.json")
                sealed = {
                    "schema": "hepta.memory.v5.selected-before-held.v1",
                    "source_commit": frozen["source_commit"],
                    "freeze_sha256": freeze_identity["sha256"],
                    "assets_binding_sha256": frozen["assets_binding_sha256"],
                    "held_opened": False,
                    "routers": {
                        str(seed): {key: identity[key] for key in SEALED_ROUTER_FIELDS}
                    },
                }
                write_json(root / "SELECTED_MODELS.json", sealed)
                self.assertEqual(
                    verify_selected_models({seed: selected}, frozen, freeze_identity)[
                        0
                    ][seed],
                    identity,
                )
                source_file = selected.parent.parent / "SOURCE.json"
                source_raw = source_file.read_bytes()
                source = json.loads(source_raw)
                source["files"]["v5/never_frozen.py"] = None
                source_file.write_bytes(canonical(source))
                with self.assertRaisesRegex(
                    ValueError, "training source differs from the frozen source"
                ):
                    selected_identity(selected, **options)
                source_file.write_bytes(source_raw)
                with self.assertRaisesRegex(ValueError, "training source"):
                    selected_identity(
                        selected, **{**options, "expected_source_commit": "2" * 40}
                    )
                with self.assertRaisesRegex(ValueError, "training seed"):
                    selected_identity(
                        selected, **{**options, "expected_seed": seed + 1}
                    )
                bad = deepcopy(sealed)
                bad["routers"][str(seed)]["files"]["manifest.json"]["sha256"] = "0" * 64
                (root / "SELECTED_MODELS.json").write_bytes(canonical(bad))
                with self.assertRaisesRegex(ValueError, "pre-held seal"):
                    verify_selected_models({seed: selected}, frozen, freeze_identity)
                (root / "SELECTED_MODELS.json").write_bytes(canonical(sealed))
                primary_file = selected.parent / "PRIMARY.json"
                primary = json.loads(primary_file.read_bytes())
                primary["artifact"]["bytes"] += 1
                primary_file.write_bytes(canonical(primary))
                with self.assertRaisesRegex(ValueError, "PRIMARY"):
                    selected_identity(selected, **options)


if __name__ == "__main__":
    unittest.main()
