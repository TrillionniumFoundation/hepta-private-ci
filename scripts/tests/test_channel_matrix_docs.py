"""Canonical generated-document regressions for channel.matrix."""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/channel_matrix_docs.py"
spec = importlib.util.spec_from_file_location("channel_matrix_docs_test", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class ChannelMatrixDocsTests(unittest.TestCase):
    def test_committed_generated_documents_match_canonical_sources(self) -> None:
        rendered = module.render_documents(ROOT)
        self.assertEqual(module.check_documents(ROOT, rendered), [])
        for relative, content in rendered.items():
            self.assertTrue(content.startswith(module.GENERATED_HEADER))
            self.assertEqual((ROOT / relative).read_text(encoding="utf-8"), content)

    def test_current_status_is_fail_closed_and_has_no_embedded_candidate_result(self) -> None:
        model = module.load_model(ROOT)
        self.assertTrue(all(value is False for value in model["status"]["claims"].values()))
        status = module.render_current_status(model)
        self.assertIn("external_readiness_manifest", status)
        self.assertNotIn("workflow_run_id", status)
        self.assertNotIn("productionQualified = true", status)

    def test_closed_inventory_counts_and_review_slices(self) -> None:
        model = module.load_model(ROOT)
        self.assertEqual(len(model["scenarios"]), 29)
        self.assertEqual(len(model["process"]), 18)
        self.assertEqual(len(model["target"]), 29)
        self.assertEqual(len(model["acceptance"]), 5)
        self.assertEqual(len(model["slices"]), 7)
        self.assertEqual(
            [row["id"] for row in model["slices"]],
            [
                "01-sdk-final-use",
                "02-durable-store-migrations",
                "03-runtime-recovery",
                "04-transport-adapter-tcb",
                "05-observability-clock",
                "06-qualification-evidence",
                "07-documentation-generated-status",
            ],
        )

    def test_duplicate_machine_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "duplicate.json"
            path.write_text('{"schema":"one","schema":"two"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                module.load_object(root, "duplicate.json")

    def test_true_current_claim_cannot_generate_documentation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for relative in module.load_model(ROOT)["sources"]["machineSources"]:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)
            status_path = root / "docs/modules/channel.matrix/MODULE_STATUS.json"
            status = json.loads(status_path.read_text(encoding="utf-8"))
            status["claims"]["activation"] = True
            status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
            with self.assertRaisesRegex(ValueError, "closed false set"):
                module.render_documents(root)

    def test_generated_drift_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            model = module.load_model(ROOT)
            for relative in model["sources"]["machineSources"]:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)
            documents = module.render_documents(root)
            module.write_documents(root, documents)
            self.assertEqual(module.check_documents(root, documents), [])
            changed = root / "docs/modules/channel.matrix/CURRENT_STATUS.md"
            changed.write_text(changed.read_text(encoding="utf-8") + "drift\n")
            self.assertEqual(
                module.check_documents(root, documents),
                ["docs/modules/channel.matrix/CURRENT_STATUS.md"],
            )


if __name__ == "__main__":
    unittest.main()
