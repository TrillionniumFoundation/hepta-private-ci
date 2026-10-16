import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.hepta_ci_scope import GROUPS, changed_paths, select


class ScopeTests(unittest.TestCase):
    def test_repository_policy_regressions_keep_their_python_scope(self):
        paths = [
            "scripts/hepta_repository_controls.py",
            "scripts/hepta_main_protection.py",
            "scripts/test_hepta_control_hardening.py",
            "scripts/tests/test_hepta_repository_controls.py",
        ]
        scope = select(paths)
        self.assertTrue(scope["derived"])
        self.assertFalse(scope["native"] or scope["full_repo"])
        mixed = select(paths + ["codex-rs/hepta-infer-core/src/lib.rs"])
        self.assertTrue(mixed["inference"])
        self.assertFalse(mixed["full_repo"] or mixed["effects"] or mixed["learning"])
        for unknown in ["scripts/tests/other.py", "scripts/tests/test_hepta.rs"]:
            with self.subTest(path=unknown):
                self.assertTrue(select([unknown])["full_repo"])

    def test_readme_and_ordinary_prose_do_not_prepare_native_dependencies(self):
        self.assertFalse(
            select(["README.md", "docs/modules/inference.control/TECHNICAL.md"])[
                "native"
            ]
        )

    def test_inference_local_change_does_not_run_browser_learning_or_objective(self):
        scope = select(["codex-rs/hepta-infer-core/src/durable_control.rs"])
        self.assertTrue(scope["inference"])
        self.assertTrue(scope["native"])
        self.assertFalse(scope["full_repo"])
        for group in GROUPS - {"inference"}:
            self.assertFalse(scope[group])

    def test_topology_contract_stays_on_lifecycle_boundary(self):
        scope = select(["codex-rs/hepta-types/src/topology.rs"])
        self.assertTrue(scope["lifecycle"])
        self.assertTrue(scope["native"])
        self.assertFalse(scope["inference"])
        self.assertFalse(scope["effects"])
        self.assertFalse(scope["learning"])
        self.assertFalse(scope["objective"])
        self.assertFalse(scope["full_repo"])

    def test_runtime_module_abi_stays_on_lifecycle_boundary(self):
        scope = select(
            [
                "codex-rs/hepta-control-plane/src/module_runtime.rs",
                "codex-rs/hepta-supervisor/src/module_runtime.rs",
                "codex-rs/hepta-fleet/src/module_catalog.rs",
            ]
        )
        self.assertTrue(scope["lifecycle"])
        self.assertTrue(scope["native"])
        self.assertFalse(scope["inference"])
        self.assertFalse(scope["effects"])
        self.assertFalse(scope["learning"])
        self.assertFalse(scope["objective"])
        self.assertFalse(scope["full_repo"])

    def test_signed_original_observer_native_gates_cover_effects_and_lifecycle(self):
        # Supervisor/Control original-effect changes can intentionally have
        # no learning scope. Both signed read-only native guards are required.
        for path in [
            "codex-rs/hepta-supervisor/src/writer_handoff.rs",
            "codex-rs/hepta-control-plane/src/organ_hierarchy.rs",
        ]:
            with self.subTest(path=path):
                scope = select([path])
                self.assertTrue(scope["effects"])
                self.assertTrue(scope["lifecycle"])
                self.assertTrue(scope["native"])
                self.assertFalse(scope["learning"])

        workflow = (
            Path(__file__).resolve().parents[2]
            / ".github/workflows/hepta-architecture-convergence.yml"
        ).read_text(encoding="utf-8")
        expected_if = (
            "if: steps.execution.outputs.run_native == 'true' && "
            "(steps.scope.outputs.effects == 'true' || "
            "steps.scope.outputs.lifecycle == 'true' || "
            "steps.scope.outputs.learning == 'true')"
        )
        checkpoints = (
            (
                "Early original Deep Observer canonical terminal "
                "and signer regressions",
                "Early original signed monotonic custody RPC and no-replay tests",
                ("deep-observer-early-negative.json", "deep-observer-early-full.json"),
                ("--minimum-tests 1", "--minimum-tests 2"),
            ),
            (
                "Early original signed monotonic custody RPC and no-replay tests",
                "Signed serving owners and durable metrics regression",
                ("original-monotonic-custody-signed-rpc.json",),
                ("--minimum-tests 19",),
            ),
        )
        for title, following, records, minimums in checkpoints:
            with self.subTest(gate=title):
                begin = "      - name: " + title + "\n"
                end = "      - name: " + following + "\n"
                self.assertEqual(workflow.count(begin), 1)
                self.assertEqual(workflow.count(end), 1)
                gate = workflow.split(begin, 1)[1].split(end, 1)[0]
                actual_if = next(
                    line.strip()
                    for line in gate.splitlines()
                    if line.strip().startswith("if: ")
                )
                self.assertEqual(actual_if, expected_if)
                for receipt in records:
                    self.assertIn(receipt, gate)
                for minimum in minimums:
                    self.assertIn(minimum, gate)

    def test_cns_original_control_non_test_denial_gate(self):
        # The product-linked CNS library must deny even a caller-supplied
        # valid-looking signed witness before preflight or a route mutation.
        path = "codex-rs/hepta-runtime/tests/cell_split_cns_non_test_denial.rs"
        scope = select([path])
        self.assertTrue(scope["native"])
        self.assertTrue(scope["effects"])
        self.assertTrue(scope["lifecycle"])

        workflow = (
            Path(__file__).resolve().parents[2]
            / ".github/workflows/hepta-architecture-convergence.yml"
        ).read_text(encoding="utf-8")
        begin = "      - name: CellSplit native CNS route shared-Control admission regression\n"
        end = "      - name: Early Neuron original Control/Evidence non-test model denial\n"
        self.assertEqual(workflow.count(begin), 1)
        self.assertEqual(workflow.count(end), 1)
        gate = workflow.split(begin, 1)[1].split(end, 1)[0]
        self.assertIn("cns-original-control-non-test-deny.json", gate)
        self.assertIn("--features cell-split-cns-port --test cell_split_cns_non_test_denial", gate)
        self.assertIn("--minimum-tests 1", gate)
        self.assertLess(
            gate.index("cns-prod-feature-compile.json"),
            gate.index("cns-original-control-non-test-deny.json"),
            "the compiled product-feature library must be checked before external denial",
        )

    def test_original_control_abrupt_process_exit_recovery_native_gate(self):
        # Genuine Control B and an external test marker must survive process
        # exit without being promoted by a cold-start counterfeit Control C.
        source = (
            Path(__file__).resolve().parents[2]
            / "codex-rs/hepta-control-plane/src/ndu_publication_tests.rs"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "fn abrupt_process_exit_after_control_begin_fences_recovery()",
            source,
        )
        self.assertIn(
            "fn sigkill_after_control_begin_without_commit_keeps_original_wal_quarantined()",
            source,
        )
        path = "codex-rs/hepta-control-plane/src/ndu_publication_tests.rs"
        self.assertTrue(select([path])["native"])

        workflow = (
            Path(__file__).resolve().parents[2]
            / ".github/workflows/hepta-architecture-convergence.yml"
        ).read_text(encoding="utf-8")
        start = "      - name: Same-owner CNS and signed Neuron checkpoint linearization\n"
        end = "      - name: CellSplit native CNS route shared-Control admission regression\n"
        self.assertEqual(workflow.count(start), 1)
        self.assertEqual(workflow.count(end), 1)
        gate = workflow.split(start, 1)[1].split(end, 1)[0]
        self.assertIn(
            "control-ndu-process-exit-between-b-c.json", gate
        )
        self.assertIn(
            "--lib abrupt_process_exit_after_control_begin_fences_recovery",
            gate,
        )
        self.assertIn(
            "--lib sigkill_after_control_begin_without_commit_keeps_original_wal_quarantined",
            gate,
        )
        self.assertIn("control-ndu-sigkill-between-b-c.json", gate)
        self.assertLess(
            gate.index("control-ndu-process-exit-between-b-c.json"),
            gate.index("control-ndu-sigkill-between-b-c.json"),
            "the clean process-exit regression must run before true SIGKILL",
        )
        self.assertIn("--minimum-tests 1", gate)
        self.assertIn("--test-threads=1", gate)
        self.assertLess(
            gate.index("control-ndu-atomic-owner.json"),
            gate.index("control-ndu-process-exit-between-b-c.json"),
        )

    def test_neuron_original_effect_non_test_denial_gate(self):
        # A public callback cannot be an independent Control/Evidence owner.
        # Scope must run an external test linked against the normal library.
        for path in [
            "codex-rs/hepta-neuron/src/runtime.rs",
            "codex-rs/hepta-neuron/src/runtime_types.rs",
            "codex-rs/hepta-neuron/tests/public_ndu_tick_non_test_denial.rs",
        ]:
            with self.subTest(path=path):
                scope = select([path])
                self.assertTrue(scope["native"])
                self.assertTrue(scope["learning"])
                self.assertFalse(scope["effects"])
                self.assertFalse(scope["lifecycle"])

        workflow = (
            Path(__file__).resolve().parents[2]
            / ".github/workflows/hepta-architecture-convergence.yml"
        ).read_text(encoding="utf-8")
        name = (
            "      - name: Early Neuron original Control/Evidence "
            "non-test model denial\n"
        )
        next_gate = (
            "      - name: Early Supervisor original-Control "
            "non-test retirement denial\n"
        )
        self.assertEqual(workflow.count(name), 1)
        self.assertEqual(workflow.count(next_gate), 1)
        gate = workflow.split(name, 1)[1].split(next_gate, 1)[0]
        self.assertIn(
            "if: steps.execution.outputs.run_native == 'true' && "
            "(steps.scope.outputs.effects == 'true' || "
            "steps.scope.outputs.lifecycle == 'true' || "
            "steps.scope.outputs.learning == 'true')",
            gate,
        )
        self.assertIn("--test public_ndu_tick_non_test_denial", gate)
        self.assertIn("neuron-original-effect-product-build.json", gate)
        self.assertIn("neuron-original-effect-non-test-deny.json", gate)
        self.assertIn("--minimum-tests 1", gate)

    def test_supervisor_original_control_non_test_retirement_gate(self):
        # The non-test library denies an unverified Supervisor Retired write.
        # A cfg(test) unit fixture cannot substitute for this linked test.
        for path in [
            "codex-rs/hepta-supervisor/src/cell_split_finalization.rs",
            "codex-rs/hepta-supervisor/src/cell_split_finalization_tests.rs",
            "codex-rs/hepta-supervisor/tests/cell_split_finalizer_non_test_gate.rs",
        ]:
            with self.subTest(path=path):
                scope = select([path])
                self.assertTrue(scope["native"])
                self.assertTrue(scope["effects"])
                self.assertTrue(scope["lifecycle"])
                self.assertFalse(scope["learning"])

        root = Path(__file__).resolve().parents[2]
        workflow = (
            root / ".github/workflows/hepta-architecture-convergence.yml"
        ).read_text(encoding="utf-8")
        title = (
            "      - name: Early Supervisor original-Control "
            "non-test retirement denial\n"
        )
        next_title = (
            "      - name: Early original Deep Observer "
            "canonical terminal and signer regressions\n"
        )
        self.assertEqual(workflow.count(title), 1)
        self.assertEqual(workflow.count(next_title), 1)
        gate = workflow.split(title, 1)[1].split(next_title, 1)[0]
        self.assertIn(
            "if: steps.execution.outputs.run_native == 'true' && "
            "(steps.scope.outputs.effects == 'true' || "
            "steps.scope.outputs.lifecycle == 'true' || "
            "steps.scope.outputs.learning == 'true')",
            gate,
        )
        self.assertIn("--features cell-split-supervisor-port --lib", gate)
        self.assertIn("--test cell_split_finalizer_non_test_gate", gate)
        self.assertIn("--minimum-tests 1", gate)
        self.assertIn("supervisor-original-control-non-test-deny.json", gate)
        self.assertIn("supervisor-original-retirement-no-reexecute.json", gate)
        self.assertIn("--features cell-split-supervisor-port --lib real_journal_port", gate)
        self.assertIn("--minimum-tests 5", gate)

    def test_shared_types_and_agentd_keep_cross_domain_coverage(self):
        for path in [
            "codex-rs/hepta-types/src/lib.rs",
            "codex-rs/hepta-agentd/src/state.rs",
        ]:
            with self.subTest(path=path):
                scope = select([path])
                self.assertTrue(all(scope[key] for key in GROUPS))
                self.assertFalse(scope["full_repo"])
        lock_scope = select(["codex-rs/Cargo.lock"])
        self.assertTrue(all(lock_scope[key] for key in GROUPS))
        self.assertTrue(lock_scope["full_repo"])

    def test_generated_module_projections_do_not_force_native_builds(self):
        for path in [
            "docs/modules/SOURCE_BINDINGS.json",
            "docs/modules/MODULE_DOCS.json",
            "docs/readiness/STATUS.md",
        ]:
            with self.subTest(path=path):
                scope = select([path])
                self.assertTrue(scope["derived"])
                self.assertFalse(scope["native"])

    def test_plasticity_change_runs_learning_and_lifecycle_only(self):
        scope = select(["codex-rs/hepta-plasticity/src/topology_v3.rs"])
        self.assertTrue(scope["learning"])
        self.assertTrue(scope["lifecycle"])
        for group in GROUPS - {"learning", "lifecycle"}:
            self.assertFalse(scope[group])

    def test_registry_is_runtime_consumed_lifecycle_input(self):
        scope = select(["docs/modules/MODULES.json"])
        self.assertTrue(scope["derived"])
        self.assertTrue(scope["lifecycle"])
        self.assertTrue(scope["native"])
        self.assertFalse(scope["full_repo"])
        for group in GROUPS - {"lifecycle"}:
            self.assertFalse(scope[group])

    def test_unknown_or_executable_document_selects_full(self):
        for path in [
            "docs/check.rs",
            "scripts/new-verifier.py",
            ".github/workflows/new.yml",
        ]:
            with self.subTest(path=path):
                scope = select([path])
                self.assertTrue(all(scope[key] for key in GROUPS))
                self.assertTrue(scope["full_repo"])
        new_hepta = select(["codex-rs/hepta-new/src/lib.rs"])
        self.assertTrue(all(new_hepta[key] for key in GROUPS))
        self.assertFalse(new_hepta["full_repo"])

    def test_code_owned_markdown_is_not_assumed_pure_prose(self):
        self.assertTrue(select(["codex-rs/core/prompt.md"])["native"])

    def test_rename_keeps_source_and_destination_groups(self):
        scope = select(
            [
                "codex-rs/hepta-infer-core/src/old.rs",
                "codex-rs/hepta-learning-ledger/src/new.rs",
            ]
        )
        self.assertTrue(scope["inference"] and scope["learning"])

    def test_effectful_retirement_keeps_lifecycle_and_effect_tests(self):
        scope = select(["codex-rs/hepta-automation/src/timer_lifecycle.rs"])
        self.assertTrue(scope["effects"] and scope["lifecycle"])

    def test_manual_full_keeps_all_groups_even_with_no_paths(self):
        self.assertTrue(all(select([], force_full=True).values()))

    def test_generated_projection_is_derived_only(self):
        scope = select(["docs/readiness/STATUS.md"])
        self.assertTrue(scope["derived"])
        self.assertFalse(scope["native"])
        self.assertFalse(scope["full_repo"])

    def test_bad_paths_fail_instead_of_selecting_nothing(self):
        for path in [
            "",
            "../README.md",
            "/README.md",
            "docs/../foo.md",
            "docs\\foo.md",
            "docs/a\0.md",
        ]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                select([path])

    def test_commit_id_validation_precedes_subprocess(self):
        with patch("subprocess.run") as run, self.assertRaises(ValueError):
            changed_paths("--output=/tmp/file", "a" * 40)
        run.assert_not_called()

    def test_git_diff_covers_real_rename_and_deleted_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def git(*args):
                return (
                    subprocess.check_output(
                        ["git", "-C", directory, *args], stderr=subprocess.DEVNULL
                    )
                    .decode()
                    .strip()
                )

            git("init", "-q")
            git("config", "user.name", "Scope Test")
            git("config", "user.email", "scope@localhost")
            old = root / "codex-rs/hepta-infer-core/src/old.rs"
            old.parent.mkdir(parents=True)
            old.write_text("fn original() {}\n")
            git("add", ".")
            git("commit", "-qm", "base")
            base = git("rev-parse", "HEAD")
            new = root / "docs/new name.md"
            new.parent.mkdir()
            old.rename(new)
            git("add", "-A")
            git("commit", "-qm", "renamed")
            head = git("rev-parse", "HEAD")
            previous = os.getcwd()
            try:
                os.chdir(directory)
                paths = changed_paths(base, head)
            finally:
                os.chdir(previous)
            self.assertIn("codex-rs/hepta-infer-core/src/old.rs", paths)
            self.assertIn("docs/new name.md", paths)
            self.assertTrue(select(paths)["inference"])


if __name__ == "__main__":
    unittest.main()
