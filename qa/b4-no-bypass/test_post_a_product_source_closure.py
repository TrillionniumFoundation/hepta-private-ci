"""Keep the actual post-A CLI, Root contexts and late installation connected.

These mutate source custody and ordering. They are not native handoff, training,
publication or whole-system recovery evidence. Freeze locks cover the original
derived-profile action, not the subsequent outer Task postchecks or delivery.
"""
from dataclasses import replace
from pathlib import Path
import re
import tempfile
import tomllib
import unittest

import test_historical_task_read_source_closure as route
import test_post_a_installation_source_closure as install

ROOT, PROOF, A = route.ROOT, route.PROOF, route.A
PLAN = A + "authority_host_post_a_learning.rs"
DERIVE = A + "authority_host_post_a_derive.rs"
PROVIDER = A + "authority_host_post_a_provider.rs"
PREPARED, RUNTIME, CLI = route.PREPARED, route.RUNTIME, route.CLI
CALLERS = {
    "root_post_a_enable": (CLI,),
    "root_post_a_fixed_plan": (PREPARED,),
    "root_post_a_derive_profile": (PLAN,),
    "root_post_a_prepare_installation": (PROVIDER,),
    "root_post_a_install_provider": (route.PROVIDER,),
    "root_learning_derived_checkpoint": (PLAN,),
    "root_q24_factory_v2_reserve_same_service": (PLAN,),
}


def body_without_nested_functions(source, marker):
    body, raw = route.function(source, marker)
    cursor = body.index("{") + 1
    while nested := re.search(r"\bfn\s+(?:r#)?\w+", body[cursor:]):
        start = cursor + nested.start()
        end = PROOF._rust_item_end(body, start)
        if end is None:
            raise PROOF.VerificationFailure("complete nested source item required")
        body = body[:start] + "".join("\n" if c == "\n" else " "
                                      for c in body[start:end + 1]) + body[end + 1:]
        cursor = end + 1
    return body, raw


def require_returned(code, end):
    if not re.match(r"^\s*,\s*\)\?\s*;", code[end:]):
        raise PROOF.VerificationFailure("actual enclosing postcheck must return successfully")


def require_structure(path, source, rows):
    if path == PROVIDER:
        body, _ = body_without_nested_functions(source, "fn install_original_frozen_learning(")
        outer = route.original.span(body, "|read| {")
        context = route.original.span(body, "|initial, proof| {")
        if not outer[0] < context[0] < context[1] < outer[1]:
            raise PROOF.VerificationFailure("original recipient context escaped the complete Task")
        require_returned(body, context[1])
        require_returned(body, outer[1])
        install.at_depth(body, "RootRetainedHistoricalCompleteTaskV1::with_original_historical_task(", 1)
        install.at_depth(body, "post_a_worker::PostALearningSubmitter::submit(", 1)
        for marker in ("RootHistoricalSourceInputsV1::open_original_source_deployment(",
                       "RootInitialRunStartFilesV1::open_original_deployment(",
                       "RootOriginalHistoricalTaskReadV1::observe_original_task("):
            if not context[0] < body.index(marker) < context[1]:
                raise PROOF.VerificationFailure("original physical files escaped the actual recipient")
        prepare = body.index("post_a::PostALearningRuntime::prepare_original_installation(")
        submit = body.index("post_a_worker::PostALearningSubmitter::submit(")
        if not context[1] < prepare < outer[1] < submit:
            raise PROOF.VerificationFailure("late registration or handoff crossed its real postcheck")
        for marker in ("post_a::PostALearningRuntime::prepare_original_installation(",
                       "PostAFrozenLearningResponseV1 {", "Ok((installation, reply))"):
            install.at_depth(body, marker, 2)
        install.at_depth(body[outer[1]:], "require_end(end)?", 0)
    if path == PLAN:
        body, _ = body_without_nested_functions(source, "fn prepare_original_installation(")
        action = route.original.span(body, "|profile| {")
        install.at_depth(body, "self.with_original_derived_profile(", 1)
        for marker in ("service.prepare_original_derived_learning_checkpoint(",
                       "service.open_q24_model_factory_v2(", "service.seal_learning_checkpoint(",
                       "service.seal_q24_model_factory_offer(", "Ok(PostALearningInstallation {"):
            if not action[0] < body.index(marker) < action[1]:
                raise PROOF.VerificationFailure("original installation escaped the actual derived profile")
            install.at_depth(body, marker, 2)
        register = route.original.span(body, "if self.register")
        reserve = body.index("service.reserve_q24_model_factory_v2_for_profile(")
        if not action[0] < register[0] < reserve < register[1] < action[1]:
            raise PROOF.VerificationFailure("reopening cannot reserve a missing factory")
        install.at_depth(body, "service.reserve_q24_model_factory_v2_for_profile(", 3)
    if path == DERIVE:
        body, _ = body_without_nested_functions(source, "fn with_original_derived_profile<T>(")
        freeze = route.original.span(body,
            "PostAFreezeFiles::with_original_completion(&self.freeze, &key, end, |saved|")
        for marker in ("HostAuthorityLearningProfileV1::new_scoped_v2(", "let result = action(profile)?",
                       "RootHistoricalLearningTrustV1::revalidate(trust, service, initial)?",
                       "after.effective_weights_digest() != baseline.effective_weights_digest()"):
            if not freeze[0] < body.index(marker) < freeze[1]:
                raise PROOF.VerificationFailure("derived action escaped the original freeze observation")
        install.at_depth(body, "let result = action(profile)?", 2)
    if path == PREPARED:
        body, _ = body_without_nested_functions(source,
            "fn enable_original_post_a_learning_from_deployment(")
        context = route.original.span(body, "|initial, proof| {")
        require_returned(body, context[1])
        if not context[0] < body.index("post_a::PostALearningRuntime::retain_original_plan(") < context[1]:
            raise PROOF.VerificationFailure("fixed Root deployment escaped its original registration")
        prepare = body.index("post_a_worker::prepare(")
        if not context[1] < prepare < body.index("runtime.post_a = Some(plan)"):
            raise PROOF.VerificationFailure("late worker became available before registration postchecks")
        install.at_depth(body, "post_a_worker::prepare(", 1)
    if path == RUNTIME:
        body, _ = body_without_nested_functions(source, "fn serve_optional(")
        install.at_depth(body, "post_a_worker::serve_optional(", 1)
        outer = route.original.span(body, "post_a_worker::serve_optional(")
        for marker in ("bound.listener.accept()", "let result = original()",
                       "stream.shutdown(Shutdown::Both)", "result.and(historical)"):
            if not outer[0] < body.index(marker) < outer[1]:
                raise PROOF.VerificationFailure("historical shutdown escaped its owned late worker")
    if path == CLI:
        body, raw = body_without_nested_functions(source, "fn main() -> Result")
        for row in rows:
            if "required_order" in row:
                PROOF._verify_required_order(row, body, path)
        start = body.index("let post_a_deployment = options")
        end = body.index(";", start)
        literal = '.remove(std::ffi::OsStr::new("--post-a-learning-deployment"))'
        if literal not in raw[start:end] or PROOF._strip_rust_non_code(literal) not in body[start:end]:
            raise PROOF.VerificationFailure("the actual option must select the protected Root plan")
        for marker, depth in (("if post_a_deployment.is_some()", 2),
                              ("if let Some(post_a_path) = post_a_deployment.as_deref()", 4),
                              ("enable_original_post_a_learning_from_deployment(", 5)):
            install.at_depth(body, marker, depth)


class PostAProductSourceTests(unittest.TestCase):
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
                require_structure(path, text, rows)
            verify(source)
            changed = change(source)
            self.assertNotEqual(changed, source)
            with self.assertRaises(PROOF.VerificationFailure):
                verify(changed)

    reject = route.HistoricalTaskReadSourceTests.reject
    check = route.HistoricalTaskReadSourceTests.check

    def test_actual_root_entry_and_derived_callers_are_closed(self):
        for identifier, callers in CALLERS.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, callers)
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, self.sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                bypass = (f"fn bypass(actual: &{row.receiver_type}) {{ actual.{method}(); }}"
                          if row.receiver_type else f"fn bypass() {{ {method}(); }}")
                sources = dict(self.sources)
                sources[A + "unregistered_late_root.rs"] = bypass
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, sources, ())
                for omitted in callers:
                    declared = tuple(p for p in callers if p != omitted)
                    with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                        PROOF._verify_boundary(ROOT, replace(row, product_callers=declared), self.sources, ())

    def test_prepared_route_requires_original_phase_custody_and_empty_slots(self):
        self.check(PREPARED, "enable_original_post_a_learning_from_deployment", (
            "original_root()?", "self.learning.is_some() || self.publication.is_some()",
            "self.historical_read.as_mut()", "runtime.phase.load(Ordering::Acquire) != PREPARED",
            "runtime.post_a.is_some()", "runtime.post_a_worker.is_some()",
            "runtime.post_a_submitter.get_mut()", "let plan = self.service.with_learning_profile(",
            "HistoricalTaskReadProfileV1::require_original_context(", "expected != initial",
            "post_a::PostALearningRuntime::retain_original_plan(", "self.config.peer_uid",
            "self.config.peer_gid", "post_a_worker::prepare(learning_handoff, model_handoff, root_pidfd, publication.map(|(_, handoff)| handoff))?",
            "runtime.post_a = Some(plan)", "runtime.post_a_worker = Some(worker)"))
        for marker in ("runtime.metadata.require_metadata_unchanged()?", "RootHistoricalLearningTrustV1::revalidate("):
            for occurrence in (0, 1):
                self.reject(PREPARED, "enable_original_post_a_learning_from_deployment", marker, occurrence)

    def test_provider_reads_actual_task_inside_the_original_unfrozen_context(self):
        self.check(PROVIDER, "install_original_frozen_learning", (
            "RootRetainedHistoricalCompleteTaskV1::with_original_historical_task(",
            "service.with_learning_profile(", "&self.deployment.initial",
            "self.profile.require_original_context(", "self.phase.load(Ordering::Acquire) != SERVING",
            "RootOriginalHistoricalTaskReadV1::require_original_target(",
            "RootOriginalHistoricalTaskReadV1::observe_original_task(",
            "RootHistoricalSourceInputsV1::open_original_source_deployment(",
            "RootInitialRunStartFilesV1::open_original_deployment(",
            "RootHistoricalLearningTrustV1::require_original_ledger(",
            "Ok((initial, proof, observed))"))

    def test_derived_registration_and_seals_use_the_same_original_profile(self):
        self.check(PLAN, "prepare_original_installation", (
            "original_root()?", "registration.registered_identity.identity()?",
            "self.with_original_derived_profile(", "profile.require_cell_scope(initial)?.binding().to_string()",
            "service.prepare_original_derived_learning_checkpoint(", "self.original_mode()",
            "if self.register", "service.reserve_q24_model_factory_v2_for_profile(",
            "&self.reservation,", "service.open_q24_model_factory_v2(", "&self.reservation_path,",
            "service.seal_learning_checkpoint(", "service.seal_q24_model_factory_offer(",
            "learning.q24_model = Some(factory)", "self.require_original_metadata()?",
            "Ok(PostALearningInstallation {", "frozen_scope,"))
        for occurrence in (0, 1, 2):
            self.reject(PLAN, "prepare_original_installation", "require_end(end)?", occurrence)

    def test_original_context_and_all_data_postchecks_precede_submission(self):
        self.check(PROVIDER, "install_original_frozen_learning", (
            "post_a::PostALearningRuntime::prepare_original_installation(",
            "RootOriginalHistoricalCompleteTaskObservationV1::data_cut_digest(&observed)",
            "profile: self.profile.binding.clone()", "frozen_scope: installation.frozen_scope.clone()",
            "reply.is_empty() || reply.len() > WIRE_BOUND", "Ok((installation, reply))",
            "self.post_a_submitter", ".try_lock()", ".take()",
            "post_a_worker::PostALearningSubmitter::submit(submitter, installation, end)?"))
        for occurrence in range(5):
            self.reject(PROVIDER, "install_original_frozen_learning", "require_end(end)?", occurrence)
        for occurrence in (0, 1):
            self.reject(PROVIDER, "install_original_frozen_learning", "self.metadata.require_metadata_unchanged()?", occurrence)
            self.reject(PROVIDER, "install_original_frozen_learning", "RootHistoricalLearningTrustV1::revalidate(", occurrence)

    def test_postchecks_cannot_be_replaced_by_closure_creation_or_caught_errors(self):
        for path, marker in ((PROVIDER, "|initial, proof| {"), (PROVIDER, "|read| {"),
                             (PREPARED, "|initial, proof| {")):
            def change(source):
                code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
                _, end = route.original.span(code, marker)
                match = re.match(r"\s*,\s*\)\?\s*;", code[end:])
                self.assertIsNotNone(match)
                right = end + match.end()
                return source[:end] + source[end:right].replace("?", ".unwrap_or_default()", 1) + source[right:]
            self.mutate(path, change)

    def test_actions_in_unreachable_or_nested_helpers_cannot_supply_actual_order(self):
        for path, marker in ((PROVIDER, "post_a_worker::PostALearningSubmitter::submit(submitter, installation, end)?;"),
                             (DERIVE, "let result = action(profile)?;")):
            self.mutate(path, lambda s: s.replace(marker, "if false { " + marker + " }", 1))
        self.mutate(CLI, lambda s: s.replace("fn main() -> Result", "fn unrelated_main() -> Result", 1))
        def hide(source):
            code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
            start = code.index("if let Some(post_a_path) = post_a_deployment.as_deref()")
            _, end = route.original.span(code, "if let Some(post_a_path) = post_a_deployment.as_deref()")
            return source[:start] + "if false { " + source[start:end] + " }" + source[end:]
        self.mutate(CLI, hide)

    def test_cli_requires_both_late_fds_and_rejects_eager_owner_substitution(self):
        self.check(CLI, "main", ("let post_a_deployment = options", "if post_a_deployment.is_some()",
            "historical_deployment.is_none()", "learning_handoff.is_none()", "model_handoff.is_none()",
            "learning_profile.is_some()", "model_reservation.is_some()",
            "if let Some(post_a_path) = post_a_deployment.as_deref()", "learning_handoff.take()",
            "model_handoff.take()", "enable_original_post_a_learning_from_deployment("))
        # The first occurrence belongs to the separate eager Initial guard.
        self.reject(CLI, "main", "publication_handoff.is_some()", 1)
        self.mutate(CLI, lambda s: s.replace('"--post-a-learning-deployment"',
                    '"--untrusted-post-a" /* "--post-a-learning-deployment" */', 1))
        self.mutate(CLI, lambda s: s.replace("&& (historical_deployment.is_none()",
                                           "|| (historical_deployment.is_none()", 1))
        self.mutate(CLI, lambda s: s.replace("|| model_reservation.is_some()",
                                           "&& model_reservation.is_some()", 1))

    def test_serve_scope_preserves_absolute_end_and_closes_before_joining(self):
        self.check(RUNTIME, "serve_optional", ("post_a_worker::serve_optional(",
            "bound.runtime.post_a_worker.as_ref()", "HostAuthorityPeerChannel::limit_original_end(&mut channel, session_end)",
            "stopping.store(true, Ordering::Release)", "stream.shutdown(Shutdown::Both)",
            "worker.join()", "result.and(historical)"))


if __name__ == "__main__":
    unittest.main()
