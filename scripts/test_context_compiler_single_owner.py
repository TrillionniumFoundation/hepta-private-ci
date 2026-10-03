#!/usr/bin/env python3
"""Static source-topology regressions for the one context delivery owner."""

from fnmatch import fnmatchcase
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


class ContextCompilerSingleOwnerTests(unittest.TestCase):
    def test_artifact_manifests_bind_every_payload_without_hashing_their_output(self):
        lines = read(
            ".github/workflows/context-compiler-qualification.yml"
        ).splitlines()
        pipelines = []
        for index, line in enumerate(lines):
            match = re.search(
                r'find "\$RUNNER_TEMP/(context-source|context-evidence)"', line
            )
            if match:
                pipelines.append((match.group(1), "\n".join(lines[index : index + 2])))
        self.assertEqual(
            {name for name, _ in pipelines}, {"context-source", "context-evidence"}
        )
        self.assertEqual(len(pipelines), 2)
        for name, pipeline in pipelines:
            with (
                self.subTest(manifest=name),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary) / name
                payloads = {
                    root / "payload.txt": b"retained source or receipt\n",
                    root / "empty.bin": b"",
                    root
                    / "logs/detail with spaces.log": b"native execution\x00bytes\n",
                    root
                    / "logs/artifact-files.sha256": b"same basename is still payload\n",
                }
                for path, content in payloads.items():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                manifest = root / "artifact-files.sha256"
                environment = dict(os.environ, RUNNER_TEMP=temporary)

                def execute(command):
                    subprocess.run(
                        ["bash", "-c", command],
                        env=environment,
                        check=True,
                        capture_output=True,
                    )
                    return {
                        Path(path): digest
                        for digest, path in (
                            line.split("  ", 1)
                            for line in manifest.read_text(
                                encoding="utf-8"
                            ).splitlines()
                        )
                    }

                expected = {
                    path: hashlib.sha256(content).hexdigest()
                    for path, content in payloads.items()
                }
                self.assertEqual(execute(pipeline), expected)
                manifest.write_text("stale previous manifest\n", encoding="utf-8")
                self.assertEqual(execute(pipeline), expected)
                exclusion = f' ! -path "$RUNNER_TEMP/{name}/artifact-files.sha256"'
                without_exclusion = pipeline.replace(exclusion, "")
                self.assertNotEqual(without_exclusion, pipeline)
                invalid = execute(without_exclusion)
                self.assertEqual(set(invalid), set(payloads) | {manifest})
                self.assertNotEqual(
                    invalid[manifest], hashlib.sha256(manifest.read_bytes()).hexdigest()
                )

    def test_registry_and_intelligence_v3_are_registered(self):
        registry = read("codex-rs/hepta-prompt-registry/src/lib.rs")
        intelligence = read("codex-rs/hepta-intelligence/src/lib.rs")
        self.assertEqual(registry.count("mod context_authority;"), 1)
        self.assertIn(
            "pub use context_authority::PromptContextAuthoritySnapshotV3;", registry
        )
        self.assertEqual(intelligence.count("mod prompt_product_v3;"), 1)
        self.assertIn(
            "pub use prompt_product_v3::compile_prompt_registry_v3;", intelligence
        )

    def test_v3_is_default_legacy_is_explicit_and_fixtures_are_qualification_only(self):
        registry = read("codex-rs/hepta-prompt-registry/Cargo.toml")
        intelligence = read("codex-rs/hepta-intelligence/Cargo.toml")
        extension = read("codex-rs/ext/hepta-prompt/Cargo.toml")
        agentd = read("codex-rs/hepta-agentd/Cargo.toml")

        self.assertIn('default = ["prompt-context-v3"]', registry)
        self.assertIn('default = ["prompt-context-v3"]', intelligence)
        self.assertIn('default = ["prompt-context-v3"]', extension)
        self.assertIn(
            'default = ["production-cognitive-write", "prompt-context-v3"]',
            agentd,
        )
        self.assertIn("legacy-prompt-context-v1 = []", intelligence)
        self.assertIn(
            'legacy-prompt-context-v1 = ["codex-hepta-intelligence/legacy-prompt-context-v1"]',
            agentd,
        )
        for manifest in (registry, intelligence, extension, agentd):
            self.assertIn("qualification-context-fixtures", manifest)
        self.assertIn("default-features = false", intelligence)
        self.assertGreaterEqual(agentd.count("default-features = false"), 2)

    def test_only_existing_prompt_runtime_owns_the_physical_send(self):
        extension_root = read("codex-rs/ext/hepta-prompt/src/root.rs")
        canonical_extension = read("codex-rs/ext/hepta-prompt/src/lib.rs")
        agentd_root = read("codex-rs/hepta-agentd/src/lib.rs")
        runtime = read("codex-rs/hepta-agentd/src/prompt_runtime.rs")

        self.assertNotIn("pub mod v3;", extension_root)
        self.assertNotIn("mod v3;", extension_root)
        self.assertIn("mod canonical_runtime;", extension_root)
        self.assertIn("pub use canonical_runtime::*;", extension_root)
        self.assertEqual(canonical_extension.count("pub fn install_prompt_runtime<"), 1)
        self.assertNotIn("install_prompt_runtime_v3", canonical_extension)
        self.assertEqual(agentd_root.count("mod exact_context_delivery;"), 1)
        self.assertEqual(agentd_root.count("mod prompt_runtime;"), 1)
        self.assertNotIn("mod prompt_product_v3;", agentd_root)
        self.assertEqual(runtime.count("pub fn compile_and_stage_v3"), 1)
        self.assertIn(".with_final_request_observer", runtime)
        self.assertIn(".with_final_terminal_observer", runtime)
        self.assertIn(".stage_with(thread_id, turn_id, compiled.clone(), ||", runtime)
        lifecycle = read(
            "codex-rs/hepta-agentd/src/exact_context_delivery/lifecycle.rs"
        )
        self.assertLess(
            lifecycle.index("let result = publish()?;"),
            lifecycle.index("state.staged.insert(key, Arc::new(compiled))"),
        )
        self.assertIn("self.exact.clear_turn_with", runtime)
        self.assertIn("retire_completed_stage", lifecycle)

        v3_definition = ROOT / "codex-rs/ext/hepta-prompt/src/v3.rs"
        for path in sorted((ROOT / "codex-rs").rglob("*.rs")):
            if path == v3_definition:
                continue
            self.assertNotIn(
                "install_prompt_runtime_v3",
                path.read_text(encoding="utf-8"),
                str(path),
            )

    def test_parallel_agentd_owner_cannot_become_implicit(self):
        agentd_root = read("codex-rs/hepta-agentd/src/lib.rs")
        historical = ROOT / "codex-rs/hepta-agentd/src/prompt_product_v3.rs"
        if historical.exists():
            self.assertNotIn("mod prompt_product_v3;", agentd_root, str(historical))

    def test_context_workflows_are_read_only_and_source_writers_are_retired(self):
        forbidden = (
            "contents: write",
            "persist-credentials: true",
            "git push",
            "git commit",
            "apply_context_compiler_",
            "remediate_context_compiler_",
        )
        workflows = sorted((ROOT / ".github/workflows").glob("context-compiler*.yml"))
        self.assertTrue(workflows)
        for path in workflows:
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, text, f"{path}: {token}")
        self.assertFalse(
            (ROOT / ".github/workflows/context-compiler-source-promotion.yml").exists()
        )
        self.assertFalse(
            (ROOT / ".github/workflows/context-compiler-v3-source-bundle.yml").exists()
        )
        self.assertFalse(list((ROOT / "scripts").glob("apply_context_compiler_*.py")))
        self.assertFalse(
            list((ROOT / "scripts").glob("remediate_context_compiler_*.py"))
        )

    def test_supervisor_dependency_changes_select_context_qualification(self):
        workflow = read(".github/workflows/context-compiler-qualification.yml")
        pull_request = workflow.split("  pull_request:\n", 1)[1].split("  push:\n", 1)[
            0
        ]
        path_lines = pull_request.split("    paths:\n", 1)[1].splitlines()
        self.assertTrue(all(line.startswith("      - ") for line in path_lines))
        paths = [line.removeprefix("      - ") for line in path_lines]
        supervisor_scope = "codex-rs/hepta-supervisor/**"
        without_supervisor = [path for path in paths if path != supervisor_scope]
        for changed in (
            "codex-rs/hepta-supervisor/src/restart_journal.rs",
            "codex-rs/hepta-supervisor/Cargo.toml",
        ):
            with self.subTest(changed=changed):
                self.assertTrue(any(fnmatchcase(changed, path) for path in paths))
                self.assertFalse(
                    any(fnmatchcase(changed, path) for path in without_supervisor)
                )

    def test_profile_matrix_covers_both_git_lanes_and_feature_profiles(self):
        workflow = read(".github/workflows/context-compiler-profile-matrix.yml")
        for token in (
            "source-head",
            "synthetic-merge",
            "default-v3",
            "no-default-features",
            "legacy-compatibility",
            "all-features",
            "downstream-consumer",
            "sourceCommit",
            "sourceTree",
            "testedCommit",
            "testedTree",
            "workflowSha",
            "logSha256",
            "payloadCanonicalSha256",
            "candidateVerificationExitCode",
            "candidate-verify.log",
            "--verify",
            "Source topology and external-acceptance regressions",
            "context-profile-build",
            "! -name 'artifact-files.sha256'",
        ):
            self.assertIn(token, workflow)
        self.assertIn("contents: read", workflow)
        self.assertNotIn("context-profile/build", workflow)

    def test_external_acceptance_is_named_host_protected_and_read_only(self):
        workflow = read(".github/workflows/context-compiler-external-acceptance.yml")
        self.assertIn("runs-on: [self-hosted, hepta-context-acceptance]", workflow)
        self.assertIn("name: context-compiler-${{ inputs.mode }}", workflow)
        self.assertIn("contents: read", workflow)
        self.assertIn("actions: read", workflow)
        self.assertIn("openssl dgst -sha256 -verify", workflow)
        self.assertIn("artifact entry size rejected", workflow)
        self.assertIn("non-regular artifact entry", workflow)
        self.assertIn("must contain exactly receipt and signature", workflow)
        self.assertIn("! -name 'artifact-files.sha256'", workflow)
        validator = read("scripts/context_compiler_external_acceptance.py")
        self.assertIn("sourceStateMutationAuthorized", validator)
        self.assertIn("approvals must be independent", validator)
        self.assertIn("approval is future-dated", validator)


if __name__ == "__main__":
    unittest.main()
