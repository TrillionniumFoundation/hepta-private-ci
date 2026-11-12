"""Negative source checks for the original C grant consumer and worker.

These checks use the repository's unchanged production verifier. They are not
native execution or proof of an ordinary A/B/C positive result.
"""

from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import verify_hepta_callers as PROOF

PREFIX = "codex-rs/hepta-agentd/src/"
CLIENT = PREFIX + "root_generation_current_grant.rs"
CURRENT_CLIENT = PREFIX + "root_generation_current_client.rs"
STORE = PREFIX + "neuron_generation_current_store.rs"
OWNER = PREFIX + "neuron_generation_current_root.rs"
PREPARED = PREFIX + "neuron_generation_update.rs"
AGGREGATE = PREFIX + "cell_q24_publication_successor_grant.rs"
WORKER = PREFIX + "circuit_q24_successor_worker.rs"
HANDOFF = PREFIX + "circuit_q24_successor.rs"
CONTINUATION = PREFIX + "production_post_a_continuation.rs"


class OriginalCGrantConsumerSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.paths = (
            CLIENT, CURRENT_CLIENT, STORE, OWNER, PREPARED, AGGREGATE,
            WORKER, HANDOFF, CONTINUATION,
        )
        cls.rows = [
            row for row in cls.manifest["protected_file"] if row["path"] in cls.paths
        ]
        cls.original = {path: (ROOT / path).read_text() for path in cls.paths}
        cls._check(cls.original)

    @classmethod
    def _check(cls, sources):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for path, source in sources.items():
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": cls.rows})

    def reject(self, path, marker, replacement="", occurrence=0, function=None):
        source = self.original[path]
        selected = function or {
            CLIENT: "fn issue_original_prepared_final_use(",
            STORE: "fn issue_original_prepared_final_use(",
            OWNER: "fn issue_original_prepared_final_use(",
            PREPARED: "fn issue_original_root_final_use(",
            AGGREGATE: "fn issue_original_successor_final_use(",
            WORKER: "fn finish_original_worker(",
        }.get(path)
        start = source.index(selected) if selected else 0
        for _ in range(occurrence + 1):
            index = source.find(marker, start)
            self.assertNotEqual(index, -1, (path, marker, occurrence))
            start = index + len(marker)
        mutated = dict(self.original)
        mutated[path] = source[:index] + replacement + source[start:]
        with self.assertRaises(PROOF.VerificationFailure):
            self._check(mutated)

    def test_client_requires_one_attempt_exact_prepared_and_original_connection(self):
        for marker in (
            "self.grant_attempted.swap(true, Ordering::AcqRel)",
            "self.version != PublicationVersion::DurableV2",
            "intent != &self.profile.intent",
            "let before = self.observe()?",
            "before.current != intent.previous || before.prepared.as_ref() != Some(intent)",
            "self.exchange_response(Command::IssueFinalUse {",
            "expected: head_digest(&before)?",
            "intent: intent.digest()?.to_string()",
            "response.head != before || response.successor.is_some()",
            "response.grant.ok_or_else(uncertain)?",
            "signed.grant.binding != intent.binding()?",
            "signed.grant.signing_bytes()",
            "self.connection.require_original_publication_session()?",
            "if result.is_err()",
            "self.fence()",
        ):
            with self.subTest(marker=marker):
                self.reject(CLIENT, marker)

    def test_client_cannot_reconnect_sign_or_extend_original_budget(self):
        for bypass in (
            "loop {}", "File::open(path);", "UnixStream::connect(path);",
            "connect(path);", "sleep(duration);",
            "Instant::now() + duration;", "SignedFinalUseGrant { value };",
        ):
            with self.subTest(bypass=bypass):
                self.reject(CLIENT, "let result = (|| {", "let result = (|| {\n" + bypass)

    def test_only_root_backend_and_actual_prepared_owner_can_request(self):
        for path, marker in (
            (STORE, "Store::Root(client) =>"),
            (STORE, "RootGenerationCurrentClient::issue_original_prepared_final_use(client, intent)"),
            (STORE, "_ => Err(invalid("),
            (OWNER, "CurrentStore::issue_original_prepared_final_use(&self.store, &prepared.intent)"),
            (PREPARED, "NeuronGenerationCurrentOwnerV1::issue_original_prepared_final_use("),
            (PREPARED, "&self.current,"),
            (PREPARED, "&self.prepared,"),
        ):
            with self.subTest(path=path, marker=marker):
                self.reject(path, marker)

    def test_original_lane_keeps_running_and_slot_checks_after_error_result(self):
        for marker in (
            "self.original.decision.require_new_work()?",
            "require_successor_admission(&state, &identity)?",
            "Arc::clone(&self.original.owners)",
            "self.original.decision.snapshot.clone()",
            "self.original.manifest.clone()",
            "with_original_publication(snapshot, manifest, move || {",
            "slot.require_installation_open()",
            "PreparedAgentdGenerationUpdateV1::issue_original_root_final_use(&self.prepared)",
            "Ok((self, issued?))",
        ):
            with self.subTest(marker=marker):
                self.reject(AGGREGATE, marker)
        # Both checks after the actual issuer call remain required, including Err.
        self.reject(AGGREGATE, "require_successor_admission(&state, &identity)?", occurrence=2)
        self.reject(AGGREGATE, "slot.require_installation_open()", occurrence=1)

    def test_worker_rechecks_original_proof_before_unpacking_issuer_result(self):
        for marker in (
            "let requested = tokio::select!",
            "self.slot.closed.cancelled()",
            "tokio::time::timeout(",
            "let issued = match requested",
            "OriginalSuccessorGrant::Provided(signed) => Ok((original.prepared, signed))",
            "OriginalSuccessorGrant::OriginalRoot =>",
            "OriginalCellQ24PreparedPublicationV1::issue_original_successor_final_use(",
            "Arc::clone(&state)",
            "self.context.identity().clone()",
            "Arc::clone(&self.slot)",
            "let (prepared, signed) = issued?",
            "publish_successor_current(",
        ):
            with self.subTest(marker=marker):
                self.reject(WORKER, marker)
        self.reject(WORKER, "require_current_successor_publication()", occurrence=0)
        self.reject(WORKER, "require_current_successor_publication()", occurrence=1)

    def test_sole_ordinary_continuation_uses_fixed_root_command(self):
        self.reject(
            CONTINUATION,
            "OriginalQ24PreparedSuccessorV1::publish_from_original_root(prepared)",
        )
        for forbidden in (
            "grants.request_grant(&binding);",
            "issue_registered_final_use(&binding);",
        ):
            with self.subTest(forbidden=forbidden):
                self.reject(
                    CONTINUATION,
                    "OriginalQ24PreparedSuccessorV1::publish_from_original_root(prepared)",
                    forbidden + "\nOriginalQ24PreparedSuccessorV1::publish_from_original_root(prepared)",
                )

    def test_other_current_replies_cannot_smuggle_a_grant(self):
        for marker in (
            "response.successor.is_some() || response.grant.is_some()",
            "response.head.current != self.profile.intent.target || response.grant.is_some()",
        ):
            with self.subTest(marker=marker):
                self.reject(CURRENT_CLIENT, marker, function=(
                    "fn exchange(" if marker.startswith("response.successor")
                    else "fn read_original_completed_successor("
                ))


if __name__ == "__main__":
    unittest.main()
