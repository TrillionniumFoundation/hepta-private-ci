"""Keep actual late publication data separate from the retained Root authority.

These mutations verify source custody and ordering. They are not a native
publication, independent-B result, or daemon-plus-Root recovery qualification.
"""
from dataclasses import replace
from pathlib import Path
import re
import tempfile
import tomllib
import unittest

import test_historical_task_read_source_closure as route
import test_post_a_installation_source_closure as installation

ROOT, PROOF, A = route.ROOT, route.PROOF, route.A
FILES = A + "authority_host_post_a_publication.rs"
MATERIAL = A + "authority_host_post_a_publication_material.rs"
SERVE = A + "authority_host_post_a_publication_worker.rs"
WORKER = A + "authority_host_post_a_worker.rs"
PLAN = A + "authority_host_post_a_learning.rs"
PROVIDER = A + "authority_host_post_a_provider.rs"
CLI = route.CLI
CALLERS = {
    "root_post_a_publication_files": (PLAN,),
    "root_post_a_publication_attach": (PLAN,),
    "root_post_a_publication_register": (SERVE,),
    "root_post_a_publication_serve": (WORKER,),
    "root_post_a_worker_session_end": (PROVIDER,),
}


def require_structure(path, source, rows):
    if path == CLI:
        route.require_structure(path, source, rows)
    if path == WORKER:
        installation.require_structure(path, source)
    if path == FILES:
        body, raw = route.function(source, "fn retain_original_publication(")
        literal = 'data.purpose != "runtime.learning.post-a-publication-deployment.v2"'
        if raw.count(literal) != 1:
            raise PROOF.VerificationFailure("the actual Root plan purpose must remain exact")
        start = raw.index(literal)
        if body[start:start + len(literal)] != PROOF._strip_rust_non_code(literal):
            raise PROOF.VerificationFailure("the actual Root plan purpose cannot live in a comment")
    for name in {
        FILES: ("OriginalPostAPublicationFiles", "OriginalPostAPublicationDeployment"),
        MATERIAL: ("RetainedMaterial", "MaterialObservation"),
    }.get(path, ()):
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        start = code.index("struct " + name)
        begin = code.index("{", start)
        end = PROOF._rust_item_end(code, start)
        if end is None or re.search(r"\bpub\b", code[begin:end]):
            raise PROOF.VerificationFailure("actual original custody must remain private")


class PostAPublicationSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}
        paths = {cls.boundaries[key].definition_path for key in CALLERS}
        paths.update(path for values in CALLERS.values() for path in values)
        cls.sources = {path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
            (ROOT / path).read_text())) for path in paths}

    def mutate(self, path, change):
        source = (ROOT / path).read_text()
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            def verify(text):
                target.write_text(text)
                PROOF._verify_protected_files(root, {"protected_file": rows})
                require_structure(path, text, rows)
            verify(source)
            changed = change(source)
            self.assertNotEqual(source, changed)
            with self.assertRaises(PROOF.VerificationFailure):
                verify(changed)

    reject = route.HistoricalTaskReadSourceTests.reject
    check = route.HistoricalTaskReadSourceTests.check

    def test_actual_closed_callers_reject_omission_and_new_entry(self):
        for identifier, callers in CALLERS.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, callers)
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, self.sources, ())
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, replace(row, product_callers=()), self.sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                bypass = (f"fn bypass(real: &{row.receiver_type}) {{ real.{method}(); }}"
                          if row.receiver_type else f"fn bypass() {{ {method}(); }}")
                sources = dict(self.sources)
                sources[A + "unregistered_publication.rs"] = bypass
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, sources, ())

    def test_root_plan_keeps_original_recipient_and_all_file_inputs(self):
        self.check(FILES, "retain_original_publication", (
            "original_root()?", "MetadataFile::open_metadata(path)?", "data.schema != 2",
            "data.initial != initial.head_digest.to_string()", "!initial.receipts.is_empty()",
            "data.inputs.issuer_keys.is_empty()", "DirectoryPin::capture_root(",
            "RootAuthorityDirectory::open(", "OriginalFile::open_original(&data.inputs.previous_journal)?",
            "OriginalFile::open_original(&data.inputs.previous_witness)?",
            "OriginalFile::open_original(&data.inputs.target_journal)?",
            "OriginalFile::open_original(&data.inputs.target_witness)?",
            "OriginalFile::open_original(&data.inputs.withdrawal_file)?",
            "material.require_distinct(file)?", "held.require_original_files()?"))
        self.mutate(FILES, lambda source: source.replace(
            '"runtime.learning.post-a-publication-deployment.v2"',
            '"untrusted" /* "runtime.learning.post-a-publication-deployment.v2" */', 1))

    def test_route_uses_original_root_uid_phase_initial_and_end(self):
        self.check(FILES, "attach_original_route", (
            "original_root()?", "self.require_original_files()?",
            "self.initial != initial.head_digest.to_string()", "self.uid != capability.consumer_uid",
            "capability.original_end.is_none()", "std::process::id() != capability.root_pid",
            "capability.phase.load(Ordering::Acquire) != PREPARED", "capability.operation_end()?"))
        self.check(WORKER, "original_session_end", (
            "self.gate.session_end.get()", "self.gate.require_original(end)?",
            "request_end > end", "self.gate.phase.load(Ordering::Acquire) != SERVING"))

    def test_material_custody_and_distinct_read_description_cannot_be_substituted(self):
        self.check(MATERIAL, "open_original", (
            "uid == 0", "gid == 0", "(expected.uid, expected.gid, expected.mode) != (uid, gid, 0o100600)",
            "expected.device == 0", "expected.inode == 0", "OriginalFile::open_original(&expected.path)?"))
        self.check(MATERIAL, "observe_ready", (
            "self.require_original()?", "self.original.original_descriptor()?", "OpenOptions::new().read(true)",
            "libc::O_CLOEXEC | libc::O_NONBLOCK", "file.try_lock_shared()",
            "Err(TryLockError::WouldBlock) => return Ok(None)", "metadata.len() == 0",
            "metadata.len() > 65_536", "file.read_exact_at(&mut bytes", "observed.require_unchanged()?"))

    def test_locked_material_checks_both_bytes_and_file_stamps_twice(self):
        self.check(MATERIAL, "require_unchanged", ("for _ in 0..2", "self.file.read_exact_at(&mut bytes",
                                                   "bytes != self.bytes"))
        for occurrence in (0, 1):
            self.reject(MATERIAL, "require_unchanged", "self.held.require_descriptor(&self.file)", occurrence)
            self.reject(MATERIAL, "require_unchanged", "self.file.metadata()?", occurrence)
            self.reject(MATERIAL, "require_unchanged", "!= self.stamp", occurrence)

    def test_registration_cannot_skip_canonical_data_or_real_root_authority(self):
        self.check(FILES, "wait_and_register_original_material", (
            "self.capability.operation_end()?", "self.capability.phase.load(Ordering::Acquire)",
            "self.files.material.observe_ready()?", "serde_json::from_slice(observed.bytes())",
            "serde_json::to_vec(&material)", "!= observed.bytes()", "OriginalInputs::enrollment_inputs(",
            "RootGenerationPublicationEnrollmentCapabilityV1::register(self.capability, inputs)?"))
        for occurrence in (0, 1, 2):
            self.reject(FILES, "wait_and_register_original_material", "self.files.require_original_files()", occurrence)
            self.reject(FILES, "wait_and_register_original_material",
                        "stopping.load(Ordering::Acquire) || std::time::Instant::now() >= end", occurrence)
        for occurrence in (0, 1):
            self.reject(FILES, "wait_and_register_original_material", "observed.require_unchanged()", occurrence)
            self.reject(FILES, "wait_and_register_original_material", "file.require_original_file()", occurrence)

    def test_third_handoff_must_match_all_original_parts_and_precede_ack(self):
        self.check(WORKER, "run_installation", (
            "publication.is_some() != publication_offer.is_some()",
            "publication.is_some() != publication_deployment.is_some()",
            "publication.is_some() != inputs.publication_handoff.is_some()",
            "send_root_generation_publication_handoff(", "publication::serve_original_material("))
        self.check(SERVE, "serve_original_material", (
            "scope.spawn(", "OriginalPostAPublicationDeployment::wait_and_register_original_material(",
            "if result.is_err()", "gate.phase.store(CLOSED, Ordering::Release)",
            "let result = original()", "stopping.store(true, Ordering::Release)", "worker.join()",
            "result.and(registered)"))

    def test_ordinary_cli_keeps_late_and_legacy_inputs_separate(self):
        self.check(CLI, "main", (
            "post_a_publication_deployment.is_some() && post_a_deployment.is_none()",
            "post_a_publication_deployment.is_some() != publication_handoff.is_some()",
            "let eager_publication_handoff = if post_a_deployment.is_some()",
            "post_a_publication_deployment.as_deref()"))

    def test_original_holders_cannot_become_raw_wire_fields(self):
        for path, field in ((FILES, "    capability:"), (FILES, "    inputs: OriginalInputs"),
                            (MATERIAL, "    original:"), (MATERIAL, "    held:")):
            with self.subTest(path=path, field=field):
                self.mutate(path, lambda source: source.replace(field, field.replace("    ", "    pub(crate) "), 1))


if __name__ == "__main__":
    unittest.main()
