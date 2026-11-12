"""Only the same actual Root can rebuild CURRENT's historical A predecessor.

These source counterexamples are not a Root/native positive or recovery of C's
own execution. The ordinary Recover product caller remains separately closed.
"""
from dataclasses import replace
from pathlib import Path
import re
import tempfile
import tomllib
import unittest

import test_historical_task_read_source_closure as route

ROOT, PROOF, A = route.ROOT, route.PROOF, route.A
RECOVER = A + "cell_q24_publication_historical_recovery.rs"
DATA = A + "cell_q24_publication_driver.rs"
CURRENT = A + "root_generation_current_history.rs"
PUBLICATION = A + "root_generation_publication_connection.rs"
CONNECTION = A + "root_historical_task_connection.rs"
RECEIPT = A + "root_historical_task_read_client.rs"
STORE = A + "neuron_generation_current_store.rs"
OWNER = A + "neuron_generation_current_root.rs"
CALLERS = {
    "root_current_historical_identity": (CONNECTION,),
    "root_current_historical_connection": (RECEIPT,),
    "root_current_historical_receipt_connection": (CURRENT,),
    "root_current_historical_client_match": (STORE, A + "root_generation_current_client.rs"),
    "root_current_historical_backend": (OWNER,),
    "root_current_historical_owner": (RECOVER, A + "neuron_generation_update_live.rs", A + "circuit_feature_historical_source.rs"),
    "q24_current_historical_recover": (A + "production_post_a_continuation.rs",),
}


def require_structure(path, source):
    if path == RECOVER:
        body, _ = route.function(source, "fn recover_feature_from_historical_a(")
        start, end = route.original.span(body, "move || {")
        if not re.match(r"\s*\)\s*\.await\?;", body[end:]):
            raise PROOF.VerificationFailure("original owner postchecks must return successfully")
        for marker in ("revalidate(&self.driver, &mut selected)?",
                       "crate::recover_agentd_generation_update_v1(",
                       ".into_circuit_feature_task(definition, source, previous)"):
            position = body.index(marker)
            if (not start < position < end
                    or body[:position].count("{") - body[:position].count("}") != 2):
                raise PROOF.VerificationFailure("recovery escaped the actual original owner lane")
        for marker, depths in (
            ("NeuronGenerationCurrentOwnerV1::require_original_root_historical_receipt(", (2, 1, 1)),
            ("PublishedCircuitFeatureCompletionV1::read_original_historical_completion(", (2, 1)),
        ):
            actual = tuple(body[:m.start()].count("{") - body[:m.start()].count("}")
                           for m in re.finditer(re.escape(marker), body))
            if actual != depths:
                raise PROOF.VerificationFailure("same-Root and A checks must surround returned owners")
    if path == STORE:
        body, _ = route.function(source, "fn require_original_root_historical_receipt(")
        if re.findall(r"\bStore\s*::\s*(\w+)", body) != ["Root"]:
            raise PROOF.VerificationFailure("only the actual Root publication backend can recover")
    if path == DATA:
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        start = code.index("pub(crate) struct OriginalCellQ24HistoricalFeatureRecoveryV1 {")
        end = PROOF._rust_item_end(code, start)
        body = code[start:end + 1]
        if re.search(r"\b(?:AgentdIdentity|CircuitTaskSourceReadbackV1|CellDecisionReceiptV1|bool)\b", body):
            raise PROOF.VerificationFailure("raw old identities or facts cannot replace the Root receipt")
    for candidate, name in (
        (PUBLICATION, "require_original_reader_identity"),
        (CONNECTION, "require_same_original_publication"),
        (RECEIPT, "require_original_publication_connection"),
        (CURRENT, "require_original_historical_receipt"),
        (STORE, "require_original_root_historical_receipt"),
        (OWNER, "require_original_root_historical_receipt"),
    ):
        if path == candidate:
            body, _ = route.function(source, "fn " + name + "(")
            if not re.search(r"->\s*Result\s*<\s*\(\s*\)\s*,\s*AgentdError\s*>\s*$",
                             body[:body.index("{")]):
                raise PROOF.VerificationFailure("identity predicates cannot return a new capability")


class CurrentHistoricalARecoverySourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}
        paths = {cls.boundaries[key].definition_path for key in CALLERS}
        paths.update(path for values in CALLERS.values() for path in values)
        cls.sources = {path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
            (ROOT / path).read_text())) for path in paths}

    def mutate(self, path, change):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        source = (ROOT / path).read_text()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / path
            target.parent.mkdir(parents=True)
            def verify(text):
                target.write_text(text)
                PROOF._verify_protected_files(root, {"protected_file": rows})
                require_structure(path, text)
            verify(source)
            changed = change(source)
            self.assertNotEqual(source, changed)
            with self.assertRaises(PROOF.VerificationFailure):
                verify(changed)

    reject = route.HistoricalTaskReadSourceTests.reject
    check = route.HistoricalTaskReadSourceTests.check

    def test_actual_callers_and_unconnected_recovery_remain_closed(self):
        for identifier, callers in CALLERS.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, callers)
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, self.sources, ())
                for omitted in callers:
                    missing = tuple(p for p in callers if p != omitted)
                    with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                        PROOF._verify_boundary(ROOT, replace(row, product_callers=missing), self.sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                rogue = dict(self.sources)
                rogue[A + "unregistered_historical_current.rs"] = (
                    f"fn bypass(actual: &{row.receiver_type}) {{ actual.{method}(); }}")
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, rogue, ())

    def test_equal_public_data_cannot_replace_the_actual_shared_verifier(self):
        for occurrence in (0, 1):
            self.reject(PUBLICATION, "require_original_reader_identity",
                        "self.require_original_publication_session()", occurrence)
        self.check(PUBLICATION, "require_original_reader_identity", (
            "self.require_original_publication_session()?", "!Arc::ptr_eq(&self.verifier, verifier)",
            "&self.identity != identity", "serde_json::to_vec(&self.original)? != serde_json::to_vec(original)?",
            "self.authority.grant_digest != authority.grant_digest", "self.require_original_publication_session()"))
        self.mutate(PUBLICATION, lambda s: s.replace("-> Result<(), AgentdError> {\n        self.require_original_publication_session()?;\n        if !Arc::ptr_eq(&self.verifier, verifier)",
            "-> Result<AgentdRootAuthoritySession, AgentdError> {\n        self.require_original_publication_session()?;\n        if !Arc::ptr_eq(&self.verifier, verifier)", 1))

    def test_both_original_connections_and_failed_receipt_are_rechecked(self):
        for occurrence in (0, 1):
            self.reject(CONNECTION, "require_same_original_publication",
                        "self.require_original_session()", occurrence)
        self.check(CONNECTION, "require_same_original_publication", (
            "self.require_original_session()?", "RootGenerationPublicationConnectionV1::require_original_reader_identity(",
            "publication,", "&self.original,", "&self.identity,", "&self.authority,", "&self.verifier,",
            "self.require_original_session()"))
        self.check(RECEIPT, "require_original_publication_connection", (
            "self.client.fenced.load(Ordering::Acquire)", "RootHistoricalTaskReadConnectionV1::require_same_original_publication(",
            "&self.client.connection,", "publication,", "if result.is_err()", "self.client.fence()"))

    def test_current_observation_and_iteration_must_match_the_same_receipt(self):
        for occurrence in (0, 1):
            self.reject(CURRENT, "require_original_historical_receipt",
                        "OriginalHistoricalTaskReadReceiptV1::require_original_publication_connection(", occurrence)
        self.check(CURRENT, "require_original_historical_receipt", (
            "self.observe()?", "original.initial_snapshot()", "self.profile.initial != initial.head_digest.to_string()",
            "self.profile.learning_operation != initial.request.operation_id.as_str()", "if result.is_err()", "self.fence()"))
        def add_wrong_backend(source):
            _, raw = route.function(source, "fn require_original_root_historical_receipt(")
            return source.replace(raw, raw.replace("Store::Root(client) =>", "Store::Host(_) => Ok(()),\n            Store::Root(client) =>", 1), 1)
        self.mutate(STORE, add_wrong_backend)
        self.check(OWNER, "require_original_root_historical_receipt", (
            "CurrentStore::require_original_root_historical_receipt(&self.store, original)",))

    def test_original_decision_and_full_target_precede_the_recovery_lane(self):
        self.check(RECOVER, "recover_feature_from_historical_a", (
            "original.require_current().await?", "original.decision.require_root_publication()?",
            "validation::feature_target(", "&recovery.target,", "&recovery.definition,", "&recovery.source,", "&recovery.model,",
            "initial.request != original.decision.snapshot.request", "initial.owners != original.decision.snapshot.owners",
            ".with_original_publication(snapshot, manifest, move || {", "revalidate(&self.driver, &mut selected)?",
            "crate::recover_agentd_generation_update_v1(", "operation_id: self.driver.original.decision.operation.to_string()",
            "intent_digest,", ".into_circuit_feature_task(definition, source, previous)", "task.require_bundle(&bundle)?"))

    def test_physical_a_and_current_checks_surround_returned_owner_postchecks(self):
        for occurrence in range(3):
            self.reject(RECOVER, "recover_feature_from_historical_a",
                        "NeuronGenerationCurrentOwnerV1::require_original_root_historical_receipt(", occurrence)
        for occurrence in range(2):
            self.reject(RECOVER, "recover_feature_from_historical_a",
                        "PublishedCircuitFeatureCompletionV1::read_original_historical_completion(", occurrence)
        self.mutate(RECOVER, lambda s: s.replace("revalidate(&self.driver, &mut selected)?;",
            "if false { revalidate(&self.driver, &mut selected)?; }", 1))

    def test_recovery_cannot_reopen_old_writers_or_replace_opaque_a(self):
        for extra in ("File::open(path);", "DurableCircuitTaskSourceV1::recover(args);",
                      "CellOwnerJournalV1::open(args);", "claim_final_use(args);", "owner.publish(args);"):
            self.mutate(RECOVER, lambda s: s + "\nfn bypass() { " + extra + " }\n")
        self.mutate(DATA, lambda s: s.replace("pub(crate) struct OriginalCellQ24HistoricalFeatureRecoveryV1 {",
            "pub(crate) struct OriginalCellQ24HistoricalFeatureRecoveryV1 {\n    original_identity: AgentdIdentity,", 1))
        self.mutate(DATA, lambda s: s.replace("Arc<crate::root_historical_task_read_client::OriginalHistoricalTaskReadReceiptV1>",
            "crate::CircuitTaskSourcePublicationV1", 1))


if __name__ == "__main__":
    unittest.main()
