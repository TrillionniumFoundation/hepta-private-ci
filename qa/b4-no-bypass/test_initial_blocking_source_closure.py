"""Mutate the real Initial scheduler scope without executing native code."""

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
CLIENT = AGENT + "root_generation_initial_client.rs"
ARTIFACT = AGENT + "root_generation_initial_artifacts.rs"
BOUNDARY = "root_initial_original_blocking_scope"
HELPER = "run_original_blocking"
SPEC = importlib.util.spec_from_file_location(
    "initial_blocking_source_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)


class InitialBlockingSourceClosureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.paths = {LANE, CLIENT, ARTIFACT}
        manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text(encoding="utf-8"))
        boundaries = PROOF._boundary_rows(manifest)
        PROOF._verify_privileged_inventory(manifest, boundaries)
        selected = [row for row in boundaries if row.identifier == BOUNDARY]
        self.assertEqual(len(selected), 1)
        self.boundary = selected[0]
        self.assertEqual(self.boundary.call_pattern, r"\brun_original_blocking\b")
        self.assertIsNone(self.boundary.receiver_type)
        self.assertEqual(self.boundary.definition_path, LANE)
        self.assertEqual(set(self.boundary.product_callers), {CLIENT, ARTIFACT})
        self.ignored = tuple(manifest["ignored_path_fragments"])
        self.protected = {"protected_file": [
            row for row in manifest["protected_file"] if row["path"] in self.paths
        ]}
        self.assertEqual({row["path"] for row in self.protected["protected_file"]}, self.paths)
        self.original = {}
        for relative in self.paths:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, path)
            self.original[relative] = path.read_text(encoding="utf-8")
        self.verify()

    def code(self, source):
        return PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))

    def span(self, source, marker):
        code = self.code(source)
        self.assertEqual(code.count(marker), 1, marker)
        start = code.index(marker)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end, marker)
        self.assertEqual(code[end], "}", marker)
        return start, end + 1, code[start:end + 1]

    def scope(self, body, wrapper):
        marker = wrapper + "(|| {"
        self.assertEqual(body.count(marker), 1)
        call = body.index(marker)
        opening = call + len(marker) - 1
        closing = PROOF._matching_delimiter(body, opening, "{", "}")
        self.assertIsNotNone(closing)
        return call, opening, closing

    def verify_caller(self, relative, marker, wrapper, prefix):
        source = (self.root / relative).read_text(encoding="utf-8")
        code = self.code(source)
        self.assertEqual(len(re.findall(r"\brun_original_blocking\b", code)), 1)
        _, _, body = self.span(source, marker)
        call, opening, closing = self.scope(body, wrapper)
        function_open = body.index("{")
        self.assertEqual(
            re.sub(r"\s+", "", body[function_open + 1:call]),
            re.sub(r"\s+", "", prefix),
            "the original end and original Weak upgrade precede the scheduler handoff",
        )
        self.assertRegex(body[closing + 1:], r"\A\s*\)\s*\}\s*\Z")
        inner = body[opening + 1:closing]
        self.assertNotRegex(inner, r"\boriginal_frame_end\b|\bInstant\s*::\s*now\s*\(")
        orders = [
            item for row in self.protected["protected_file"] if row["path"] == relative
            for item in row.get("required_function_order", []) if item["function"] == marker
        ]
        self.assertEqual(len(orders), 1)
        sequence = orders[0]["sequence"]
        index = sequence.index(wrapper + "(|| {")
        PROOF._verify_required_order(
            {"required_order": [sequence[index + 1:]]}, inner, relative + ":original scope"
        )

    def verify(self):
        PROOF._verify_protected_files(self.root, self.protected)
        source = (self.root / LANE).read_text(encoding="utf-8")
        code = self.code(source)
        start, end, helper = self.span(source, "fn run_original_blocking<R>(")
        declaration_start = code.rfind("\n", 0, start) + 1
        self.assertRegex(code[declaration_start:start], r"\A\s*pub\s*\(\s*super\s*\)\s+\Z")
        # This small helper accepts a synchronous, borrowed FnOnce. Only the
        # existing multi-thread runtime hands off. The closure stays on the
        # original thread without spawning business work or creating a runtime;
        # neither the closure nor its result needs Send.
        self.assertRegex(helper, (
            r"\Afn\s+run_original_blocking<R>\(\s*action:\s*impl\s+FnOnce\(\)\s*->\s*R\s*\)"
            r"\s*->\s*R\s*\{\s*if\s+tokio::runtime::Handle::try_current\(\)"
            r"\s*\.is_ok_and\(\|handle\|\s*handle.runtime_flavor\(\)\s*=="
            r"\s*tokio::runtime::RuntimeFlavor::MultiThread\)\s*\{"
            r"\s*tokio::task::block_in_place\(action\)\s*\}\s*else\s*\{"
            r"\s*action\(\)\s*\}\s*\}\Z"
        ))
        outside = code[:declaration_start] + code[end:]
        self.assertNotRegex(outside, (
            r"\b(?:tokio|spawn|spawn_blocking|spawn_local|block_on|block_in_place|LocalSet|"
            r"run_original_blocking)\b|\b(?:use|extern\s+crate)\b[^;]*\bas\b"
        ))
        self.verify_caller(
            CLIENT, "fn exchange(", "self::lane::run_original_blocking",
            "let end = self.original_frame_end()?;",
        )
        self.verify_caller(
            ARTIFACT, "fn with_original<R>(", "super::lane::run_original_blocking",
            "let client = self.original.upgrade().ok_or_else(uncertain)?;"
            "let end = RootGenerationInitialClient::original_frame_end(&client)?;",
        )
        index = {
            path.relative_to(self.root).as_posix(): self.code(path.read_text(encoding="utf-8"))
            for path in PROOF._source_files(self.root, ("codex-rs",))
        }
        PROOF._verify_boundary(self.root, self.boundary, index, self.ignored)

    def replace_once(self, source, old, new):
        self.assertEqual(source.count(old), 1, old)
        return source.replace(old, new, 1)

    def reject(self, relative, transform):
        original = self.original[relative]
        changed = transform(original)
        self.assertNotEqual(changed, original)
        path = self.root / relative
        try:
            path.write_text(changed, encoding="utf-8")
            with self.assertRaises((PROOF.VerificationFailure, AssertionError)):
                self.verify()
        finally:
            path.write_text(original, encoding="utf-8")

    def mutate_function(self, source, marker, transform):
        start, end, _ = self.span(source, marker)
        return source[:start] + transform(source[start:end]) + source[end:]

    def test_original_runtime_branch_preserves_private_non_send_borrows(self):
        mutations = (
            ("pub(super) fn run_original_blocking", "pub(crate) fn run_original_blocking"),
            ("pub(super) fn run_original_blocking", "pub fn run_original_blocking"),
            ("fn run_original_blocking<R>", "async fn run_original_blocking<R>"),
            ("impl FnOnce() -> R", "impl FnMut() -> R"),
            ("impl FnOnce() -> R", "impl FnOnce() -> R + Send + 'static"),
            ("RuntimeFlavor::MultiThread", "RuntimeFlavor::CurrentThread"),
            ("handle.runtime_flavor() ==", "handle.runtime_flavor() !="),
            ("tokio::task::block_in_place(action)", "action()"),
            ("} else {\n        action()", "} else {\n        tokio::task::block_in_place(action)"),
        )
        for old, new in mutations:
            with self.subTest(old=old, new=new):
                self.reject(LANE, lambda source: self.replace_once(source, old, new))

    def test_original_end_precedes_the_entire_wire_and_artifact_scope(self):
        cases = (
            (CLIENT, "fn exchange(", "self::lane::run_original_blocking",
             "let end = self.original_frame_end()?;", "held.release()?"),
            (ARTIFACT, "fn with_original<R>(", "super::lane::run_original_blocking",
             "let end = RootGenerationInitialClient::original_frame_end(&client)?;",
             "|reader| reader.require_original_client(&client)"),
        )
        for relative, marker, wrapper, end_statement, postcheck in cases:
            with self.subTest(path=relative, mutation="end inside handoff"):
                def late_end(body):
                    body = self.replace_once(body, end_statement, "")
                    return self.replace_once(body, wrapper + "(|| {", wrapper + "(|| {\n" + end_statement)
                self.reject(relative, lambda source: self.mutate_function(source, marker, late_end))
            with self.subTest(path=relative, mutation="new end after handoff"):
                self.reject(relative, lambda source: self.mutate_function(source, marker, lambda body:
                    self.replace_once(body, wrapper + "(|| {", wrapper + "(|| {\n" + end_statement)))
            with self.subTest(path=relative, mutation="empty handoff before real work"):
                def outside_work(body):
                    call, opening, closing = self.scope(self.code(body), wrapper)
                    return body[:call] + wrapper + "(|| {});\n" + body[opening + 1:closing] + "\n}"
                self.reject(relative, lambda source: self.mutate_function(source, marker, outside_work))
            with self.subTest(path=relative, mutation="postcheck removed"):
                self.reject(relative, lambda source: self.mutate_function(source, marker, lambda body:
                    self.replace_once(body, postcheck, "/* removed original postcheck */")))

    def test_scheduler_calls_and_aliases_cannot_escape_the_one_helper(self):
        escapes = (
            "use tokio as alternate_runtime;",
            "use tokio::task::block_in_place as alternate_handoff;",
            "fn unrelated() { tokio::task::yield_now(); }",
            "fn unrelated() { std::thread::spawn(|| {}); }",
            "fn unrelated() { run_original_blocking(|| {}); }",
            "pub use self::run_original_blocking as alternate_handoff;",
        )
        for extra in escapes:
            with self.subTest(extra=extra):
                self.reject(LANE, lambda source: source + "\n" + extra + "\n")
        for relative in (CLIENT, ARTIFACT):
            with self.subTest(path=relative, mutation="same-file alias"):
                self.reject(relative, lambda source: source +
                            "\nuse super::lane::run_original_blocking as alternate_handoff;\n")

    def test_closed_callers_reject_third_callers_and_import_only_aliases(self):
        path = self.root / AGENT / "unregistered_initial_blocking.rs"
        escapes = (
            "fn unrelated() { crate::root_generation_initial_client::lane::run_original_blocking(|| {}); }",
            "use crate::root_generation_initial_client::lane::run_original_blocking as alternate;",
            "pub use crate::root_generation_initial_client::lane::run_original_blocking;",
            "fn unrelated() { let function = crate::root_generation_initial_client::lane::run_original_blocking; }",
        )
        for extra in escapes:
            with self.subTest(extra=extra):
                try:
                    path.write_text(extra + "\n", encoding="utf-8")
                    with self.assertRaises(PROOF.VerificationFailure):
                        self.verify()
                finally:
                    path.unlink()


if __name__ == "__main__":
    unittest.main()
