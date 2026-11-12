"""Retain one actual Root installation and its original absolute deadlines.

These are source mutations of the real serving and channel methods. They do
not prove the unwired worker is an ordinary caller or a completed learning run.
"""
from dataclasses import replace
from pathlib import Path
import re
import tempfile
import tomllib
import unittest

import test_historical_task_read_source_closure as route

ROOT, PROOF, A = route.ROOT, route.PROOF, route.A
C = "codex-rs/hepta-contracts/src/"
OWNER, PEER = C + "authority_host_channel.rs", C + "authority_host_peer.rs"
L, M, P = (A + "authority_host_" + name + ".rs" for name in (
    "learning_checkpoint", "q24_model_transport", "generation_publication_transport"))
LS, MS, PS = (A + "authority_host_" + name + ".rs" for name in (
    "learning_session", "q24_model_session", "generation_publication_runtime"))
WORKER = A + "authority_host_post_a_worker.rs"
CALLERS = {
    "root_original_owner_absolute_end": (PEER,),
    "root_original_peer_absolute_end": (L, M, P),
    "root_post_a_bound_learning": (A + "authority_host_session.rs", WORKER),
    "root_post_a_installation_prepare": (),
    "root_post_a_installation_submit": (),
    "root_post_a_installation_serve": (),
    "root_post_a_installation_run": (),
}
for stem, caller in (("learning_checkpoint", LS), ("q24_model_factory", MS),
                     ("generation_publication", PS)):
    CALLERS["root_late_" + stem + "_until"] = (caller,)
    CALLERS["root_late_" + stem + "_core"] = ()
for stem, caller in (("learning", WORKER), ("q24_model", LS), ("generation_publication", LS)):
    CALLERS["root_late_" + stem + "_listener_until"] = (caller,)


def at_depth(code, marker, depth):
    matches = list(re.finditer(route.token_pattern(marker), code))
    if not matches:
        raise PROOF.VerificationFailure("actual required operation missing")
    for match in matches:
        prefix = code[:match.start()]
        if prefix.count("{") - prefix.count("}") != depth:
            raise PROOF.VerificationFailure("required operation hidden in nested code")


def require_structure(path, source):
    if path in (L, M, P):
        stem = {L: "learning_checkpoint", M: "q24_model_factory", P: "generation_publication"}[path]
        body, _ = route.function(source, "fn serve_" + stem + "_with_end(")
        start, end = route.original.span(body, "if let Some(end) = original_end")
        at_depth(body[start:end], "HostAuthorityPeerChannel::limit_original_end(&mut channel, end)", 1)
    if path in (LS, MS, PS):
        body, _ = route.function(source, "fn serve_optional_until(")
        at_depth(body, "owner_alive(owner, end)?", 1)
        for marker in ("Instant::now() +", "Duration::from_millis(", "unwrap_or", "Some(Instant::now()"):
            if marker in body:
                raise PROOF.VerificationFailure("late serving cannot renew the original end")
    if path == WORKER:
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        for name in ("PostALearningWorker", "PostALearningSubmitter", "Submission", "OriginalInputs"):
            start = code.index("struct " + name + " {")
            end = PROOF._rust_item_end(code, start)
            if re.search(r"\bpub\b", code[start:end + 1]):
                raise PROOF.VerificationFailure("installation fields must remain private")
        if re.search(r"\bClone\b", code):
            raise PROOF.VerificationFailure("one installation cannot be cloned")
        body, _ = route.function(source, "fn submit(")
        start, end = route.original.span(body, "let result = (|| {")
        for marker in ("let end = request_end.min(", "self.gate.require_original(end)?",
                       "self.sender.try_send(", "receiver.recv_timeout(remaining)"):
            at_depth(body[start:end], marker, 1)
        if not re.match(r"^\s*\)\(\);\s*if result.is_err\(\)", body[end:]):
            raise PROOF.VerificationFailure("all uncertain submissions must close the one attempt")
        body, _ = route.function(source, "fn run_installation(")
        for marker in ("let end = submission.end.min(session_end)", "gate.require_original(end)?",
                       "verify_pinned_process(", "super::super::learning::BoundLearning::bind(",
                       "crate::send_root_learning_handoff(", "crate::send_root_q24_model_factory_handoff(",
                       "submission.acknowledgement.try_send(())",
                       "super::super::learning::serve_optional_until("):
            at_depth(body, marker, 1)


class PostAInstallationSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {r.identifier: r for r in PROOF._boundary_rows(cls.manifest)}
        paths = {cls.boundaries[name].definition_path for name in CALLERS}
        paths.update(path for values in CALLERS.values() for path in values)
        cls.sources = {p: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / p).read_text()))
                       for p in paths}

    def mutate(self, path, change):
        rows = [r for r in self.manifest["protected_file"] if r["path"] == path]
        self.assertTrue(rows)
        source = (ROOT / path).read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)

            def verify(text):
                target.write_text(text)
                PROOF._verify_protected_files(root, {"protected_file": rows})
                require_structure(path, text)

            verify(source)
            changed = change(source)
            self.assertNotEqual(changed, source)
            with self.assertRaises(PROOF.VerificationFailure):
                verify(changed)

    def reject(self, path, name, marker, occurrence=0):
        def change(source):
            key = "fn " + name + "("
            body, _ = route.function(source, key)
            matches = list(re.finditer(route.token_pattern(marker), body))
            self.assertGreater(len(matches), occurrence, (path, name, marker))
            match = matches[occurrence]
            code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
            start = code.index(key)
            lo, hi = start + match.start(), start + match.end()
            return source[:lo] + "/* " + source[lo:hi] + " */" + source[hi:]
        self.mutate(path, change)

    def check(self, path, name, markers):
        for marker in markers:
            with self.subTest(function=name, marker=marker):
                self.reject(path, name, marker)

    def test_exact_callers_cannot_omit_or_add_a_new_custody_path(self):
        for identifier, callers in CALLERS.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, callers)
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, self.sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                if row.receiver_type:
                    bypass = f"fn bypass(real: &mut {row.receiver_type}) {{ real.{method}(); }}"
                elif "_listener_until" in identifier:
                    namespace = identifier.removeprefix("root_late_").removesuffix("_listener_until")
                    bypass = f"fn bypass() {{ {namespace}::serve_optional_until(); }}"
                elif identifier.endswith("installation_prepare"):
                    bypass = "fn bypass() { post_a_worker::prepare(); }"
                elif identifier.endswith("installation_serve"):
                    bypass = "fn bypass() { post_a_worker::serve_optional(); }"
                else:
                    bypass = f"fn bypass() {{ {method}(); }}"
                sources = dict(self.sources)
                sources[A + "unregistered_post_a.rs"] = bypass
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, sources, ())
                if callers:
                    with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                        PROOF._verify_boundary(ROOT, replace(row, product_callers=()), self.sources, ())

    def test_channel_end_only_shrinks_and_checks_the_actual_pidfd(self):
        self.check(OWNER, "limit_original_end", ("self.end = self.end.min(end)", "self.check(self.end)"))
        self.check(OWNER, "deadline", (".min(self.end)",))
        for occurrence in (0, 1):
            self.reject(OWNER, "check", "remaining(deadline.min(self.end))?", occurrence)
        self.check(OWNER, "check", ("PollFd::new(&self.owner, PollFlags::IN)", "HostIssuerTransportError::PeerDenied"))
        self.check(OWNER, "wait", ("remaining(deadline.min(self.end))?", "PollFd::new(&self.owner, PollFlags::IN)",
                                  "!descriptors[1].revents().is_empty()"))

    def test_failed_clamp_permanently_shuts_down_the_real_stream(self):
        self.check(PEER, "limit_original_end", ("self.stream.is_none()", "HostIssuerTransportError::Closed",
            "OwnerChannel::limit_original_end(&mut self.owner, end)", "result.is_err()",
            "self.stream.take()", "stream.shutdown(Shutdown::Both)"))
        for marker in ("self.end = self.end.min(end);", "self.check(self.end)"):
            self.mutate(OWNER, lambda source: source.replace(marker, "if false { " + marker + " }", 1))

    def test_absolute_end_controls_idle_read_and_precedes_every_reply(self):
        self.reject(PEER, "exchange_inner", "self.owner.end()")
        for occurrence in (0, 1, 2):
            self.reject(PEER, "exchange_inner", "self.owner.check(deadline)?", occurrence)

    def test_every_transport_clamps_before_its_existing_exchange(self):
        for path, stem in ((L, "learning_checkpoint"), (M, "q24_model_factory"), (P, "generation_publication")):
            self.check(path, "serve_" + stem + "_with_end", (
                "if let Some(end) = original_end", "HostAuthorityPeerChannel::limit_original_end(&mut channel, end)"))
            self.reject(path, "serve_" + stem + "_until", "Some(end)")
            self.reject(path, "serve_" + stem, "None")
            marker = "HostAuthorityPeerChannel::limit_original_end(&mut channel, end)"
            self.mutate(path, lambda source: source.replace(marker, "if false { " + marker + " }", 1))

    def test_listener_until_keeps_original_end_and_both_owner_checks(self):
        for path in (LS, MS, PS):
            self.reject(path, "serve_optional_until", "Some(end)")
            for occurrence in (0, 1):
                self.reject(path, "serve_optional_until", "owner_alive(owner, end)?", occurrence)
            self.reject(path, "serve_optional_with_end", "lifetime: end.checked_duration_since(Instant::now())")
            self.reject(path, "serve_optional_with_end", "stream.shutdown(Shutdown::Both)")
            self.reject(path, "serve_optional_with_end", "worker.join()")

    def test_nested_model_publication_and_ack_keep_the_same_end(self):
        self.check(LS, "serve_optional_with_end", (
            "Some(end) => super::q24_model::serve_optional_until(",
            "Some(end) => super::generation_publication::serve_optional_until("))
        self.check(PS, "serve_optional_with_end", (
            "if original_end.is_some()", "service.enroll_generation_publication("))
        self.reject(PS, "serve_optional_with_end", "owner_alive(owner, end)?", 1)

    def test_worker_keeps_original_root_incarnation_and_one_fixed_end(self):
        self.check(WORKER, "require_original", ("original_root()?", "std::process::id() != self.root_pid",
            ".trim() != self.boot_id", "root_start()? != self.start", "Instant::now() >= end"))
        self.check(WORKER, "serve_optional", ("worker.gate.require_original(session_end)?", "owner_alive(owner, session_end)?",
            "session_end.set(session_end)", "worker.inputs.lock()", ".take()",
            "compare_exchange(PREPARED, SERVING, Ordering::AcqRel, Ordering::Acquire)"))

    def test_submit_consumes_one_attempt_and_cannot_renew_the_request(self):
        self.check(WORKER, "submit", ("let end = request_end.min(", "self.gate.session_end.get()",
            "compare_exchange(SERVING, SUBMITTED, Ordering::AcqRel, Ordering::Acquire)",
            "self.sender.try_send(Submission {", "end.checked_duration_since(Instant::now())",
            ".filter(|duration| !duration.is_zero())", "receiver.recv_timeout(remaining)",
            "self.gate.phase.load(Ordering::Acquire) != INSTALLED", "self.gate.phase.store(CLOSED, Ordering::Release)"))
        for occurrence in (0, 1):
            self.reject(WORKER, "submit", "self.gate.require_original(end)?", occurrence)

    def test_bind_and_both_real_handoffs_precede_the_only_ack(self):
        self.check(WORKER, "run_installation", (
            "let end = submission.end.min(session_end)", "learning.q24_model.is_none()",
            "learning.backend.frozen_scope_binding()", "Some(frozen_scope.as_str())",
            "super::super::learning::BoundLearning::bind(learning, config, publication)?",
            "end.checked_duration_since(Instant::now())", ".map(|duration| duration.min(timeout))",
            "crate::send_root_learning_handoff(", "crate::send_root_q24_model_factory_handoff(",
            "compare_exchange(SUBMITTED, INSTALLED, Ordering::AcqRel, Ordering::Acquire)",
            "submission.acknowledgement.try_send(())", "super::super::learning::serve_optional_until("))
        for occurrence in (0, 1, 2, 3, 4):
            self.reject(WORKER, "run_installation", "gate.require_original(end)?", occurrence)
        for occurrence in (0, 1):
            self.reject(WORKER, "run_installation", "verify_pinned_process(", occurrence)

    def test_worker_operations_cannot_be_hidden_in_unreachable_blocks(self):
        for marker in ("self.gate.require_original(end)?;", "crate::send_root_learning_handoff(",
                       "super::super::learning::BoundLearning::bind("):
            self.mutate(WORKER, lambda source: source.replace(marker, "if false { " + marker + " }", 1))

    def test_outer_termination_closes_and_joins_the_owned_worker(self):
        self.check(WORKER, "serve_optional", ("let result = original()", "running.join()", "result.and(installed)"))
        for occurrence in (0, 1):
            self.reject(WORKER, "serve_optional", "worker.gate.phase.store(CLOSED, Ordering::Release)", occurrence)
        self.check(WORKER, "run_installation", ("while gate.phase.load(Ordering::Acquire) != CLOSED",
            "gate.require_original(session_end)?", "owner_alive(owner, session_end)?"))

    def test_installation_fields_cannot_become_a_cloneable_or_raw_wire_api(self):
        for marker in ("sender: mpsc::SyncSender<Submission>", "installation: PostALearningInstallation",
                       "root_pidfd: OwnedFd"):
            self.mutate(WORKER, lambda source: source.replace(marker, "pub(crate) " + marker, 1))
        self.mutate(WORKER, lambda source: source.replace("pub(super) struct PostALearningSubmitter", "#[derive(Clone)]\npub(super) struct PostALearningSubmitter", 1))
        self.mutate(WORKER, lambda source: source + "\nfn bypass() { open_registered_writer(); }\n")


if __name__ == "__main__":
    unittest.main()
