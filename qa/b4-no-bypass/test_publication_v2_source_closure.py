"""Explicit publication versions retain the whole durable cut and live checks.

These source mutations do not establish physical cold refusal, an independent
evaluation result, or a successful Root CURRENT publication.
"""
from dataclasses import replace
from pathlib import Path
import re
import tempfile
import tomllib
import unittest

import test_historical_task_read_source_closure as route

ROOT, PROOF, A = route.ROOT, route.PROOF, route.A
VERSION = A + "authority_host_publication_profile_versions.rs"
OWNER = A + "authority_host_generation_publication.rs"
ENROLL = A + "authority_host_generation_publication_enrollment.rs"
SERVER = A + "authority_host_generation_publication_transport.rs"
CLIENT = A + "root_generation_current_client.rs"
INPUTS = A + "root_generation_publication_inputs.rs"
PREPARE = A + "authority_host_original_publication_route.rs"
SESSION = A + "authority_host_generation_publication_session.rs"
POST_A = A + "authority_host_post_a_learning.rs"
REFUSAL = A + "authority_host_publication_refusal.rs"
CALLERS = {
    "root_publication_fixed_version": (OWNER, SERVER, CLIENT, INPUTS, REFUSAL),
    "root_publication_reserved_origin": (ENROLL,),
    "root_publication_reserved_version": (ENROLL, REFUSAL),
    "root_publication_current_live_profile": (ENROLL, OWNER),
}


def require_structure(path, source):
    if path == VERSION:
        for name, markers in (
            ("socket", ('Self::DurableV2 => "cell-generation-publication-v2.sock"',)),
            ("owner_prefix", ('Self::LegacyV1 => "generation-publication"', 'Self::DurableV2 => "generation-publication-v2"')),
            ("binding_domain", ('Self::LegacyV1 => b"hepta.root.generation-publication.profile.v1\\0"',
                                'Self::DurableV2 => b"hepta.root.generation-publication.profile.v2\\0"')),
        ):
            code, raw = route.function(source, "fn " + name + "(")
            for marker in markers:
                if raw.count(marker) != 1:
                    raise PROOF.VerificationFailure("each original version has one exact namespace")
                start = raw.index(marker)
                if code[start:start + len(marker)] != PROOF._strip_rust_non_code(marker):
                    raise PROOF.VerificationFailure("version namespace cannot come from a comment")
        body, _ = route.function(source, "fn require_live_profile(")
        if re.findall(r"\bexpected\s*\.\s*(\w+)\s*=", body) != ["writer", "identity", "binding"]:
            raise PROOF.VerificationFailure("only the two live admissions and their digest can change")
        if re.search(r"\boriginal\s*\.\s*\w+\s*=", body):
            raise PROOF.VerificationFailure("the original durable object cannot be overwritten")
        raw = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        for name in ("PublicationVersion", "DurablePublicationProfileV2"):
            start = raw.index(("enum " if name == "PublicationVersion" else "struct ") + name)
            begin, end = raw.index("{", start), PROOF._rust_item_end(raw, start)
            if end is None:
                raise PROOF.VerificationFailure("the exact version structure is required")
            fields = raw[begin + 1:end]
            if name == "PublicationVersion" and re.sub(r"\s+", "", fields) != "LegacyV1,DurableV2,":
                raise PROOF.VerificationFailure("no inferred or fallback version is permitted")
            if name == "DurablePublicationProfileV2" and re.search(r"\bpub\b", fields):
                raise PROOF.VerificationFailure("durable origin fields stay private")
    if path == ENROLL:
        body, _ = route.function(source, "fn enroll_armed_generation_publication(")
        begin, end = route.original.span(body, "|initial, proof| {")
        for marker in ("writer: proof", "neuron_generation_process_identity_digest_v1(&self.identity)",
                       "ReservedPublicationProfile::require_live_profile(",
                       "ReservedPublicationProfile::retain_original(profile.clone())?"):
            if not begin < body.index(marker) < end:
                raise PROOF.VerificationFailure("durable comparison must use the actual Root context")
        start, stop = route.original.span(body, "Some((store, record)) => {")
        recovered = body[start:stop]
        if "HostAuthorityFrontierStore::initialize" in recovered or "compare_and_set" in recovered:
            raise PROOF.VerificationFailure("reopen cannot initialize or rewrite retained provenance")


class PublicationV2SourceTests(unittest.TestCase):
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
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            def verify(value):
                target.write_text(value)
                PROOF._verify_protected_files(root, {"protected_file": rows})
                require_structure(path, value)
            verify(source)
            changed = change(source)
            self.assertNotEqual(source, changed)
            with self.assertRaises(PROOF.VerificationFailure):
                verify(changed)

    reject = route.HistoricalTaskReadSourceTests.reject
    check = route.HistoricalTaskReadSourceTests.check

    def test_actual_version_and_origin_callers_are_closed(self):
        for identifier, callers in CALLERS.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, callers)
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, self.sources, ())
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, replace(row, product_callers=()), self.sources, ())
                extra = dict(self.sources, **{A + "unregistered_publication_version.rs":
                             f"fn bypass() {{ {row.symbol}(); }}"})
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())

    def test_versions_and_namespaces_never_infer_or_downgrade(self):
        self.check(VERSION, "from_purpose", ("PURPOSE => Ok(Self::LegacyV1)",
            "PURPOSE_V2 => Ok(Self::DurableV2)", "_ => Err(io::Error::other("))
        for method, first, second in (
            ("schema", "Self::LegacyV1 => 1", "Self::DurableV2 => 2"),
            ("purpose", "Self::LegacyV1 => PURPOSE", "Self::DurableV2 => PURPOSE_V2"),
            ("socket", "Self::LegacyV1 => SOCKET", "Self::DurableV2 =>"),
            ("owner_prefix", "Self::LegacyV1 =>", "Self::DurableV2 =>"),
            ("binding_domain", "Self::LegacyV1 =>", "Self::DurableV2 =>"),
        ):
            self.check(VERSION, method, (first, second))
        self.mutate(VERSION, lambda s: s.replace("enum PublicationVersion {", "enum PublicationVersion { Automatic,", 1))
        self.mutate(VERSION, lambda s: s.replace('"cell-generation-publication-v2.sock"', '"cell-generation-publication-v1.sock"', 1))
        self.mutate(VERSION, lambda s: s.replace('"generation-publication-v2"', '"generation-publication"', 1))
        self.mutate(VERSION, lambda s: s.replace("hepta.root.generation-publication.profile.v2", "hepta.root.generation-publication.profile.v1", 1))

    def test_durable_origin_remains_canonical_and_private(self):
        self.check(VERSION, "retain_original", ("profile.digest()? != profile.binding", "schema_version: 2", "original: profile"))
        self.check(VERSION, "original_for_version", ("durable.schema_version == 2", "original.purpose != version.purpose()", "original.digest()? != original.binding"))
        self.mutate(VERSION, lambda s: s.replace("    original: PublicationProfile,", "    pub(crate) original: PublicationProfile,", 1))
        self.check(OWNER, "digest", ("value.binding.clear()", "PublicationVersion::from_purpose(&self.purpose)?.binding_domain()", "serde_json::to_vec(&value)"))

    def test_new_live_admission_cannot_substitute_any_other_durable_field(self):
        self.check(VERSION, "require_live_profile", ("live.digest()? != live.binding", "original.clone()", "PublicationVersion::LegacyV1 => {}",
            "digest.is_zero() || digest.to_string() != *text", "expected.writer = live.writer.clone()", "expected.identity = live.identity.clone()",
            "expected.binding = expected.digest()?", "if expected != *live"))
        for field in ("decision", "scope", "previous_files", "target_files", "artifacts", "consumer_trust", "intent"):
            self.mutate(VERSION, lambda s: s.replace("expected.binding = expected.digest()?;",
                f"expected.{field} = live.{field}.clone();\n                expected.binding = expected.digest()?;", 1))

    def test_actual_root_context_precedes_new_live_description(self):
        self.check(ENROLL, "enroll_armed_generation_publication", ("self.with_learning_profile(", "record.fenced", "version == PublicationVersion::LegacyV1 && original.writer != proof",
            "writer: proof", "neuron_generation_process_identity_digest_v1(&self.identity)", "ReservedPublicationProfile::require_live_profile(",
            "fence_record(&store, &profile_owner)?", "(store, record.profile)", "ReservedPublicationProfile::retain_original(profile.clone())?"))
        self.mutate(ENROLL, lambda s: s.replace("Some((store, record)) => {", "Some((store, record)) => { HostAuthorityFrontierStore::initialize(root);", 1))
        self.check(OWNER, "require_profile", ("profile: self.reserved.clone()", "fenced: false", "self.profile.digest()? != self.profile.binding", "ReservedPublicationProfile::require_live_profile(&self.reserved, &self.profile)?"))

    def test_every_wire_exchange_keeps_actual_live_authority_and_fixed_version(self):
        self.check(SERVER, "serve_generation_publication_with_end", ("self.with_learning_profile(", "slot.profile.writer != proof", "slot.profile.identity",
            "request.schema != version.schema()", "request.purpose != version.purpose()", "request.request_id != sequence"))
        self.check(CLIENT, "from_original_stream", ("PublicationVersion::from_purpose(&bootstrap.purpose)?", "response.schema != version.schema()",
            "response.purpose != version.purpose()", "profile.writer != bootstrap.writer", "profile.digest()? != profile.binding"))
        self.check(CLIENT, "exchange", ("response.schema != self.version.schema()", "response.purpose != self.version.purpose()", "response.profile != self.profile"))

    def test_only_original_sealed_route_selects_v2(self):
        self.check(INPUTS, "connect_until", ("PublicationVersion::from_purpose(&bundle.purpose)?", ".join(version.socket())", "bundle.root != original.root", "bundle.consumer != original.consumer"))
        self.check(PREPARE, "prepare_original_publication_route", ("purpose: version.purpose()", ".join(version.socket())", "let runtime = PublicationRuntime", "version,"))
        self.reject(SESSION, "enable_generation_publication", "PublicationVersion::LegacyV1")
        self.reject(POST_A, "prepare_original_installation", "PublicationVersion::DurableV2")


if __name__ == "__main__":
    unittest.main()
