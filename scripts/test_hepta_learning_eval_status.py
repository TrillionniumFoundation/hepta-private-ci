"""Adversarial checks for formatting-stable lexical source call inventory."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "learning_eval_status", Path(__file__).with_name("hepta-learning-eval-status.py")
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class SourceCallInventoryTests(unittest.TestCase):
    def require_fixture(
        self, source, call="archive.verify(verifier, now)", literals=()
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.rs").write_text(source, encoding="utf-8")
            with (
                mock.patch.object(MODULE, "ROOT", root),
                mock.patch.object(MODULE, "REQUIRED_TOKENS", {"source.rs": literals}),
                mock.patch.object(MODULE, "REQUIRED_CODE_CALLS", {"source.rs": [call]}),
            ):
                MODULE.require_tokens()

    def test_rustfmt_method_chain_line_break_keeps_archive_verification(self):
        self.require_fixture(
            "let decision = archive\n"
            "    .verify(verifier, now)\n"
            "    .map_err(RecordedProductEvaluationErrorV1::Evaluation)?;\n"
        )

    def test_cursor_nested_arguments_can_wrap_without_changing_identity(self):
        self.require_fixture(
            "cursor\n .save(\n Some(\n &id\n )\n )?;\n",
            call="cursor.save(Some(&id))",
        )

    def test_removed_or_changed_verification_call_is_rejected(self):
        for source in (
            "let decision = archive;",
            "archive.check(verifier, now);",
            "self.verify(verifier, now);",
            "other_archive.verify(verifier, now);",
            "object.archive.verify(verifier, now);",
            "module::archive.verify(verifier, now);",
            "archive.verify(now, verifier);",
            "archive.verify(other_verifier, now);",
            "archive.verify(verifier, now + 1);",
        ):
            with (
                self.subTest(source=source),
                self.assertRaisesRegex(SystemExit, "missing code call"),
            ):
                self.require_fixture(source)

    def test_whitespace_cannot_join_distinct_identifiers(self):
        for source in (
            "arch ive.verify(verifier, now);",
            "archive.ver ify(verifier, now);",
            "archive.verify(veri fier, now);",
        ):
            with (
                self.subTest(source=source),
                self.assertRaisesRegex(SystemExit, "missing code call"),
            ):
                self.require_fixture(source)

    def test_comments_and_literals_cannot_replace_the_code_call(self):
        for source in (
            "// archive.verify(verifier, now)\n",
            "/* outer /* archive.verify(verifier, now) */ end */",
            'let text = "archive.verify(verifier, now)";',
            'let text = r###"archive.verify(verifier, now)"###;',
            'let text = br#"archive.verify(verifier, now)"#;',
            'archive "literal barrier" .verify(verifier, now);',
        ):
            with (
                self.subTest(source=source),
                self.assertRaisesRegex(SystemExit, "missing code call"),
            ):
                self.require_fixture(source)

    def test_comments_between_code_tokens_preserve_the_call(self):
        self.require_fixture(
            "archive /* outer /* inner */ end */ .verify(\n"
            "verifier, // current verifier\n now\n);"
        )

    def test_documentation_text_checks_stay_exact(self):
        with self.assertRaisesRegex(SystemExit, "missing 'No decoder callback'"):
            self.require_fixture(
                "// No decoder\n// callback\narchive.verify(verifier, now);",
                literals=("No decoder callback",),
            )

    def test_formatted_repository_required_source_inventory_is_present(self):
        MODULE.require_tokens()


class SourceObservationIdentityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.map_path = self.root / "docs/modules/learning.eval/IMPLEMENTATION_MAP.json"
        self.symbol = (
            "RecordedProductEvaluationRunnerV1::qualify_and_persist_with_artifacts"
        )
        for name, value in (
            ("ROOT", self.root),
            ("MAP", self.map_path),
            ("REQUIRED_SYMBOLS", {self.symbol}),
        ):
            patcher = mock.patch.object(MODULE, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.source_path = (
            "codex-rs/hepta-intelligence-eval/src/qualification_artifacts.rs"
        )
        self.codec_path = (
            "codex-rs/hepta-intelligence-eval/src/qualification_archive_codec.rs"
        )
        self.test_path = "codex-rs/hepta-intelligence-eval/tests/qualification.rs"
        self.caller_path = "codex-rs/hepta-agentd/src/intelligence_evaluation.rs"
        for path, content in (
            (self.source_path, "pub fn qualify_and_persist_with_artifacts() {}\n"),
            (self.codec_path, "pub fn decode_archive() {}\n"),
            (self.test_path, "#[test] fn qualification_round_trip() {}\n"),
            (self.caller_path, "pub fn consume_qualification() {}\n"),
            (
                "codex-rs/hepta-intelligence-eval/Cargo.toml",
                "[package]\nname = 'fixture'\n",
            ),
            (
                "codex-rs/hepta-intelligence-eval/BUILD.bazel",
                "rust_library(name = 'fixture')\n",
            ),
        ):
            self.write(path, content)
        MODULE.git("init", "--quiet")
        MODULE.git("add", ".")
        self.commit("observed source")
        self.model = {
            "sourceFacts": {"callers": [{"sourcePath": self.caller_path}]},
            "repositoryControlledGaps": [],
        }
        self.value = {
            "schema": "hepta.module-implementation-map.v3",
            "module": "learning.eval",
            "operations": [
                {
                    "nativeSymbol": self.symbol,
                    "sourcePath": self.source_path,
                    "tests": [self.test_path],
                }
            ],
            "productCallers": self.model["sourceFacts"]["callers"],
            "repositoryControlledGaps": [],
            "claimBoundary": {
                **{key: True for key in MODULE.TRUE_SOURCE},
                **{key: False for key in MODULE.FALSE_CLAIMS},
            },
            "sourceBase": {
                "commit": MODULE.git("rev-parse", "HEAD").stdout.strip(),
                "tree": MODULE.git("rev-parse", "HEAD^{tree}").stdout.strip(),
            },
        }
        self.write_map()

    def write(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def write_map(self):
        self.write(self.map_path.relative_to(self.root), json.dumps(self.value))

    def commit(self, message):
        MODULE.git(
            "-c",
            "user.name=Source Observation Fixture",
            "-c",
            "user.email=source-observation@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "-m",
            message,
        )

    def test_unchanged_owned_and_mapped_source_is_accepted(self):
        MODULE.validate_map(self.model)

    def test_map_only_descendant_preserves_observed_source(self):
        MODULE.git("add", "docs")
        self.commit("bind observation without changing source")
        MODULE.validate_map(self.model)

    def test_changed_unmapped_archive_source_is_rejected(self):
        self.write(self.codec_path, "pub fn decode_archive() { panic!(); }\n")
        with self.assertRaisesRegex(SystemExit, self.codec_path):
            MODULE.validate_map(self.model)

    def test_added_tracked_unmapped_source_is_rejected(self):
        path = "codex-rs/hepta-intelligence-eval/src/new_archive_decoder.rs"
        self.write(path, "pub fn decode_archive_v2() {}\n")
        MODULE.git("add", path)
        with self.assertRaisesRegex(SystemExit, path):
            MODULE.validate_map(self.model)

    def test_added_untracked_unmapped_source_is_rejected(self):
        path = "codex-rs/hepta-intelligence-eval/src/new_archive_decoder.rs"
        self.write(path, "pub fn decode_archive_v2() {}\n")
        with self.assertRaisesRegex(SystemExit, "untracked owned or mapped source"):
            MODULE.validate_map(self.model)

    def test_manifest_and_build_input_changes_are_rejected(self):
        for name in ("Cargo.toml", "BUILD.bazel"):
            path = "codex-rs/hepta-intelligence-eval/" + name
            with self.subTest(path=path):
                self.write(path, "changed build configuration\n")
                with self.assertRaisesRegex(SystemExit, name):
                    MODULE.validate_map(self.model)
                MODULE.git("checkout", "--", path)

    def test_changed_mapped_caller_outside_owned_root_is_rejected(self):
        self.write(self.caller_path, "pub fn consume_qualification() { panic!(); }\n")
        with self.assertRaisesRegex(SystemExit, self.caller_path):
            MODULE.validate_map(self.model)

    def test_changed_mapped_test_is_rejected(self):
        self.write(
            self.test_path, "#[test] fn qualification_round_trip() { panic!(); }\n"
        )
        with self.assertRaisesRegex(SystemExit, self.test_path):
            MODULE.validate_map(self.model)

    def test_missing_canonical_archived_operation_is_rejected(self):
        self.value["operations"] = []
        self.write_map()
        with self.assertRaisesRegex(SystemExit, "implementation-map operation drift"):
            MODULE.validate_map(self.model)


if __name__ == "__main__":
    unittest.main()
