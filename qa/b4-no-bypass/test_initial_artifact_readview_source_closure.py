"""Source guards for the actual Root Initial Artifact readview.

These mutation checks protect concrete authority checks. They are not an A
execution, independent evaluation, native result or cold-recovery receipt.
"""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "initial_artifact_source_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
CALLERS = {
    "root_initial_artifact_authorities": [AGENT + "production_initial_q24.rs"],
    "root_initial_artifact_revalidate": [
        "codex-rs/hepta-agentd/src/neuron_generation_artifact_readback.rs",
        "codex-rs/hepta-agentd/src/neuron_generation_current_initial_root.rs"
    ],
    "root_initial_artifact_current_bridge": [
        "codex-rs/hepta-agentd/src/neuron_generation_artifact_readback.rs"
    ],
    "root_initial_artifact_store_client": [
        "codex-rs/hepta-agentd/src/neuron_generation_current_initial_root.rs",
        AGENT + "neuron_generation_current_initial_learning_trust.rs",
        AGENT + "neuron_generation_current_initial_run_start.rs"
    ],
    "root_initial_artifact_same_session": [
        "codex-rs/hepta-agentd/src/root_generation_initial_artifacts.rs",
        "codex-rs/hepta-agentd/src/root_generation_initial_source_capture.rs",
        AGENT + "root_generation_initial_learning_trust.rs"
    ],
    "root_initial_artifact_full_pin": [
        "codex-rs/hepta-agentd/src/root_generation_initial_artifacts.rs"
    ],
    "root_initial_artifact_publish": [
        "codex-rs/hepta-agentd/src/neuron_generation_initial.rs"
    ]
}


class InitialArtifactReadviewClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def reject_removal(self, filename, function, marker, occurrence=0):
        path = AGENT + filename
        rows = [r for r in self.manifest["protected_file"] if r["path"] == path]
        self.assertTrue(rows)
        source = (ROOT / path).read_text()
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        self.assertEqual(code.count(function), 1)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        offset = start
        for _ in range(occurrence + 1):
            offset = source.index(marker, offset, end + 1)
            offset += len(marker)
        offset -= len(marker)
        mutated = source[:offset] + "/* " + marker + " */" + source[offset + len(marker):]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(mutated)
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_closed_callers_are_actual_with_the_original_main_assembly(self):
        rows = {r["id"]: r for r in self.manifest["boundary"]}
        for identifier, callers in CALLERS.items():
            with self.subTest(boundary=identifier):
                self.assertEqual(rows[identifier]["product_callers"], callers)
        self.assertIn(AGENT + "root_generation_initial_artifacts.rs",
                      rows["root_generation_original_selection_recheck"]["product_callers"])

    def test_actual_client_full_pin_and_original_final_use_precede_readview(self):
        for marker in (
            "self.fenced.load(", ".require_same_original_session(&root.session)?",
            "self.profile.local_consumer != consumer.local_state_dir",
            ".current_external_frontier()", ".open_matching_artifact_readback(",
            "Arc::downgrade(self)", "readback.revalidate(",
        ):
            with self.subTest(marker=marker):
                self.reject_removal("root_generation_initial_artifacts.rs",
                                    "fn open_original_artifact_authorities(", marker)
        self.reject_removal("root_generation_initial_artifacts.rs",
                            "fn open_original_artifact_authorities(",
                            ".require_same_original_session(&root.session)?", 1)
        for marker in ("artifact_pin(&inputs)? != self.artifacts",
                       "selected.observation().digest().to_string() != self.selection"):
            self.reject_removal("authority_host_generation_initial_inputs.rs",
                                "fn open_matching_artifact_readback(", marker)

    def test_same_actual_client_brackets_physical_artifact_revalidation(self):
        for occurrence in (0, 1):
            self.reject_removal("root_generation_initial_artifacts.rs", "fn revalidate(",
                                "self.require_original_client(client)", occurrence)
        for marker in ("self.original.upgrade()", "!Arc::ptr_eq(&original, client)",
                       "client.fenced.load(", "client.profile != self.profile",
                       "client.mode != self.mode"):
            self.reject_removal("root_generation_initial_artifacts.rs",
                                "fn require_original_client(", marker)
        self.reject_removal("root_generation_publication_connection.rs",
                            "fn require_same_original_session(",
                            "!Arc::ptr_eq(&self.verifier, &session.verifier())")

    def test_root_initial_reader_cannot_supply_writer_or_other_current_store(self):
        self.reject_removal("neuron_generation_artifact_readback.rs", "fn writer(",
                            "Self::RootInitial(_) => Err(invalid(")
        self.reject_removal("neuron_generation_current_store.rs", "fn original_initial_client(",
                            "_ => Err(invalid(")
        self.reject_removal("neuron_generation_current_initial_root.rs",
                            "fn revalidate_original_initial_artifacts(",
                            "self.store.original_initial_client()?")

    def test_current_brackets_original_artifact_and_consumed_final_use(self):
        for occurrence in (0, 1):
            self.reject_removal("neuron_generation_update_live.rs", "fn check_current(",
                                "self.current.check_current(binding)", occurrence)
        for marker in (".lock_initial()", ".revalidate_owner(", ".verify_retained_use("):
            self.reject_removal("neuron_generation_update_live.rs", "fn check_live(", marker)

    def test_publication_keeps_claim_dispatch_genesis_and_original_cas(self):
        function = "fn publish_initial_with_original_artifacts<W: AnchorWitnessStore>("
        for marker in (".current_external_frontier()", ".revalidate_owner(",
                       "claim_final_use(", "dispatch_final_use_with_witness(",
                       "publication.artifacts.revalidate_owner(",
                       "self.store.replace(expected, &next)"):
            self.reject_removal("neuron_generation_current_initial.rs", function, marker)
        for occurrence in (0, 1):
            self.reject_removal("neuron_generation_current_initial.rs", function,
                                "self.require_initial_genesis(prepared, new)", occurrence)

    def test_all_six_actual_artifact_writer_callers_keep_writer_gate(self):
        sites = (
            ("cell_q24_publication_root_stage.rs", "fn publish_candidate("),
            ("cell_q24_publication_root_stage.rs", "fn recover_published("),
            ("cell_q24_publication_root_stage.rs", "fn revalidate("),
            ("cell_q24_publication_driver.rs", "fn load_selected("),
            ("cell_q24_publication_driver.rs", "fn publish_candidate("),
            ("neuron_v13_generation_update.rs", "fn revalidate_selection("),
        )
        for filename, function in sites:
            with self.subTest(file=filename, function=function):
                self.reject_removal(filename, function, ".writer()?")

    def test_local_initial_update_and_forward_recovery_require_original_writer(self):
        sites = (
            ("neuron_generation_initial.rs",
             "fn prepare_agentd_generation_initial_v1<W: AnchorWitnessStore>("),
            ("neuron_generation_update.rs", "fn prepare_with_completion<Old, New>("),
            ("neuron_generation_update.rs",
             "fn recover_agentd_generation_update_v1<W: AnchorWitnessStore>("),
            ("neuron_generation_update_forward.rs",
             "fn prepare_agentd_generation_forward_recovery_v1<Old, New>("),
            ("neuron_generation_initial_forward.rs",
             "fn prepare_agentd_generation_initial_forward_recovery_v1<W: AnchorWitnessStore>("),
        )
        for filename, function in sites:
            with self.subTest(file=filename):
                self.reject_removal(filename, function, "authorities.artifacts.writer()?")


if __name__ == "__main__":
    unittest.main()
