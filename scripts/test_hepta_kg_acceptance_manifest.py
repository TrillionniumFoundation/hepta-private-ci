from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent / "hepta_kg_acceptance_manifest.py"


def load_module():
    spec = importlib.util.spec_from_file_location("hepta_kg_acceptance_manifest", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load acceptance manifest module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AcceptanceManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        files = {
            ".github/workflows/hepta-knowledge-graph-qualification.yml": "name: test\n",
            ".github/workflows/hepta-kg-abc-execution.yml": "name: abc\n",
            ".github/actions/hepta-synthetic-merge/action.yml": "name: merge\n",
            "codex-rs/Cargo.lock": "# lock\n",
            "codex-rs/hepta-memory/migrations/0013_kg_generation_semantics.sql": "CREATE TABLE kg(x);\n",
            "codex-rs/hepta-memory/src/cognitive_intelligence_writer.rs": "pub fn writer() {}\n",
            "codex-rs/hepta-memory/src/cognitive_kg_store.rs": "pub fn store() {}\n",
            "codex-rs/hepta-memory/src/cognitive_retrieval.rs": "pub fn retrieve() {}\n",
            "codex-rs/hepta-memory/src/cognitive_store.rs": "pub fn owner() {}\n",
            "codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs": "#[test] fn path() {}\n",
            "codex-rs/hepta-kg/Cargo.toml": "[package]\nname='kg'\n",
            "codex-rs/hepta-kg/src/lib.rs": "pub fn v2() {}\n",
            "codex-rs/hepta-prompt-optimizer/src/lib.rs": "pub fn optimize() {}\n",
            "codex-rs/hepta-prompt-registry/src/lib.rs": "pub fn registry() {}\n",
            "docs/modules/knowledge.graph/IMPLEMENTATION_MAP.json": "{}\n",
            "docs/modules/knowledge.graph/TECHNICAL.md": "# technical\n",
            "scripts/hepta_kg_acceptance_manifest.py": SCRIPT.read_text(encoding="utf-8"),
            "scripts/hepta_kg_qualification_lane.sh": "#!/bin/sh\n",
        }
        for relative, content in files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "test"], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "config", "user.email", "test@example.invalid"],
            check=True,
        )
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "fixture"], check=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_request_is_pending_and_fail_closed(self) -> None:
        request = self.module.issue_request(self.root, [])
        self.assertEqual(request["acceptance"]["status"], "pending_independent_signature")
        self.assertFalse(request["activation"])
        self.assertFalse(request["release"])
        self.assertEqual(
            request["candidate"]["commit"],
            subprocess.check_output(
                ["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True
            ).strip(),
        )

    def test_any_tracked_change_invalidates_candidate(self) -> None:
        before = self.module.candidate_fingerprint(self.root)
        lockfile = self.root / "codex-rs/Cargo.lock"
        lockfile.write_text("# changed\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "drift"], check=True)
        after = self.module.candidate_fingerprint(self.root)
        self.assertNotEqual(before["commit"], after["commit"])
        self.assertNotEqual(before["cargoLockSha256"], after["cargoLockSha256"])
        self.assertNotEqual(before["sourceManifestSha256"], after["sourceManifestSha256"])

    @unittest.skipUnless(shutil.which("ssh-keygen"), "ssh-keygen is required")
    def test_independent_signature_verifies_exact_candidate(self) -> None:
        candidate = self.module.candidate_fingerprint(self.root)
        receipts = []
        for lane in ("source-head", "main-head", "base-merge"):
            receipts.append(
                {
                    "lane": lane,
                    "testedCommit": candidate["commit"] if lane != "base-merge" else "1" * 40,
                    "testedTree": candidate["tree"] if lane != "base-merge" else "2" * 40,
                    "sourceCommit": candidate["commit"],
                    "baseCommit": "3" * 40,
                    "workflowBlob": candidate["workflowBlob"],
                    "cargoLockSha256": candidate["cargoLockSha256"],
                    "schemaSha256": candidate["schemaSha256"],
                    "allRequiredPassed": True,
                    "receiptSha256": lane * 8,
                }
            )
        manifest = {
            "schema": self.module.SCHEMA,
            "candidate": candidate,
            "qualificationReceipts": receipts,
            "acceptance": {
                "status": "accepted",
                "signerIdentity": "independent-operator",
                "signerRole": "independent_operator",
            },
            "implementationOwner": "knowledge-graph",
            "activation": False,
            "release": False,
        }
        manifest_path = self.root / "acceptance.json"
        manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
        payload_path = self.root / "payload.json"
        payload_path.write_bytes(self.module.canonical_payload(manifest))
        key = self.root / "operator_key"
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
            check=True,
        )
        subprocess.run(
            [
                "ssh-keygen",
                "-Y",
                "sign",
                "-f",
                str(key),
                "-n",
                self.module.SIGNATURE_NAMESPACE,
                str(payload_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        signature = Path(str(payload_path) + ".sig")
        allowed = self.root / "allowed_signers"
        allowed.write_text(
            "independent-operator " + Path(str(key) + ".pub").read_text(encoding="utf-8")
        )
        result = self.module.verify_manifest(
            self.root,
            manifest_path,
            signature,
            allowed,
            "independent-operator",
        )
        self.assertEqual(result["status"], "PASS_HEPTA_KG_INDEPENDENT_ACCEPTANCE")

        source = self.root / "codex-rs/hepta-kg/src/lib.rs"
        source.write_text("pub fn changed() {}\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "source drift"], check=True)
        with self.assertRaisesRegex(self.module.AcceptanceError, "changed after acceptance"):
            self.module.verify_manifest(
                self.root,
                manifest_path,
                signature,
                allowed,
                "independent-operator",
            )


if __name__ == "__main__":
    unittest.main()
