"""Mutate the actual scoped Artifact reader; this is no native qualification."""

import importlib.util
from pathlib import Path
import re
import shutil
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
AGENT = "codex-rs/hepta-agentd/src/"
LANE = AGENT + "root_generation_initial_lane.rs"
OWNER = AGENT + "root_generation_initial_artifacts.rs"
BRIDGE = AGENT + "neuron_generation_artifact_readback.rs"
LIVE = AGENT + "neuron_generation_update_live.rs"
INITIAL = AGENT + "neuron_generation_initial.rs"
PREPARE = AGENT + "root_generation_initial_prepare.rs"
SPEC = importlib.util.spec_from_file_location(
    "initial_artifact_admission_source_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)


class InitialArtifactAdmissionSourceClosureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        paths = {LANE, OWNER, BRIDGE, LIVE, INITIAL, PREPARE}
        manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text(encoding="utf-8"))
        self.manifest = {"protected_file": [
            row for row in manifest["protected_file"] if row["path"] in paths
        ]}
        self.assertEqual({row["path"] for row in self.manifest["protected_file"]}, paths)
        self.original = {}
        for relative in paths:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, path)
            self.original[relative] = path.read_text(encoding="utf-8")
        self.verify()

    def span(self, source, marker):
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        self.assertEqual(code.count(marker), 1, marker)
        start = code.index(marker)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end, marker)
        self.assertEqual(code[end], "}", marker)
        return start, end + 1, code[start:end + 1]

    def verify(self):
        PROOF._verify_protected_files(self.root, self.manifest)
        owner = (self.root / OWNER).read_text(encoding="utf-8")
        _, _, fields = self.span(owner, "struct OriginalInitialArtifactOwnerV1")
        self.assertRegex(fields, r"\boriginal\s*:\s*Weak\s*<\s*RootGenerationInitialClient\s*>")
        self.assertNotRegex(fields, r"\bpub(?:\s*\([^)]*\))?\s+\w+\s*:")
        self.assertNotRegex(fields, r"\bArc\s*<\s*RootGenerationInitialClient\s*>")
        _, _, borrowed = self.span(owner, "fn with_original<R>(")
        self.assertNotRegex(borrowed, r"\bacquire_original_lane\s*\(|\bclient\s*\.\s*lane\b")
        self.assertNotRegex(borrowed, r"\b(?:Instant::now|Duration::from_millis)\s*\(")
        self.assertNotRegex(borrowed, r"\.\s*(?:lock|try_lock)\s*\(")
        lane = (self.root / LANE).read_text(encoding="utf-8")
        _, _, action = self.span(lane, "fn with_original_action<T, R>(")
        self.assertNotRegex(action, r"\.\s*(?:lock|recv|send|recv_timeout)\s*\(|\b(?:loop|while)\b")
        self.assertNotRegex(action, r"\baction\s*\([^;]*\)\s*\?")
        _, _, held = self.span(lane, "struct Held<")
        data = re.search(r"\bdata\s*:\s*MutexGuard\s*<", held)
        permit = re.search(r"\bpermit\s*:\s*Permit\s*<", held)
        self.assertIsNotNone(data)
        self.assertIsNotNone(permit)
        self.assertLess(data.start(), permit.start(), "unwind releases the data guard before the token")
        live = (self.root / LIVE).read_text(encoding="utf-8")
        _, _, checking = self.span(live, "fn check_live(")
        selected = list(re.finditer(r"\.\s*selected\b", checking))
        self.assertEqual(len(selected), 1, "one selected lock stays inside the Artifact scope")
        self.assertLess(checking.index("GenerationArtifactOwnerV1::with_initial("), selected[0].start())
        self.assertLess(checking.index("let result = (|| {"), selected[0].start())
        prepare = (self.root / PREPARE).read_text(encoding="utf-8")
        _, _, preparing = self.span(prepare, "fn prepare_original_initial(")
        self.assertEqual(preparing.count("current_prepared = true;"), 1)
        self.assertRegex(preparing, r"else\s*\{\s*completed\s*\}\s*\}$")

    def reject(self, relative, marker, transform):
        source = self.original[relative]
        start, end, _ = self.span(source, marker)
        original_body = source[start:end]
        changed = transform(original_body)
        self.assertNotEqual(changed, original_body)
        path = self.root / relative
        try:
            path.write_text(source[:start] + changed + source[end:], encoding="utf-8")
            with self.assertRaises((PROOF.VerificationFailure, AssertionError)):
                self.verify()
        finally:
            path.write_text(source, encoding="utf-8")

    def replace(self, body, old, new, occurrence=0):
        offsets = [match.start() for match in re.finditer(re.escape(old), body)]
        self.assertGreater(len(offsets), occurrence, old)
        offset = offsets[occurrence]
        return body[:offset] + new + body[offset + len(old):]

    def remove(self, relative, marker, old, occurrence=0):
        self.reject(relative, marker, lambda body: self.replace(
            body, old, "/* removed original check */", occurrence
        ))

    def test_original_artifact_borrow_keeps_same_client_and_absolute_budget(self):
        function = "fn with_original<R>("
        for marker in (
            "self.original.upgrade().ok_or_else(uncertain)?",
            "RootGenerationInitialClient::original_frame_end(&client)?",
            "client.fenced.load(Ordering::Acquire)",
            "RootGenerationPublicationConnectionV1::require_original_publication_session(",
            "&client.connection",
            "client.fence()", "&self.reader", "&client.fenced",
            "|reader| reader.require_original_client(&client)",
        ):
            with self.subTest(marker=marker):
                self.remove(OWNER, function, marker)
        self.reject(OWNER, function, lambda body: self.replace(
            body, "&self.admission", "&client.admission",
        ))
        self.reject(OWNER, "struct OriginalInitialArtifactOwnerV1", lambda body: self.replace(
            body, "Weak<RootGenerationInitialClient>", "Arc<RootGenerationInitialClient>",
        ))
        self.reject(LANE, "fn for_artifact(", lambda body: self.replace(
            body, "Self::with_domain(ARTIFACT)", "Self::with_domain(WIRE)",
        ))
        self.remove(OWNER, "fn open_original_artifact_authorities(",
                    "super::lane::InitialLaneAdmission::for_artifact()?")
        self.remove(BRIDGE, "fn with_initial<R>(", "OriginalInitialArtifactOwnerV1::with_original(")

    def test_failed_artifact_work_still_runs_postchecks_and_releases(self):
        function = "fn with_original_action<T, R>("
        self.reject(LANE, function, lambda body: self.replace(
            body, "let result = action(&held.data);", "let result = action(&held.data)?;",
        ))
        for marker in (
            "self.acquire(data, fenced, end)?", "require_current(&held.data)",
            "held.require_open()?", "let post = require_current(&held.data);",
            "if post.is_err()", "let open = held.require_open();",
            "let released = held.release();", "post?;", "open?;", "released?;",
        ):
            with self.subTest(marker=marker):
                self.remove(LANE, function, marker)
        for occurrence in (0, 1):
            self.remove(LANE, function, "fenced.store(true, Ordering::Release)", occurrence)
        self.reject(LANE, function, lambda body: self.replace(
            body, "let post = require_current(&held.data);",
            "let post = require_current(&held.data)?;",
        ))
        self.reject(LANE, function, lambda body: self.replace(
            body, "let open = held.require_open();", "let open = held.require_open()?;",
        ))
        self.reject(LANE, "fn release(", lambda body: self.replace(
            body, "drop(data);\n        permit.return_token()",
            "let returned = permit.return_token();\n        drop(data);\n        returned",
        ))

    def test_scoped_callers_keep_lock_order_and_durable_error_boundary(self):
        for relative, function in (
            (LIVE, "fn check_live("),
            (INITIAL, "fn publish("),
            (INITIAL, "fn recover_agentd_generation_initial_v1<W: AnchorWitnessStore>("),
            (PREPARE, "fn prepare_original_initial("),
        ):
            with self.subTest(path=relative, function=function):
                self.remove(relative, function, "GenerationArtifactOwnerV1::with_initial(")
        self.reject(LIVE, "fn check_live(", lambda body: self.replace(
            body, "let result = (|| {", "let result = self.selected.lock();\n            let result = (|| {",
        ))
        for marker in ("let result = (|| {", "Ok(result)"):
            self.remove(LIVE, "fn check_live(", marker)
        for marker in (
            "let mut current_prepared = false;", "self.client.prepare_initial_current()?",
            "current_prepared = true;", "if current_prepared",
            "completed.map_err(crate::root_generation_initial_client::uncertain_after_prepare)",
        ):
            with self.subTest(marker=marker):
                self.remove(PREPARE, "fn prepare_original_initial(", marker)
        self.reject(PREPARE, "fn prepare_original_initial(", lambda body: self.replace(
            body, "if current_prepared", "if true",
        ))
        def early_durable_flag(body):
            body = self.replace(body, "current_prepared = true;", "")
            return self.replace(body, "self.client.prepare_initial_current()?;",
                                "current_prepared = true;\n            self.client.prepare_initial_current()?;")
        self.reject(PREPARE, "fn prepare_original_initial(", early_durable_flag)
        self.reject(PREPARE, "fn prepare_original_initial(", lambda body: self.replace(
            body, "} else {\n            completed", "} else {\n            completed.map_err(crate::root_generation_initial_client::uncertain_after_prepare)",
        ))


if __name__ == "__main__":
    unittest.main()
