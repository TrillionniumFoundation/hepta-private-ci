#!/usr/bin/env python3
"""Keep native operator verification separate from honest integration work."""

import contextlib
import copy
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).with_name("hepta-lane-e-closure.py")
SPEC = importlib.util.spec_from_file_location("hepta_lane_e_closure", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class LaneEClosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.matrix = json.loads(MODULE.MATRIX_PATH.read_text(encoding="utf-8"))
        self.operator = next(
            row
            for row in self.matrix["modules"]
            if row["module"] == "learning.operator"
        )

    def test_truthful_integration_work_does_not_fail_native_mapping(self) -> None:
        gap = (
            "The default runtime still needs the complete independent operator handoff."
        )
        self.operator["remainingRepositoryGaps"] = [gap]
        findings = MODULE.Findings()
        MODULE.verify_matrix(self.matrix, findings)
        self.assertEqual(findings.integration_work["learning.operator"], [gap])
        self.assertFalse(
            any(
                finding.code in {"repository_gap_open", "repository_gap_shape"}
                or (
                    finding.code == "operation_closed_world"
                    and "learning.operator" in finding.message
                )
                for finding in findings.items
            ),
            findings.items,
        )

    def test_unrelated_module_integration_gates_remain_required(self) -> None:
        for name in ("learning.ledger", "learning.artifacts", "learning.eval"):
            with self.subTest(module=name):
                matrix = copy.deepcopy(self.matrix)
                row = next(row for row in matrix["modules"] if row["module"] == name)
                row["remainingRepositoryGaps"] = [
                    "Unexpected unresolved repository gap."
                ]
                findings = MODULE.Findings()
                MODULE.verify_matrix(matrix, findings)
                self.assertTrue(
                    any(
                        item.code == "repository_gap_open" and name in item.message
                        for item in findings.items
                    )
                )

    def test_supplemental_operator_inventory_is_closed(self) -> None:
        for change in ("missing", "extra", "duplicate"):
            with self.subTest(change=change):
                matrix = copy.deepcopy(self.matrix)
                row = next(
                    row
                    for row in matrix["modules"]
                    if row["module"] == "learning.operator"
                )
                operations = row["supplementalOperations"]
                if change == "missing":
                    operations.pop()
                elif change == "extra":
                    addition = copy.deepcopy(operations[0])
                    addition["operation"] = "unreviewed_operation"
                    operations.append(addition)
                else:
                    operations.append(copy.deepcopy(operations[0]))
                findings = MODULE.Findings()
                MODULE.verify_matrix(matrix, findings)
                self.assertTrue(
                    any(
                        item.code
                        in {"operator_supplemental_missing", "duplicate_operation"}
                        for item in findings.items
                    )
                )

    def test_default_feature_forwarding_cannot_enable_a_legacy_writer(self) -> None:
        for forwarded in (
            MODULE.FEATURE,
            "ledger/qualification-legacy-write",
            "agentd/" + MODULE.FEATURE,
            "agentd?/" + MODULE.FEATURE,
        ):
            with self.subTest(forwarded=forwarded):
                manifest = (
                    '[features]\ndefault=["product"]\nproduct=["'
                    + forwarded
                    + '"]\n'
                    + MODULE.FEATURE
                    + "=[]\n"
                )
                self.assertFalse(MODULE.isolated_feature(manifest))

    def test_missing_operator_source_still_rejects_with_integration_work(self) -> None:
        self.operator["remainingRepositoryGaps"] = ["Runtime composition remains open."]
        self.operator["operations"] = [
            operation
            for operation in self.operator["operations"]
            if operation["operation"]
            != "validate_applicability_with_signed_evidence_v2"
        ]
        findings = MODULE.Findings()
        MODULE.verify_matrix(self.matrix, findings)
        self.assertTrue(
            any(
                finding.code == "operation_closed_world"
                and "learning.operator" in finding.message
                for finding in findings.items
            )
        )

    def test_integration_work_requires_bounded_nonempty_strings(self) -> None:
        for gaps in [None, [{}], [""], ["x" * 4097], ["open"] * 129]:
            with self.subTest(gaps=gaps):
                matrix = copy.deepcopy(self.matrix)
                operator = next(
                    row
                    for row in matrix["modules"]
                    if row["module"] == "learning.operator"
                )
                operator["remainingRepositoryGaps"] = gaps
                findings = MODULE.Findings()
                MODULE.verify_matrix(matrix, findings)
                self.assertTrue(
                    any(
                        finding.code == "repository_gap_shape"
                        and "learning.operator" in finding.message
                        for finding in findings.items
                    )
                )
                self.assertNotIn("learning.operator", findings.integration_work)

    def test_payload_owner_mapping_must_resolve_actual_source(self) -> None:
        operation = next(
            item
            for item in self.operator["supplementalOperations"]
            if item["operation"] == "fit_terminal_cell_from_owner_v1"
        )
        operation["nativeSymbol"] = (
            "codex_hepta_bellman_operator::missing_owner_handoff"
        )
        findings = MODULE.Findings()
        MODULE.verify_matrix(self.matrix, findings)
        self.assertTrue(
            any(
                finding.code == "native_symbol_unresolved"
                and "missing_owner_handoff" in finding.message
                for finding in findings.items
            )
        )

    def test_legacy_product_writer_remains_an_integration_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            product = root / "codex-rs/hepta-agentd/src/lib.rs"
            product.parent.mkdir(parents=True)
            product.write_text(
                "use codex_hepta_learning_ledger::DurableLearningJournal;\n",
                encoding="utf-8",
            )
            manifest = "[features]\ndefault=[]\n" + MODULE.FEATURE + "=[]\n"
            (root / MODULE.MANIFEST).write_text(manifest, encoding="utf-8")
            audit = root / MODULE.EXCEPTIONS
            audit.parent.mkdir(parents=True)
            audit.write_text(
                json.dumps(
                    {
                        "schema": "hepta.lane-e-legacy-writer-exceptions.v2",
                        "authorityDelta": "none",
                        "reviewedBlobs": {
                            MODULE.MANIFEST: MODULE.blob_sha(manifest.encode())
                        },
                        "exceptions": [],
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(MODULE, "ROOT", root):
                findings = MODULE.Findings()
                MODULE.verify_product_writer_exclusivity(findings)
                self.assertEqual(
                    [finding.code for finding in findings.items],
                    ["legacy_learning_writer_product_bypass"],
                )
                product.write_text(
                    "use codex_hepta_learning_ledger::LedgerWriter;\n", encoding="utf-8"
                )
                repaired = MODULE.Findings()
                MODULE.verify_product_writer_exclusivity(repaired)
                self.assertEqual(repaired.items, [])

    def test_signed_decision_public_export_remains_an_owner_boundary_finding(
        self,
    ) -> None:
        original = Path.read_text
        path = MODULE.contract.ROOT / "codex-rs/hepta-intelligence-eval/src/lib.rs"

        def with_signed_public(target, *args, **kwargs):
            text = original(target, *args, **kwargs)
            if target == path:
                return text.replace(
                    "pub(crate) use signed_evaluation::decide_with_signed_evidence_v2;",
                    "pub use signed_evaluation::decide_with_signed_evidence_v2;",
                )
            return text

        with mock.patch.object(Path, "read_text", with_signed_public):
            findings = MODULE.Findings()
            MODULE.contract.verify_learning_eval_production_boundary(findings)
        self.assertTrue(
            any(
                finding.code == "learning_eval_signed_surface"
                and "pub(crate) use signed_evaluation::decide_with_signed_evidence_v2;"
                in finding.message
                for finding in findings.items
            )
        )

    def test_unsigned_evaluator_cannot_escape_the_default_public_surface(self) -> None:
        original = Path.read_text
        path = MODULE.contract.ROOT / "codex-rs/hepta-intelligence-eval/src/closure.rs"

        def with_unsigned_public(target, *args, **kwargs):
            text = original(target, *args, **kwargs)
            return (
                text + "\npub fn decide_independently() {}\n"
                if target == path
                else text
            )

        with mock.patch.object(Path, "read_text", with_unsigned_public):
            findings = MODULE.Findings()
            MODULE.contract.verify_learning_eval_production_boundary(findings)
        self.assertTrue(
            any(
                finding.code == "learning_eval_unsigned_public"
                for finding in findings.items
            )
        )

    def test_source_success_does_not_report_open_integration_complete(self) -> None:
        result = MODULE.Findings()
        result.integration_work["learning.operator"] = [
            "Runtime composition remains open."
        ]
        output = io.StringIO()
        with (
            mock.patch.object(MODULE, "verify", return_value=result),
            mock.patch.object(sys, "argv", [str(SCRIPT), "verify"]),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(MODULE.main(), 0)
        receipt = json.loads(output.getvalue())
        self.assertTrue(receipt["ok"])
        self.assertFalse(receipt["repositoryIntegrationComplete"])
        self.assertEqual(receipt["remainingIntegrationWork"], result.integration_work)


def load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPT.with_name(filename))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CONTRACT = load_script(
    "hepta_learning_operator_contract", "hepta-learning-operator-contract.py"
)
MAPPER = load_script("hepta_learning_operator_map", "hepta-learning-operator-map.py")


class OperatorSourceContractTests(unittest.TestCase):
    def test_shadow_coordinator_does_not_imply_default_runtime_wiring(self) -> None:
        status = CONTRACT.load_json(CONTRACT.STATUS_PATH)
        original = CONTRACT.load_json

        def status_document(path):
            return status if path == CONTRACT.STATUS_PATH else original(path)

        with mock.patch.object(CONTRACT, "load_json", side_effect=status_document):
            self.assertEqual(CONTRACT.verify_status(), status)
            for field, value in (
                ("defaultLoopWired", True),
                ("shadowCoordinatorImplemented", False),
                ("canonicalWireAdaptersImplemented", True),
            ):
                with self.subTest(field=field):
                    changed = copy.deepcopy(status)
                    changed[field] = value

                    def changed_document(path):
                        return (
                            changed if path == CONTRACT.STATUS_PATH else original(path)
                        )

                    with mock.patch.object(
                        CONTRACT, "load_json", side_effect=changed_document
                    ):
                        with self.assertRaises(SystemExit):
                            CONTRACT.verify_status()

    def test_canonical_status_rejects_extra_authority_or_boolean_as_version(
        self,
    ) -> None:
        original = CONTRACT.load_json
        status = original(CONTRACT.STATUS_PATH)
        for change in (
            {"hiddenActivation": True},
            {"schemaVersion": True},
            {"claimBoundary": ""},
        ):
            with self.subTest(change=change):
                modified = {**status, **change}

                def altered(path):
                    return modified if path == CONTRACT.STATUS_PATH else original(path)

                with mock.patch.object(CONTRACT, "load_json", side_effect=altered):
                    with self.assertRaises(SystemExit):
                        CONTRACT.verify_status()

    def test_bazel_cannot_fall_back_to_the_compatibility_root(self) -> None:
        original = CONTRACT.read
        for path, transform in (
            (
                "codex-rs/hepta-bellman-operator/BUILD.bazel",
                lambda value: value.replace(
                    'crate_root = "src/authoritative_lib.rs",', ""
                ),
            ),
            ("defs.bzl", lambda value: value.replace("crate_root = crate_root,", "")),
        ):
            with self.subTest(path=path):

                def altered(target):
                    value = original(target)
                    return transform(value) if target == path else value

                with mock.patch.object(CONTRACT, "read", side_effect=altered):
                    with self.assertRaises(SystemExit):
                        CONTRACT.verify_default_surface()

    def test_projection_cannot_rewrite_caller_or_writer_claims(self) -> None:
        source_sha, source_tree = "a" * 40, "b" * 40
        canonical = {
            "module": "learning.operator",
            "claimBoundary": {"defaultProductLoopWired": False},
            "productCallerState": "owner_ports_uncomposed",
            "productionWriterState": "not_established",
            "operations": [],
            "productCallers": [{"sourcePath": "src/consumer.rs"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canonical_path = root / "canonical.json"
            canonical_path.write_text(json.dumps(canonical), encoding="utf-8")
            status = root / "docs/modules/learning.operator/STATUS.json"
            status.parent.mkdir(parents=True)
            status.write_text("{}\n", encoding="utf-8")
            base = {
                "schema": "hepta.learning-operator-current-implementation-map.v2",
                "schemaVersion": 2,
                "generatedFrom": "canonical.json",
                "canonicalStatus": "docs/modules/learning.operator/STATUS.json",
                "module": "learning.operator",
                "source": {"sha": source_sha, "tree": source_tree},
                "canonicalMapSha256": MAPPER.sha256_bytes(canonical_path.read_bytes()),
                "canonicalStatusSha256": MAPPER.sha256_bytes(status.read_bytes()),
                "sourceObjects": [],
                **canonical,
            }
            path = root / "projection.json"
            with (
                mock.patch.object(MAPPER, "ROOT", root),
                mock.patch.object(MAPPER, "CANONICAL_MAP", canonical_path),
                mock.patch.object(MAPPER, "git", return_value=source_tree),
                mock.patch.object(MAPPER, "mapped_paths", return_value=[]),
            ):
                for key in (
                    None,
                    "schema",
                    "generatedFrom",
                    "canonicalStatus",
                    "productCallerState",
                    "productionWriterState",
                    "productCallers",
                ):
                    with self.subTest(field=key):
                        projection = copy.deepcopy(base)
                        if key is not None:
                            projection[key] = "unreviewed_claim"
                        projection["projectionSha256"] = MAPPER.sha256_bytes(
                            MAPPER.canonical_bytes(projection)
                        )
                        path.write_text(json.dumps(projection), encoding="utf-8")
                        if key is None:
                            MAPPER.verify(path)
                        else:
                            with self.assertRaises(ValueError):
                                MAPPER.verify(path)


if __name__ == "__main__":
    unittest.main()
