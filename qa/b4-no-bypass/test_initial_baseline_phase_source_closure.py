"""Keep Initial registration before genesis and publication after real genesis.

These mutations guard actual product functions. They do not execute the Root
or daemon, and cannot qualify an ordinary A or a cold recovery.
"""

from pathlib import Path
import re
import tempfile
import tomllib
import unittest

import test_initial_peer_ready_source_closure as ready


ROOT, PROOF, A = ready.ROOT, ready.PROOF, ready.A
CELL = A + "authority_host_historical_cell_registration.rs"
LEDGER = A + "authority_host_historical_ledger_registration.rs"
SLOT = A + "authority_host_generation_initial.rs"
TRANSPORT = A + "authority_host_generation_initial_transport.rs"
LAUNCH = A + "production_initial_q24.rs"
PREPARE = A + "root_generation_initial_prepare.rs"
FEATURE = A + "circuit_feature_initial_root.rs"
REGISTRATIONS = {
    CELL: ("fn register_original_initial_cell(", "files.require_original_cell_baseline()?"),
    LEDGER: ("fn register_original_initial_ledger(", "files.require_empty_baseline()?"),
}

# The ordinary manifest already protects the complete original contexts and
# custody. These additional exact orders cover the handoff between phases.
PHASE_ORDERS = {
    TRANSPORT: [{
        "function": "fn serve_generation_initial(",
        "sequence": [
            "require_fresh_window(now, signed, witness)?",
            "slot.require_genesis()?", "original_broker_initial_publish(",
            "slot.require_genesis()?", "require_fresh_window(after_time, signed, witness)?",
            "encoded_response = Some(raw)",
        ],
    }],
    LAUNCH: [{
        "function": "fn assemble_original_initial_q24(",
        "sequence": [
            "load::open(deployment, &identity, now)", ".connect_ready_until(",
            "self.session_end,", ".await?;",
            "original.client.mode() != RootGenerationInitialModeV1::Reserve",
            "original.prepare_feature(authorities, selected, target)?", "prepared.publish(&signed)",
        ],
    }],
    PREPARE: [{
        "function": "fn prepare_original_initial(",
        "sequence": [
            "observer.require_original_unwritten()", "self.client.prepare_initial_current()?",
            "CellGenerationJournalV2::open_guarded(", "journal.prepared_checkpoint()",
            "observer.observe()", "!observed.is_genesis()",
            "PreparedAgentdGenerationInitialV1::from_parts(",
        ],
    }],
}


def actual_function(source, marker):
    return ready.route.function(source, marker)[0]


def verify_registration_phase(path, source):
    if path not in REGISTRATIONS:
        return
    function, baseline = REGISTRATIONS[path]
    code = actual_function(source, function)
    target = re.compile(ready.route.token_pattern("slot.require_target(true)?"))
    reads = list(target.finditer(code))
    baselines = list(re.finditer(ready.route.token_pattern(baseline), code))
    if len(reads) != 2 or len(baselines) != 2:
        raise PROOF.VerificationFailure("two strict fresh target and baseline reads required")
    if not reads[0].end() < baselines[0].start() < baselines[1].end() < reads[1].start():
        raise PROOF.VerificationFailure("the complete baseline must stay between fresh target reads")
    if re.search(ready.route.token_pattern("slot.require_genesis("), code):
        raise PROOF.VerificationFailure("unwritten enrollment cannot require or claim actual genesis")


class InitialBaselinePhaseSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.paths = (*REGISTRATIONS, SLOT, TRANSPORT, LAUNCH, PREPARE, FEATURE)
        cls.rows = {
            path: [row for row in manifest["protected_file"] if row["path"] == path]
            for path in cls.paths
        }
        cls.sources = {path: (ROOT / path).read_text() for path in cls.paths}

    def verify(self, path, source):
        self.assertTrue(self.rows[path], path)
        extra = [{
            "path": path, "required": [], "forbidden": [],
            "required_function_order": PHASE_ORDERS[path],
        }] if path in PHASE_ORDERS else []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": self.rows[path] + extra})
        verify_registration_phase(path, source)

    def mutate(self, path, function, marker, replacement, occurrence=0):
        source = self.sources[path]
        self.verify(path, source)
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        self.assertEqual(code.count(function), 1)
        begin = code.index(function)
        body = actual_function(source, function)
        matches = list(re.finditer(ready.route.token_pattern(marker), body))
        self.assertGreater(len(matches), occurrence, (path, function, marker))
        hit = matches[occurrence]
        start, end = begin + hit.start(), begin + hit.end()
        changed = source[:start] + replacement + source[end:]
        self.assertNotEqual(source, changed)
        with self.assertRaises(PROOF.VerificationFailure):
            self.verify(path, changed)

    def test_actual_registration_publication_and_daemon_phase_guards(self):
        for path, source in self.sources.items():
            with self.subTest(path=path):
                self.verify(path, source)

    def test_each_baseline_target_read_is_strict_fresh_not_genesis_or_recovery(self):
        for path, (function, _) in REGISTRATIONS.items():
            for occurrence in (0, 1):
                for replacement in (
                    "slot.require_genesis()?", "slot.require_target(/*fresh*/ false)?",
                    "/* slot.require_target(true)? */",
                ):
                    with self.subTest(path=path, occurrence=occurrence, replacement=replacement):
                        self.mutate(path, function, "slot.require_target(true)?",
                                    replacement, occurrence)

    def test_only_reserve_can_register_new_original_baselines(self):
        for path, (function, _) in REGISTRATIONS.items():
            with self.subTest(path=path):
                self.mutate(path, function,
                            "slot.mode != RootGenerationInitialModeV1::Reserve",
                            "slot.mode != RootGenerationInitialModeV1::Recover")
                self.mutate(path, function,
                            "slot.mode != RootGenerationInitialModeV1::Reserve",
                            "false")

    def test_both_actual_file_baselines_remain_inside_registration(self):
        for path, (function, baseline) in REGISTRATIONS.items():
            for occurrence in (0, 1):
                with self.subTest(path=path, occurrence=occurrence):
                    self.mutate(path, function, baseline, "/* physical read removed */", occurrence)

    def test_publish_requires_real_genesis_before_and_after_durable_publication(self):
        for occurrence in (0, 1):
            for replacement in ("slot.require_target(/*fresh*/ true)?", "/* genesis removed */"):
                with self.subTest(occurrence=occurrence, replacement=replacement):
                    self.mutate(TRANSPORT, "fn serve_generation_initial(",
                                "slot.require_genesis()?", replacement, occurrence)

    def test_empty_targets_cannot_be_promoted_to_genesis(self):
        for marker in ("self.target.observe()", "!observed.is_genesis()", "self.fence()?"):
            with self.subTest(marker=marker):
                self.mutate(SLOT, "fn require_genesis(", marker, "/* check removed */")
        self.mutate(SLOT, "fn require_target(", "self.target.require_original_unwritten()",
                    "self.target.require_original_unwritten_or_genesis()")

    def test_actual_main_requires_ready_ack_before_feature_preparation(self):
        self.mutate(LAUNCH, "fn assemble_original_initial_q24(", ".connect_ready_until(",
                    ".connect_until(")
        self.mutate(LAUNCH, "fn assemble_original_initial_q24(", ".await?;",
                    "; /* readiness result was not awaited */")
        self.mutate(LAUNCH, "fn assemble_original_initial_q24(",
                    "original.prepare_feature(authorities, selected, target)?",
                    "peer_supplied_feature")
        self.mutate(FEATURE, "fn prepare_feature(",
                    "self.prepare_original_initial(authorities, selected, target.files)?",
                    "peer_supplied_initial")

    def test_original_genesis_is_created_only_after_actual_current_preparation(self):
        for marker in (
            "self.client.prepare_initial_current()?", "CellGenerationJournalV2::open_guarded(",
            "journal.prepared_checkpoint()", "observer.observe()", "!observed.is_genesis()",
        ):
            with self.subTest(marker=marker):
                self.mutate(PREPARE, "fn prepare_original_initial(", marker, "/* check removed */")


if __name__ == "__main__":
    unittest.main()
