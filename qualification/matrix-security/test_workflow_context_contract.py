"""Regression checks for Matrix CI startup and non-waivable security gates.

These source checks guard the GitHub Actions expression contexts after an
invalid job-level `runner.temp` reference caused no-job workflow failures.
They do not substitute for actually running Actions or cargo-deny.
"""

from pathlib import Path
import re
import unittest


WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github/workflows/hepta-matrix-security-qualification.yml"
)


class WorkflowContextContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = WORKFLOW.read_text(encoding="utf-8")
        cls.lines = cls.source.splitlines()

    def test_job_environment_uses_only_available_expression_contexts(self):
        job_env_sections = 0
        for index, line in enumerate(self.lines):
            if line != "    env:":
                continue
            job_env_sections += 1
            for field in self.lines[index + 1 :]:
                if field.strip() and not field.startswith("      "):
                    break
                if field.lstrip().startswith("#"):
                    continue
                # The runner context is unavailable in jobs.<job_id>.env:
                # GitHub rejects the entire workflow before creating jobs.
                self.assertNotIn("${{ runner.", field)
        self.assertGreater(job_env_sections, 0)

    def test_all_matrix_checkouts_are_immutable_source_or_pinned_upstream(self):
        # GitHub's default pull_request checkout is a synthetic merge commit,
        # not the source HEAD on which the claimed security gate must be bound.
        # Audit EVERY checkout, including later SDK candidate jobs; a default
        # checkout may otherwise silently alter the security graph.
        checkout_pattern = re.compile(
            r"(?m)^ {6,8}(?:- )?uses: actions/checkout@[a-f0-9]{40}\n"
            r" {8}with:\n((?: {10}[a-z-]+:.*\n)+)"
        )
        groups = checkout_pattern.findall(self.source)
        self.assertEqual(self.source.count("uses: actions/checkout@"), len(groups))
        own = upstream = 0
        for block in groups:
            attrs = dict(re.findall(r"(?m)^ {10}([a-z-]+): (.*)$", block))
            self.assertEqual(attrs.get("persist-credentials"), "false")
            if "repository" not in attrs:
                own += 1
                self.assertEqual(
                    attrs.get("ref"), "${{ github.event.pull_request.head.sha || github.sha }}",
                    "a Matrix security job must never silently test synthetic merge HEAD",
                )
            else:
                upstream += 1
                self.assertEqual(attrs["repository"], "matrix-org/matrix-rust-sdk")
                self.assertRegex(attrs.get("ref", ""), r"^[0-9a-f]{40}$")
                self.assertIn(attrs.get("path"), ("upstream", "upstream-release", "upstream-anymap-commit"))
        self.assertEqual((own, upstream), (7, 7))
        # The original four non-pinned checkouts were also merely printing
        # git rev-parse instead of refusing a wrong SHA.
        self.assertEqual(
            self.source.count('test "$(git rev-parse HEAD)" = "$HEPTA_SOURCE_SHA"'), 5
        )

    def test_missing_exact_head_checkout_is_detected_by_contract(self):
        # The invariant is intended to detect a future accidental removal of
        # an explicit PR-source pin, not simply the current source shape.
        checkout_pattern = re.compile(
            r"(?m)^ {6,8}(?:- )?uses: actions/checkout@[a-f0-9]{40}\n"
            r" {8}with:\n((?: {10}[a-z-]+:.*\n)+)"
        )
        correct = checkout_pattern.findall(self.source)
        self.assertEqual(len(correct), 14)
        tampered = self.source.replace(
            "          ref: ${{ github.event.pull_request.head.sha || github.sha }}\n",
            "",
            1,
        )
        unpinned = checkout_pattern.findall(tampered)
        self.assertEqual(len(unpinned), len(correct))
        self.assertTrue(any(
            "repository:" not in block and "          ref:" not in block
            for block in unpinned
        ))

    def test_disposable_stage_is_unique_and_outside_repository(self):
        matching = [
            line.strip()
            for line in self.lines
            if re.match(r"^      STAGE: ", line)
        ]
        self.assertEqual(len(matching), 1)
        stage = matching[0]
        self.assertIn("${{ github.workspace }}/../hepta-matrix-stage-", stage)
        self.assertIn("${{ github.run_id }}", stage)
        self.assertIn("${{ matrix.sqlite_arm }}", stage)
        self.assertNotIn("runner.temp", stage)
        self.assertIn('git worktree add --detach "$STAGE" "$SOURCE_SHA"', self.source)
        self.assertIn('git worktree remove --force "$STAGE"', self.source)

    def test_crypto_gate_remains_non_waivable_and_independently_blocking(self):
        start = self.source.index("  no-waiver-crypto-migration:")
        end = self.source.index("  pinned-upstream-source-probe:", start)
        gate = self.source[start:end]
        self.assertIn("matrix_dependency_gate.py --root . --require-safe", gate)
        self.assertNotIn("continue-on-error: true", gate)
        self.assertIn("name: Non-waivable dependency security gate", gate)
        self.assertIn("matrix-sdk-sqlite-*/**", self.source)

    def test_accepted_triggers_and_pinned_upstream_candidates(self):
        self.assertIn("  workflow_dispatch:", self.source)
        self.assertIn("  pull_request:", self.source)
        self.assertIn("b18166c68bb958a21f0bca8b2d8320cb53583362", self.source)
        self.assertIn("9c5fdd2cf5be1b7b8b20541e56d7a109db968534", self.source)
        self.assertIn("b3c07ea6ba6e8e46e30811c0500b04505c4be9f9", self.source)

    def test_async_trait_repin_is_isolated_read_only_diagnostic(self):
        # A stale Cargo.lock may be repinned only inside the detached stage;
        # a generated lock is never copied into production or used to waive
        # the independently failing cargo-deny/Matrix crypto security gate.
        start = self.source.index("  disposable-cargo-resolution-probe:")
        diagnostic = self.source[start:]
        self.assertIn("isolated_lock_repin_probe.py", diagnostic)
        self.assertIn('--manifest "$STAGE/codex-rs/Cargo.toml"', diagnostic)
        self.assertIn('--lock "$STAGE/codex-rs/Cargo.lock"', diagnostic)
        self.assertIn("-p async-trait --precise 0.1.92", diagnostic)
        self.assertIn("CARGO_INITIAL_STATUS=", diagnostic)
        self.assertIn("disposable_async_trait_update_status", diagnostic)
        self.assertIn("git worktree remove --force", diagnostic)
        self.assertNotIn("continue-on-error: true", diagnostic)

    def test_isolated_sdk_compile_does_not_bypass_security_or_touch_hepta_lock(self):
        # Compiling a patched *upstream source candidate* is the next strict
        # prerequisite, not evidence of a safe Hepta 0.18 -> 0.19 migration.
        start = self.source.index("  minimal-backport-native-compile:")
        end = self.source.index("  disposable-cargo-resolution-probe:", start)
        candidate = self.source[start:end]
        self.assertIn("needs: minimal-anymap-backport-source-probe", candidate)
        self.assertIn("disposable_backport_probe.py", candidate)
        self.assertIn("rustup toolchain install 1.96.0", candidate)
        self.assertIn("cargo +1.96.0 metadata", candidate)
        self.assertIn("assert not select(\"anymap2\")", candidate)
        self.assertIn("cargo +1.96.0 check --locked", candidate)
        self.assertIn("--features e2e-encryption,sqlite", candidate)
        self.assertIn('"hepta_source_modified": False', candidate)
        self.assertIn('"hepta_cargo_lock_updated": False', candidate)
        self.assertIn('"cargo_deny_verified": False', candidate)
        self.assertIn('"production_authorized": False', candidate)
        self.assertIn("git diff --exit-code", candidate)
        self.assertNotIn("continue-on-error: true", candidate)
        self.assertNotIn("cargo update --manifest-path codex-rs/Cargo.toml", candidate)
        self.assertNotIn('"production_authorized": True', candidate)

    def test_disposable_hepta_adapter_compiler_is_exact_sha_and_non_authorizing(self):
        begin = self.source.index("  disposable-hepta-matrix-adapter-compile:")
        end = self.source.index("  disposable-cargo-resolution-probe:", begin)
        candidate = self.source[begin:end]
        self.assertIn('git worktree add --detach "$STAGE" "$SOURCE_SHA"', candidate)
        self.assertIn("--sqlite-arm use_upstream_sqlite", candidate)
        self.assertIn("isolated_lock_repin_probe.py", candidate)
        self.assertIn("adapter_candidate_gate.py", candidate)
        self.assertIn("--source-manifest codex-rs/Cargo.toml", candidate)
        self.assertIn("HEPTA_MATRIX_SOURCE_SHA", candidate)
        self.assertIn('cargo +1.96.0 check --locked', candidate)
        self.assertIn("-p codex-hepta-matrix-sdk -p codex-hepta-matrixd", candidate)
        self.assertIn("--all-targets", candidate)
        self.assertIn('"cargo_deny_verified": False', candidate)
        self.assertIn('"production_authorized": False', candidate)
        self.assertIn('git worktree remove --force "$HEPTA_MATRIX_ADAPTER_STAGE"', candidate)
        self.assertIn("git diff --exit-code", candidate)
        self.assertNotIn("continue-on-error: true", candidate)
        self.assertNotIn('cargo update --manifest-path codex-rs/Cargo.toml', candidate)

    def test_minimal_reviewed_hepta_matrix_compiler_is_non_promoting(self):
        # Different from the older 278-commit upstream-tip experiment: this
        # compiles Hepta callers against the exact 0.19.1 source + narrow,
        # source-reviewed AnyMap3 patch. Original real Cargo/Bazel locks stay.
        begin = self.source.index("  minimal-hepta-matrix-adapter-compile:")
        end = self.source.index("  disposable-hepta-matrix-adapter-compile:", begin)
        candidate = self.source[begin:end]
        self.assertIn("needs: minimal-anymap-backport-source-probe", candidate)
        self.assertIn("minimal_hepta_source_stage.py", candidate)
        self.assertIn("minimal_hepta_graph_gate.py", candidate)
        self.assertIn("rustup toolchain install 1.96.0", candidate)
        self.assertIn("cargo +1.96.0 metadata", candidate)
        self.assertIn("cargo +1.96.0 check --locked", candidate)
        self.assertIn("-p codex-hepta-matrix-sdk -p codex-hepta-matrixd", candidate)
        self.assertIn("e2ee_interoperability_verified", candidate)
        self.assertIn("sqlite_wal_crash_recovery_verified", candidate)
        self.assertIn('"cargo_deny_verified": False', candidate)
        self.assertIn('"production_authorized": False', candidate)
        self.assertIn('git worktree remove --force "$HEPTA_MINIMAL_STAGE"', candidate)
        self.assertIn("git diff --exit-code", candidate)
        self.assertNotIn("continue-on-error: true", candidate)
        self.assertNotIn("cargo update --manifest-path codex-rs/Cargo.toml", candidate)
        self.assertNotIn("git checkout -b", candidate)

    def test_source_root_lockfile_remains_outside_repin_command(self):
        start = self.source.index("  disposable-cargo-resolution-probe:")
        diagnostic = self.source[start:]
        self.assertNotIn("cargo update -p async-trait", diagnostic)
        self.assertIn('cargo +1.96.0 update \\', diagnostic)
        self.assertIn('timeout 180 cargo +1.96.0 update', diagnostic)
        self.assertIn('--manifest-path "$STAGE/codex-rs/Cargo.toml"', diagnostic)
        self.assertIn("production_authorized':False", diagnostic)


if __name__ == "__main__":
    unittest.main()
