"""Named admission regression checks; no general Rust source validation."""

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from authbus_caller_api import ADMISSION, validate_bao_api

ROOT = Path(__file__).resolve().parents[1]
BAO_PATH = "codex-rs/hepta-bao-adapter/src/durable_authbus.rs"
SOURCE = (ROOT / BAO_PATH).read_text()
CONTRACT = json.loads(
    (ROOT / "docs/modules/auth.authbus/PRODUCT_CALLER_CONTRACT.json").read_text()
)
spec = importlib.util.spec_from_file_location(
    "authbus_projection", ROOT / "scripts/authbus-evidence-projection.py"
)
PROJECTION = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PROJECTION)


def admission_field(field):
    return SOURCE.replace(
        f"pub struct {ADMISSION} {{", f"pub struct {ADMISSION} {{\n{field},", 1
    )


class BaoAdmissionTests(unittest.TestCase):
    def test_passive_receipt_output_allowed(self):
        validate_bao_api(SOURCE)

    def test_input_identity_rejected_across_layout_and_visibility(self):
        for field in [
            "pub operation_id: StableId",
            "pub(crate) operation_id : StableId",
            "operation_id: StableId",
            "pub r#operation_id: StableId",
            "pub /* harmless */ operation_id\n: \nStableId",
        ]:
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "caller-supplied operation_id"),
            ):
                validate_bao_api(admission_field(field))

    def test_benign_metadata_attributes_and_comments_allowed(self):
        source = admission_field(
            '#[doc = "operation_id: is not authority"] pub diagnostic: String'
        )
        source = source.replace(
            f"pub struct {ADMISSION}", f"#[non_exhaustive]\npub struct {ADMISSION}"
        )
        source += "\n// operation_id: StableId\n"
        validate_bao_api(source)

    def test_missing_or_duplicate_named_body_requires_review(self):
        for source in ["", SOURCE + f"\nstruct {ADMISSION} {{}}"]:
            with (
                self.subTest(source=source[:30]),
                self.assertRaisesRegex(ValueError, "review changed source shape"),
            ):
                validate_bao_api(source)

    def test_unbalanced_body_rejected(self):
        with self.assertRaisesRegex(ValueError, "unbalanced"):
            validate_bao_api(f"pub struct {ADMISSION} {{")


class ProductContractTests(unittest.TestCase):
    def check(self, name, source):
        caller = copy.deepcopy(
            next(c for c in CONTRACT["callers"] if c["name"] == name)
        )
        caller["testPaths"] = []
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / caller["sourcePath"]
            path.parent.mkdir(parents=True)
            path.write_text(source)
            contract = root / "contract.json"
            contract.write_text(
                json.dumps({"schema": CONTRACT["schema"], "callers": [caller]})
            )
            with (
                patch.object(PROJECTION, "ROOT", root),
                patch.object(PROJECTION, "PRODUCT_CONTRACT", contract),
            ):
                return PROJECTION.validate_product_contract(
                    {"productCallers": [{"name": name}]}
                )

    def test_passive_output_passes_real_product_contract(self):
        self.check("bao_kv_v2_read", SOURCE)

    def test_raw_store_ban_is_preserved(self):
        with self.assertRaisesRegex(ValueError, "forbidden tokens"):
            self.check(
                "bao_kv_v2_read", SOURCE + "\nuse forbidden::AuthBusAuthorityStore;\n"
            )

    def test_output_allowance_does_not_exempt_input_field(self):
        with self.assertRaisesRegex(ValueError, "caller-supplied operation_id"):
            self.check("bao_kv_v2_read", admission_field("pub operation_id: StableId"))

    def test_signed_ingress_forbidden_tokens_are_preserved(self):
        caller = next(
            c for c in CONTRACT["callers"] if c["name"] == "agentd_signed_text"
        )
        source = (ROOT / caller["sourcePath"]).read_text()
        for forbidden in ["SystemTime::now", "AuthBusAuthorityStore"]:
            with (
                self.subTest(forbidden=forbidden),
                self.assertRaisesRegex(ValueError, "forbidden tokens"),
            ):
                self.check("agentd_signed_text", source + f"\n// {forbidden}\n")


class WorkflowSourceTruthTests(unittest.TestCase):
    def check(self, text):
        spec = importlib.util.spec_from_file_location(
            "authbus_source_truth", ROOT / "scripts/check-authbus-source-truth.py"
        )
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workflows = root / ".github/workflows"
            workflows.mkdir(parents=True)
            path = workflows / "authbus-regression.yml"
            path.write_text(text)
            with (
                patch.object(checker, "ROOT", root),
                patch.object(checker, "WORKFLOW_ROOT", workflows),
            ):
                return checker.verify_workflow_immutability(
                    {path.relative_to(root).as_posix()}
                )

    def test_read_only_formatting_remains_allowed(self):
        workflow = (ROOT / ".github/workflows/authbus-authoring-format.yml").read_text()
        self.assertEqual(self.check(workflow), [])

    def test_reintroduced_authoring_mutations_remain_rejected(self):
        for mutation in [
            "permissions:\n  contents: write",
            "run: git add source",
            "run: git commit -m generated",
            "run: git push origin HEAD",
        ]:
            with self.subTest(mutation=mutation):
                self.assertTrue(
                    any(
                        "must be read-only" in error
                        for error in self.check(
                            "name: AuthBus authoring\n" + mutation + "\n"
                        )
                    )
                )


if __name__ == "__main__":
    unittest.main()
