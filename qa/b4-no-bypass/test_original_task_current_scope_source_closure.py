"""Keep Initial task checks within the original journal borrow and live postcheck."""

import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
AGENT = "codex-rs/hepta-agentd/src/"
CURRENT = AGENT + "circuit_feature_current.rs"
CONTROL = AGENT + "circuit_feature_current_control.rs"
ORIGINAL = "impl<W: AnchorWitnessStore + Send> OriginalVersion for CellGenerationJournalV2<W> {"
PUBLISHED = "impl PublishedCircuitFeatureTaskV1 {"
SPEC = importlib.util.spec_from_file_location("original_task_current_scope_proof", ROOT / "scripts/verify_hepta_callers.py")
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)


class OriginalTaskCurrentScopeSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        self.rows = [row for row in manifest["protected_file"] if row["path"] in (CURRENT, CONTROL)]
        self.assertEqual(len(self.rows), 4)
        self.original = {path: (ROOT / path).read_text() for path in (CURRENT, CONTROL)}
        for path, text in self.original.items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        self.verify()

    def code(self, source):
        return PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))

    def compact(self, source):
        return re.sub(r"\s+", "", source)

    def item(self, source, marker, within=None):
        code = self.code(source)
        lower, upper = (0, len(code)) if within is None else within
        self.assertEqual(code[lower:upper].count(marker), 1, marker)
        start = code.index(marker, lower, upper)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        self.assertLess(end, upper)
        return start, end + 1, code[start:end + 1]

    def method(self, source, owner, name):
        lower, upper, _ = self.item(source, owner)
        return self.item(source, "fn " + name + "(", (lower, upper))

    def direct(self, body, marker, count=1):
        positions = [match.start() for match in re.finditer(re.escape(marker), body)]
        self.assertEqual(len(positions), count, marker)
        for position in positions:
            prefix = body[:position]
            self.assertEqual(prefix.count("{") - prefix.count("}"), 1, marker)

    def verify(self):
        PROOF._verify_protected_files(self.root, {"protected_file": self.rows})
        source = (self.root / CURRENT).read_text()
        code = self.code(source)
        self.assertNotRegex(code, r"\bpub(?:\s*\([^)]*\))?\s+trait\s+OriginalVersion\b")
        self.assertEqual(code.count("trait OriginalVersion: Send {"), 1)
        implementations = re.findall(r"\bimpl[^;{}]*\bOriginalVersion\s+for[^{}]*\{", code)
        self.assertEqual([self.compact(item) for item in implementations], [self.compact(ORIGINAL)])
        self.assertEqual(code.count("fn require_original_task("), 2, "one private trait declaration and its original journal implementation")
        self.assertEqual(code.count(".require_original_task("), 2, "only the Initial current and active branches use this scope")
        _, _, body = self.method(source, ORIGINAL, "require_original_task")
        signature = "fnrequire_original_task(&self,expected:&CellGenerationOwnerBindingV1,active:bool,)->Result<(),AgentdError>{"
        self.assertTrue(self.compact(body).startswith(signature))
        _, _, local = self.item(body, "let result = (|| {")
        self.direct(body, "let result = (|| {")
        self.direct(local, "let observed = CellGenerationJournalV2::observe_generation(self).map_err(invalid)?;")
        self.direct(local, "if self.owner_binding() != Some(expected)")
        self.direct(local, "if observed.snapshot().revision != 0")
        self.direct(local, "if active && CellGenerationJournalV2::is_drained(self).map_err(invalid)?")
        self.direct(local, "Ok(())")
        self.assertEqual(local.count("return Err("), 3)
        self.assertEqual(body.count("Ok(())"), 1)
        self.assertNotIn("return Ok(", body)
        post = "let post = CellGenerationJournalV2::require_current(self).map_err(invalid);"
        self.direct(body, post)
        self.direct(body, "post?;")
        self.direct(body, "\n        result\n")
        tail = "})();" + post + "post?;result}"
        self.assertTrue(self.compact(body).endswith(self.compact(tail)), "local failure cannot return before the same journal's live postcheck")
        for method, active in (("require_current", "false"), ("require_active", "true")):
            _, _, entry = self.method(source, PUBLISHED, method)
            _, _, branch = self.item(entry, "if matches!(&self.0.publication, Publication::Initial(_))")
            self.direct(entry, "if matches!(&self.0.publication, Publication::Initial(_))")
            expected = (
                "ifmatches!(&self.0.publication,Publication::Initial(_)){"
                "returnself.0.original.lock().map_err(invalid)?"
                ".require_original_task(self.0.publication.target()," + active + ");}"
            )
            self.assertEqual(self.compact(branch), expected, "the original mutex guard and immutable target cover the entire call")
            if method == "require_current":
                self.direct(entry, "self.0\n            .current\n            .check_current", 2)
                self.direct(entry, "self.0.original.lock().map_err(invalid)?.require_current()?;")
            else:
                self.direct(entry, "self.require_current()?;")
                self.direct(entry, "if self.0.original.lock().map_err(invalid)?.is_drained()?")
                self.direct(entry, "\n        self.require_current()\n")
        control = (self.root / CONTROL).read_text()
        _, _, run = self.method(control, PUBLISHED, "require_original_initial_run")
        self.direct(run, "if !matches!(&self.0.publication, Publication::Initial(_))")
        self.direct(run, "\n        self.require_active()\n")
        self.assertEqual(run.count("self.require_active()"), 1)
        self.assertNotIn("Ok(())", run)
        self.assertTrue(self.compact(run).endswith("self.require_active()}"))

    def reject(self, path, changed):
        self.assertNotEqual(changed, self.original[path])
        target = self.root / path
        try:
            target.write_text(changed)
            with self.assertRaises((PROOF.VerificationFailure, AssertionError, ValueError)):
                self.verify()
        finally:
            target.write_text(self.original[path])

    def reject_in(self, path, owner, name, old, new):
        source = self.original[path]
        start, end, _ = self.method(source, owner, name)
        body = source[start:end]
        self.assertEqual(body.count(old), 1, old)
        self.reject(path, source[:start] + body.replace(old, new) + source[end:])

    def test_original_observation_binding_and_every_empty_work_condition_remain(self):
        for condition in (
            "self.owner_binding() != Some(expected)",
            "observed.snapshot().revision != 0",
            "observed.pending_request_digest().is_some()",
            "observed.pending_output().is_some()",
            "!observed.snapshot().prefix.is_empty()",
            "observed.snapshot().stopped",
        ):
            with self.subTest(condition=condition):
                self.reject_in(CURRENT, ORIGINAL, "require_original_task", condition, "false")
        self.reject_in(CURRENT, ORIGINAL, "require_original_task", "CellGenerationJournalV2::observe_generation(self)", "cached_observation(self)")
        self.reject_in(CURRENT, ORIGINAL, "require_original_task", "if active && CellGenerationJournalV2::is_drained(self)", "if false && CellGenerationJournalV2::is_drained(self)")
        self.reject_in(CURRENT, ORIGINAL, "require_original_task", "let observed = CellGenerationJournalV2::observe_generation(self).map_err(invalid)?;", "if false { let observed = CellGenerationJournalV2::observe_generation(self).map_err(invalid)?; }")

    def test_local_error_cannot_skip_or_replace_original_live_postcheck(self):
        self.reject_in(CURRENT, ORIGINAL, "require_original_task", "})();", "})()?;")
        self.reject_in(CURRENT, ORIGINAL, "require_original_task", "let post = CellGenerationJournalV2::require_current(self).map_err(invalid);", "let post = Ok(());")
        self.reject_in(CURRENT, ORIGINAL, "require_original_task", "post?;", "let _ = post;")
        self.reject_in(CURRENT, ORIGINAL, "require_original_task", "post?;", "if true { post?; }")
        self.reject_in(CURRENT, ORIGINAL, "require_original_task", "\n        result\n", "\n        Ok(())\n")

    def test_initial_current_and_active_keep_original_mutex_target_and_flag(self):
        for method, flag in (("require_current", "false"), ("require_active", "true")):
            with self.subTest(method=method):
                self.reject_in(CURRENT, PUBLISHED, method, ".require_original_task(self.0.publication.target(), " + flag + ");", ".require_original_task(self.0.publication.target(), " + ("true" if flag == "false" else "false") + ");")
                self.reject_in(CURRENT, PUBLISHED, method, ".require_original_task(self.0.publication.target(), " + flag + ");", ".require_original_task(&replacement_binding, " + flag + ");")
                self.reject_in(CURRENT, PUBLISHED, method, "                .lock()", "                .try_lock()")
                self.reject_in(CURRENT, PUBLISHED, method, "if matches!(&self.0.publication, Publication::Initial(_))", "if !matches!(&self.0.publication, Publication::Initial(_))")
        extra = "\nfn replacement_scope(original: &dyn OriginalVersion, target: &CellGenerationOwnerBindingV1) { let _ = original.require_original_task(target, false); }\n"
        self.reject(CURRENT, self.original[CURRENT] + extra)

    def test_private_journal_impl_and_run_identity_must_reach_active_scope(self):
        source = self.original[CURRENT]
        self.reject(CURRENT, source.replace("trait OriginalVersion: Send {", "pub(in crate) trait OriginalVersion: Send {", 1))
        self.reject(CURRENT, source.replace(ORIGINAL, "impl<W: AnchorWitnessStore + Send> OriginalVersion for ReplacementJournal<W> {", 1))
        self.reject_in(CONTROL, PUBLISHED, "require_original_initial_run", "!matches!(&self.0.publication, Publication::Initial(_))", "false")
        self.reject_in(CONTROL, PUBLISHED, "require_original_initial_run", "&self.source().scope.run_id != run_id", "false")
        self.reject_in(CONTROL, PUBLISHED, "require_original_initial_run", "self.require_active()", "Ok(())")


if __name__ == "__main__":
    unittest.main()
