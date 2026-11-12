"""Preserve original four-cut Version, shared T/B custody and C readiness.

These are exact source/caller mutation gates, not native or ordinary-loop
qualification. Legacy three-cut contexts, original signatures and the source
verifier are unchanged. Empty producer caller sets are explicit deployment gaps.
"""
from collections import Counter
from dataclasses import replace
import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest

ROOT=Path(__file__).resolve().parents[2]
SPEC=importlib.util.spec_from_file_location("evaluated_version_source_proof",ROOT/"scripts/verify_hepta_callers.py")
assert SPEC is not None and SPEC.loader is not None
PROOF=importlib.util.module_from_spec(SPEC);sys.modules[SPEC.name]=PROOF;SPEC.loader.exec_module(PROOF)
A="codex-rs/hepta-agentd/src/"
CUT=A+"circuit_evaluated_version_context.rs"
PROFILE=A+"circuit_retained_version_profile.rs"
WIRE=A+"circuit_evaluated_version_wire.rs"
HOST=A+"circuit_evaluated_version_host.rs"
STATE=A+"circuit_retained_version_state.rs"
OLDHOST=A+"circuit_retained_version_host.rs"
CLIENT=A+"circuit_retained_version_client.rs"
EFFECT=A+"circuit_retained_version_effect.rs"
PREPARED=A+"circuit_retained_version_prepared.rs"
SERVICE=A+"circuit_retained_version_service.rs"
COMMAND=A+"circuit_evaluated_version_commands.rs"
READINESS=A+"circuit_evaluated_completion_readiness.rs"
READINESS_SERVER=A+"circuit_evaluated_completion_readiness_service.rs"
PRODUCER=A+"circuit_evaluated_version_readiness.rs"
PHYSICAL=A+"circuit_learning_completion_readiness_service.rs"
PUBLISHER=A+"circuit_evaluated_retention_publication.rs"
PROTOCOL=A+"circuit_retained_version.rs"

EXPECTED=__EXPECTED__
FUNCTIONS=__FUNCTIONS__
OWN_PATHS=__OWN_PATHS__
DOMAINS={
    CUT: [("authenticate",r"Ok\(Digest32::of_parts\(&\[",'b"hepta.agentd.original-evaluated-version.command.v1\\0"')],
    WIRE: [(None,r"const EVALUATED_OPERATION: &str =",'"runtime.learning.original-evaluated-version.command.v1"')],
    READINESS: [(None,r"const PURPOSE: &str =",'"runtime.learning.original-circuit.evaluated-completion-readiness.v1"')],
}
MOUNTS={
    A+"circuit_retained_version.rs":(("evaluated_context","circuit_evaluated_version_context.rs"),("evaluated_wire","circuit_evaluated_version_wire.rs"),("profile","circuit_retained_version_profile.rs")),
    OLDHOST:(("evaluated","circuit_evaluated_version_host.rs"),("prepared","circuit_retained_version_prepared.rs"),("readiness","circuit_evaluated_version_readiness.rs"),("evaluated_commands","circuit_evaluated_version_commands.rs")),
    A+"circuit_learning_read_capability.rs":(("evaluated_readiness","circuit_evaluated_completion_readiness.rs"),),
    A+"circuit_learning_read_service.rs":(("evaluated_readiness","circuit_evaluated_completion_readiness_service.rs"),),
    A+"circuit_evaluated_retention_receipt_tests.rs":(("version_tests","circuit_evaluated_version_support_tests.rs"),),
    A+"circuit_evaluated_version_support_tests.rs":(("completion","circuit_evaluated_completion_readiness_tests.rs"),("recovery","circuit_evaluated_version_recovery_tests.rs"),("issuer","circuit_evaluated_version_issuer_tests.rs"),("capacity","circuit_evaluated_version_capacity_tests.rs")),
    A+"circuit_evaluated_version_issuer_tests.rs":(("shared_commands","circuit_evaluated_version_shared_command_tests.rs"),),
    A+"circuit_retained_version_issuer_host_tests.rs":(("evaluated_progress","circuit_evaluated_version_progress_support_tests.rs"),),
}


def span(source,name,occurrence=0):
    code=PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
    found=list(re.finditer(r"\bfn\s+"+re.escape(name)+r"\s*(?:<|\()",code))
    if len(found)<=occurrence:raise PROOF.VerificationFailure("actual function missing: "+name)
    start=found[occurrence].start();end=PROOF._rust_item_end(code,start)
    if end is None:raise PROOF.VerificationFailure("actual function incomplete")
    return code,start,end+1


def actual_domains(path,source):
    code=PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
    for function,prefix,literal in DOMAINS.get(path,()):
        start,end=0,len(code)
        if function is not None:_,start,end=span(source,function)
        found=list(re.finditer(prefix,code[start:end]))
        if len(found)!=1:raise PROOF.VerificationFailure("unique original protocol expression")
        offset=start+found[0].end()
        actual=re.match(r'\s*(b?"(?:[^"\\]|\\.)*")',source[offset:end])
        if actual is None or actual.group(1)!=literal:raise PROOF.VerificationFailure("actual original protocol domain")
        if function is None and code[:offset].count("{")!=code[:offset].count("}"):
            raise PROOF.VerificationFailure("original purpose must be a module constant")


def actual_mounts(path,source):
    code=PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
    for name,target in MOUNTS[path]:
        pattern=r"#\[path\s*=\s+\]\s*mod\s+"+re.escape(name)+r";"
        matches=list(re.finditer(pattern,code))
        if len(matches)!=1:raise PROOF.VerificationFailure("actual mounted module "+name)
        actual=source[matches[0].start():matches[0].end()]
        if re.fullmatch(r'#\[path\s*=\s*"'+re.escape(target)+r'"\]\s*mod\s+'+re.escape(name)+r';',actual) is None:
            raise PROOF.VerificationFailure("actual original module path")


def actual_progress_wire_shapes(source):
    code=PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
    for kind,name,annotation in (
        ("enum","EvaluatedAction",'#[serde(rename_all = "snake_case")]'),
        ("struct","EvaluatedRequest",'#[serde(deny_unknown_fields)]'),
        ("struct","EvaluatedResponse",'#[serde(deny_unknown_fields)]'),
        ("struct","EvaluatedProgressResponse",'#[serde(deny_unknown_fields)]'),
        ("enum","EvaluatedProgressResult",'#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]'),
    ):
        matches=list(re.finditer(r'(?m)^[ \t]*(?:pub(?:\([^\n]*?\))?\s+)?'+kind+r'\s+'+name+r'\s*\{',code))
        if len(matches)!=1 or not source[:matches[0].start()].rstrip().endswith(annotation):
            raise PROOF.VerificationFailure("actual strict evaluated wire type "+name)


class EvaluatedVersionClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest=tomllib.loads((ROOT/"CALLERS.toml").read_text())
        cls.boundaries={b.identifier:b for b in PROOF._boundary_rows(cls.manifest)}

    def verifies(self,path,source,domains=True):
        rows=[r for r in self.manifest["protected_file"] if r["path"]==path]
        self.assertTrue(rows,path)
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/path;target.parent.mkdir(parents=True);target.write_text(source)
            PROOF._verify_protected_files(Path(directory),{"protected_file":rows})
        if domains:actual_domains(path,source)
        if path==WIRE:actual_progress_wire_shapes(source)
        if path in FUNCTIONS:
            code=PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
            actual=Counter(re.findall(r"\bfn\s+([A-Za-z_]\w*)\s*(?:<|\()",code))
            if dict(actual)!=FUNCTIONS[path]:raise PROOF.VerificationFailure("exact private function inventory")

    def rejects_source(self,path,changed,domains=True):
        self.verifies(path,(ROOT/path).read_text(),domains)
        with self.assertRaises(PROOF.VerificationFailure):self.verifies(path,changed,domains)

    def rejects(self,path,function,marker,replacement="",occurrence=0):
        source=(ROOT/path).read_text();code,start,end=span(source,function)
        pattern=r"\s*".join(re.escape(t) for t in re.findall(r"\w+|[^\w\s]",marker))
        found=list(re.finditer(pattern,code[start:end]));self.assertGreater(len(found),occurrence,(path,function,marker))
        match=found[occurrence];a=start+match.start();b=start+match.end()
        self.rejects_source(path,source[:a]+replacement+source[b:])

    def reject_each(self,path,function,markers):
        for marker in markers:
            with self.subTest(path=path,function=function,marker=marker):self.rejects(path,function,marker)

    def rejects_unused_body(self,path,function):
        source=(ROOT/path).read_text();code,start,end=span(source,function);opening=code.index("{",start,end)
        changed=source[:opening+1]+"\nlet _never_called = || async {"+source[opening+1:end-1]+"\n}; panic!();\n"+source[end-1:]
        self.rejects_source(path,changed)

    def rejects_unused_branch(self,path,function,marker):
        source=(ROOT/path).read_text();code,start,end=span(source,function)
        pattern=r"\s*".join(re.escape(t) for t in re.findall(r"\w+|[^\w\s]",marker))
        found=re.search(pattern,code[start:end]);self.assertIsNotNone(found,(path,function,marker))
        begin=start+found.start();opening=code.index("{",begin,end);closing=PROOF._matching_delimiter(code,opening,"{","}")
        self.assertIsNotNone(closing)
        changed=source[:opening+1]+"\nlet _never_called = || async {"+source[opening+1:closing]+"\n}; panic!();\n"+source[closing:]
        self.rejects_source(path,changed)

    def test_exact_actual_callers_and_extra_callers_are_rejected(self):
        paths={path for name in EXPECTED for path in (self.boundaries[name].definition_path,*self.boundaries[name].product_callers)}
        sources={p:PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT/p).read_text())) for p in paths}
        for name,expected in EXPECTED.items():
            with self.subTest(boundary=name):
                row=self.boundaries[name];self.assertEqual(row.product_callers,expected)
                self.assertIn(name,self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT,row,sources,())
                method=row.symbol.rsplit("::",1)[-1]
                extra=dict(sources)
                call=(f"{row.receiver_type}::{method}(owner)" if row.receiver_type else f"{method}()")
                argument=(f"owner: &{row.receiver_type}" if row.receiver_type else "")
                extra[A+"unregistered_evaluated_version.rs"]=f"fn unregistered({argument}) {{ {call}; }}"
                with self.assertRaisesRegex(PROOF.VerificationFailure,"unexpected"):PROOF._verify_boundary(ROOT,row,extra,())
                if expected:
                    with self.assertRaises(PROOF.VerificationFailure):PROOF._verify_boundary(ROOT,replace(row,product_callers=()),sources,())
        for name,path in (
            ("learning_evaluated_version_client_bind",A+"cell_q24_candidate_stage_retention_binding.rs"),
            ("learning_evaluated_completion_readiness_current",A+"cell_q24_candidate_stage_retention_next_use.rs"),
            ("learning_evaluated_version_selection_physical_binding",COMMAND),
        ):
            extra=dict(sources);extra[A+"unregistered_actual_version_caller.rs"]=sources[path]
            with self.assertRaisesRegex(PROOF.VerificationFailure,"unexpected"):PROOF._verify_boundary(ROOT,self.boundaries[name],extra,())
        self.assertTrue(all(x is False for x in self.manifest["authority"].values()))

    def test_every_new_actual_function_and_private_shape_is_protected(self):
        for path in OWN_PATHS:self.verifies(path,(ROOT/path).read_text())
        for path in FUNCTIONS:
            source=(ROOT/path).read_text()
            self.rejects_source(path,source+"\nfn unregistered_export() {}\n")

    def test_real_modules_and_all_native_cases_are_mounted_without_cfg_bypass(self):
        for path,modules in MOUNTS.items():
            source=(ROOT/path).read_text();actual_mounts(path,source)
            for name,target in modules:
                declaration="mod "+name+";"
                for changed in (source.replace(declaration,"",1),source.replace(declaration,"#[cfg(any())]\n"+declaration,1)):
                    with self.assertRaises(PROOF.VerificationFailure):actual_mounts(path,changed)
        source=(ROOT/A/"lib.rs").read_text();code=PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        for name,visibility in (("OriginalCircuitEvaluatedVersionRecoveryV1","pub"),("OriginalCircuitEvaluatedReadinessChannelV1","pub"),("OriginalCircuitEvaluatedCompletionReadinessClientV1","pub(crate)")):
            text='#[cfg(target_os = "linux")]\n'+visibility+" use circuit_feature_current::"+name+";"
            self.assertIn(text,source);at=source.index(text)
            self.assertEqual(code[at:at+len(text)],PROOF._strip_rust_non_code(text))
        for file,names in (
            ("circuit_evaluated_completion_readiness_tests.rs",("evaluated_readiness_waits_for_actual_c_and_preserves_original_selection","evaluated_readiness_withdrawal_is_fatal_and_consumes_original_connection","evaluated_readiness_completed_identity_and_queued_cancellation_never_revive")),
            ("circuit_evaluated_version_capacity_tests.rs",("evaluated_version_mixed_trainer_purposes_share_four_sessions_and_refuse_fifth",)),
            ("circuit_evaluated_version_issuer_tests.rs",("evaluated_version_issuer_consumes_actual_d_t_b_and_installs_original_c_once",)),
            ("circuit_evaluated_version_recovery_tests.rs",("evaluated_version_cold_readback_keeps_four_cut_and_original_c_readiness",)),
        ):
            text=(ROOT/A/file).read_text()
            actual=PROOF._strip_rust_non_code(text)
            for name in names:self.assertEqual(len(re.findall(r"\basync fn "+name+r"\(",actual)),1)

    def test_actual_independent_domains_cannot_be_supplied_by_comments(self):
        for path,guards in DOMAINS.items():
            source=(ROOT/path).read_text()
            for _,_,literal in guards:
                index=literal.index('"')+1
                changed=source.replace(literal,literal[:index]+"x"+literal[index+1:],1)
                changed+="\n// "+next(line for line in source.splitlines() if literal in line)+"\n"
                self.verifies(path,changed,domains=False)
                self.rejects_source(path,changed)

    def test_complete_original_dataset_and_all_signature_pins_are_required(self):
        self.reject_each(CUT,"from_original",("OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(","RetainedVersionOriginV1::Fresh","OriginalCircuitEvaluatedRetentionContextV1::from_original_evaluation(","RetainedVersionOriginV1::Recovered","OriginalCircuitEvaluatedRetentionContextV1::recover_original_evaluation(","OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(","require_clock(started, fresh)?","cut.authenticate(fresh, PublicationAccess::Readback)?"))
        checks=("initial.snapshot() != &self.material.initial","scope != self.material.scope","verifier.trust_digest() != self.material.verifier.trust_digest()","verifier.scope_digest() != self.material.verifier.scope_digest()","verifier.objective_digest() != self.material.verifier.objective_digest()","self.dataset.snapshot().request != prefix.request","self.dataset.snapshot().owners != prefix.owners","self.dataset.snapshot().receipts != prefix.receipts[..2]","self.dataset.snapshot().head_digest != prefix.receipts[2].predecessor")
        for marker in checks:
            self.rejects(CUT,"authenticate",marker);self.rejects(CUT,"authenticate",marker,marker.replace("!=","=="))
        self.reject_each(CUT,"authenticate",("self.evaluated.authenticate(at, access)?","original.signing_bytes()","&original.signature","&encode_original_owner_snapshot_v1(prefix)?","self.initial_binding.as_array()","&material_signatures","self.evaluated.receipt_context_binding().as_array()"))
        self.reject_each(CUT,"require_fresh",("require_clock(started, at)?","require_clock(at, fresh)?","self.authenticate(fresh, access)? != self.binding"))
        self.rejects_unused_body(CUT,"authenticate")
        for marker in ("RetainedVersionOriginV1::Fresh => {","RetainedVersionOriginV1::Recovered => {"):self.rejects_unused_branch(CUT,"from_original",marker)

    def test_legacy_three_cut_and_evaluated_four_cut_dispatch_never_alias(self):
        self.reject_each(PROFILE,"legacy_reader",("let Self::TrainingNoUpdate(cut) = self else","training_evidence: cut.training.training_evidence.clone()","selection_evidence: None"))
        self.reject_each(PROFILE,"evaluated_reader",("let Self::Evaluated(cut) = self else","OriginalCircuitEvaluatedLearningReadContextV1::for_original_selection(","cut.evaluated.clone_for_original_receipt()"))
        self.rejects(PROFILE,"evaluated_reader","clone_for_original_receipt()","into_original_receipt_readback()")
        for name,kind in (("serve_original_selection_readback","TrainingNoUpdate"),("serve_original_evaluated_selection_readback","Evaluated")):
            marker="self.purpose != VersionPurpose::"+kind
            self.rejects(SERVICE,name,marker);self.rejects(SERVICE,name,marker,marker.replace("!=","=="));self.rejects_unused_body(SERVICE,name)
        self.reject_each(SERVICE,"serve_selection_readback",("VersionPurpose::TrainingNoUpdate => OriginalCircuitLearningReadOwnerV1::serve_original_retained_channel(","VersionPurpose::Evaluated => OriginalCircuitLearningReadOwnerV1::serve_original_evaluated_retained_channel("))
        for name in ("serve_completion_readiness","readiness_response"):
            self.rejects(PHYSICAL,name,"self.context.legacy()?")

    def test_wire_fixes_evaluation_head_all_echo_fields_and_original_bounds(self):
        for marker in ("schema != 1","operation != expected_operation","actual_id != request_id","!(1..=128).contains(&request_id)","initial_pin != &initial_binding.to_string()","operation_id != &initial.request.operation_id.to_string()"):
            self.rejects(WIRE,"require_initial",marker)
        for marker in ("VersionPurpose::TrainingNoUpdate","VersionPurpose::Evaluated","&original.training_head","&original.evaluation_head","wire::digest(binding)?","wire::digest(head)?"):
            self.rejects(WIRE,"require_initial",marker)
        self.reject_each(WIRE,"require_cut",("request.require_cut(original, request_id)","request != &EvaluatedRequest::new(original, request_id, request.action)","!(1..=128).contains(&request_id)"))
        for n in (0,1):self.rejects(WIRE,"decode_response","&response.request != request",occurrence=n)
        for marker in ("Self::TrainingNoUpdate(request) => {","Self::Evaluated(request) => {"):
            self.rejects_unused_branch(WIRE,"decode_response",marker)

    def test_original_cold_origin_and_initial_connections_cannot_be_reissued(self):
        self.reject_each(HOST,"recover_from_original_evaluated_owners",("original.evaluation.into_original_receipt_readback()","evaluation.original_receipt_predecessors(","evaluation.snapshot().receipts.len() != 4","RetainedVersionHostPhaseV1::Recovered(","RetainedVersionOriginV1::Recovered","final_use_issuer: None","expected_evaluated: Some(EvaluatedVersionExpectedV1"))
        self.rejects(HOST,"recover_from_original_evaluated_owners","RetainedVersionOriginV1::Recovered","RetainedVersionOriginV1::Fresh")
        self.reject_each(STATE,"bind_original_predecessor",("if let Some(cut) = state.cut.as_ref()","VersionCut::TrainingNoUpdate(_) => state.require_cut_current(&self.runtime)","OriginalCellQ24DatasetCommandReadbackV1::verify_original_cut(",".initial_trainer.take()","OriginalCellQ24TrainingCommandConnectionV1::bind_original_dataset(","OriginalCellQ24TrainingCommandClientV1::readback(&trainer)","state.initial_evaluator.take()","OriginalCellEvaluationCommandConnectionV1::bind_original_training(","OriginalCellEvaluationCommandClientV1::readback(&evaluator)","expected.dataset != cut.dataset","expected.evaluation.snapshot() != cut.evaluated.snapshot()","expected.evaluation.receipt_context_binding() != cut.evaluated.receipt_context_binding()","self.origin == RetainedVersionOriginV1::Recovered","state.shared_evaluated = Some(SharedEvaluatedReadbacks"))
        self.rejects_unused_branch(STATE,"bind_original_predecessor","VersionPurpose::Evaluated => {")

    def test_progress_is_private_scheduling_and_never_a_legacy_or_current_result(self):
        self.rejects_source(PROTOCOL,(ROOT/PROTOCOL).read_text().replace("pub(crate) enum OriginalCircuitEvaluatedVersionProgressV1", "pub enum OriginalCircuitEvaluatedVersionProgressV1",1))
        self.rejects_source(PROTOCOL,(ROOT/PROTOCOL).read_text()+"\nimpl OriginalCircuitEvaluatedVersionProgressV1 { pub fn into_current(self) {} }\n")
        self.reject_each(WIRE,"publication_progress",("let VersionCut::Evaluated(original) = cut else","EvaluatedAction::PublicationProgress"))
        self.rejects_unused_body(WIRE,"publication_progress")
        for name in ("decode_progress_response","encode_progress_response"):
            self.reject_each(WIRE,name,("let Self::Evaluated(request) = self else","request.action != EvaluatedAction::PublicationProgress"))
            self.rejects_unused_body(WIRE,name)
        self.rejects(WIRE,"decode_progress_response","&response.request != request")
        for name in ("decode_response","encode_response"):
            self.rejects(WIRE,name,"self.is_publication_progress()")
        self.reject_each(CLIENT,"publication_progress",("!matches!(self.cut.as_ref(), VersionCut::Evaluated(_))","self.exchange_original(RequestMode::PublicationProgress).await?","OriginalVersionValue::Readback(_) => Err"))
        self.rejects_unused_body(CLIENT,"publication_progress")
        source=(ROOT/WIRE).read_text()
        for attribute in ('#[serde(deny_unknown_fields)]','#[serde(rename_all = "snake_case")]','#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]'):
            for match in re.finditer(re.escape(attribute),source):
                self.rejects_source(WIRE,source[:match.start()]+source[match.end():])
        source=(ROOT/A/"circuit_retained_version_wire.rs").read_text()
        code=PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        self.assertNotIn("PublicationProgress",code)
        self.assertNotIn("ReadbackAvailable",code)
        for path,line in (
            (A+"circuit_feature_current.rs","pub(crate) use retained_publication::version::OriginalCircuitEvaluatedVersionProgressV1;"),
            (A+"lib.rs","pub(crate) use circuit_feature_current::OriginalCircuitEvaluatedVersionProgressV1;"),
        ):
            text=(ROOT/path).read_text();code=PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(text))
            self.assertEqual(code.count(line),1)
            self.assertNotIn(line.replace("pub(crate)","pub"),code)

    def test_progress_does_not_open_owners_or_claim_current_when_worker_is_pending(self):
        self.reject_each(SERVICE,"command_response",("if request.is_publication_progress()","self.publication_progress_response(request, request_id, started)","request.require_initial("))
        self.reject_each(SERVICE,"publication_progress_response",("self.purpose != VersionPurpose::Evaluated || !request.is_publication_progress()","None => (EvaluatedProgressResult::ReadbackRequired, None)","!matches!(cut, VersionCut::Evaluated(_))","request.require_cut(cut, request_id)?","cut.require_fresh(started, PublicationAccess::Readback)?","RetainedVersionFinalUseOutcomeV1::Denied","RetainedVersionFinalUseOutcomeV1::Uncertain","(_, None)","self.preparation_requested.load(Ordering::Acquire)","RetainedVersionHostPhaseV1::Prepared","RetainedVersionFinalUseOutcomeV1::Published","RetainedVersionHostPhaseV1::Installed","RetainedVersionHostPhaseV1::Recovered","Some(cut.duplicate_response_pin())","binding != self.initial_binding || fresh < started","self.require_lifetime()?","bytes.len() > 16_384","pin.require_fresh(started, PublicationAccess::Readback)?"))
        self.rejects_unused_body(SERVICE,"publication_progress_response")
        self.rejects_unused_branch(SERVICE,"publication_progress_response","Some(cut) => {")
        code,start,end=span((ROOT/SERVICE).read_text(),"publication_progress_response")
        for marker in ("bind_original_predecessor(","read_original(","require_cut_current(","phase.take()","initial_trainer.take()","initial_evaluator.take()","final_use_issuer.take()","preparation_requested.store("):
            self.assertNotIn(marker,code[start:end])
        source=(ROOT/SERVICE).read_text();at=source.index("// This is only the private worker's scheduling state.")
        self.rejects_source(SERVICE,source[:at]+"self.bind_original_predecessor(&mut state)?;\n"+source[at:])

    def test_progress_uses_the_original_once_counter_deadline_and_cancellation(self):
        self.reject_each(CLIENT,"exchange_original",("self.cut.require_fresh(started, access)?","action == Some(wire::Action::Prepare) && original.preparation_requested","original.preparation_requested = true","slot.take().ok_or(Error::Unavailable)?","!(1..=128).contains(&channel.next_request_id)","VersionRequest::publication_progress(&self.cut, channel.next_request_id)?","encoded.len() > 16_384","channel.next_request_id += 1","QueuedVersionRequestFence::new()","dropped.load(Ordering::Acquire)","cut.require_fresh(started, access)?","channel.peer.request(&encoded)?","request.decode_progress_response(&raw)?","request.decode_response(&raw)?","channel.peer.check_peer_lifetime()?","OriginalVersionResponse::Progress(response) => match response.decode()","Err(error) => return Err(error)","self.pin(value)?","Some(channel)"))
        self.rejects_unused_body(CLIENT,"exchange_original")
        self.rejects_unused_branch(CLIENT,"exchange_original","tokio::task::spawn_blocking(move || {")
        self.rejects(CLIENT,"drop","self.cancelled.store(true, Ordering::Release)")
        self.rejects(CLIENT,"exchange_original","Err(Error::Busy) => Err(Error::Busy)","Err(_) => Ok(OriginalVersionValue::Progress(OriginalCircuitEvaluatedVersionProgressV1::ReadbackAvailable))")

    def test_bound_cut_is_not_an_extra_read_or_a_substitute_for_full_transactions(self):
        self.reject_each(STATE,"bind_original_predecessor",("cut.purpose() != self.purpose || cut.initial_binding() != self.initial_binding","VersionCut::TrainingNoUpdate(_) => state.require_cut_current(&self.runtime)","VersionCut::Evaluated(_) => cut.require_fresh(","super::super::now()?, PublicationAccess::Readback"))
        self.rejects_unused_branch(STATE,"bind_original_predecessor","if let Some(cut) = state.cut.as_ref() {")
        for n in (0,1):self.rejects(STATE,"read_original","state.require_cut_current(&self.runtime)?",occurrence=n)
        for path,function in ((EFFECT,"read_original_final_use_binding"),(EFFECT,"publish_original_final_use"),(COMMAND,"bind_original_evaluated_selection_owner"),(COMMAND,"bind_original_evaluated_next_use_owner"),(PRODUCER,"prepare_evaluated_readiness_reader")):
            self.rejects(path,function,"self.read_original(&state)?")
        self.reject_each(EFFECT,"prepare_original",("state.require_cut_current(&self.runtime)?","self.read_original(state)"))

    def test_final_actual_source_cell_current_and_artifact_follow_live_reads(self):
        for n in (0,1):self.rejects(STATE,"read_original","state.require_cut_current(&self.runtime)?",occurrence=n)
        self.reject_each(STATE,"read_original",("let before = state.artifacts.read_current()?","let first = state.observe_phase()?","let last = state.observe_phase()?","let after = state.artifacts.read_current()?","artifact::require_same(&before, &after)?","if first != last"))
        source=(ROOT/STATE).read_text();first="let last = state.observe_phase()?;";last="let after = state.artifacts.read_current()?;"
        self.assertIn(first+"\n        "+last,source)
        self.rejects_source(STATE,source.replace(first+"\n        "+last,last+"\n        "+first,1))
        self.reject_each(STATE,"require_cut_current",("OriginalCellQ24DatasetCommandReadbackV1::verify_original_cut(","&actual != cut.dataset()","original.require_current(cut)","&shared.trainer, &shared.evaluator, PublicationAccess::Readback"))
        self.rejects_unused_branch(STATE,"require_cut_current","VersionCut::Evaluated(cut) => {")

    def test_once_custody_keeps_exact_original_final_use_and_actual_factory(self):
        self.reject_each(EFFECT,"prepare_original",("state.phase.take()","state.trainer.take()","state.evaluator.take()","crate::prepare_original_circuit_retained_publication_v1(","crate::prepare_original_circuit_evaluated_retention_v1(","cut.evaluated.clone_for_original_receipt()"))
        self.reject_each(EFFECT,"publish_original_final_use",("state.final_use_issuer.is_some()","self.publication_requested.swap(true, Ordering::AcqRel)","state.phase.take()","task.require_completed_a(original.completed())?","original.publish(signed)",".install_original(published, cut, intent)","state.shared_evaluated = Some(SharedEvaluatedReadbacks","trainer: Arc::new(trainer)","evaluator: Arc::new(evaluator)","self.read_original(&state)"))
        for marker in ("VersionCut::TrainingNoUpdate(cut) => {","VersionCut::Evaluated(cut) => {"):self.rejects_unused_branch(EFFECT,"prepare_original",marker)
        self.reject_each(PREPARED,"publish",("self,","PreparedOriginalCircuitRetainedPublicationV1::publish_and_retain_original_trainer(","PreparedOriginalCircuitEvaluatedRetentionV1::publish_and_retain_original_evidence(","*original, signed"))
        for marker in ("Self::TrainingNoUpdate(original) => {","Self::Evaluated(original) => {"):self.rejects_unused_branch(PREPARED,"publish",marker)

    def test_closed_factories_reject_fresh_owners_after_cold_or_missing_ack(self):
        for name,flag in (("bind_original_evaluated_selection_owner","selection_command_requested"),("bind_original_evaluated_next_use_owner","next_use_command_requested")):
            self.reject_each(COMMAND,name,("self: Arc<Self>","self."+flag+".swap(true, Ordering::AcqRel)","self.origin == RetainedVersionOriginV1::Recovered && !readback_only","if !readback_only","require_new_original_receipt(","self.bind_original_predecessor(&mut state)?","self.require_evaluated_command_context(","let before = self.read_original(&state)?","let after = self.read_original(&state)?","if before != after","state.shared_evaluated.as_ref().ok_or(Error::ReadbackRequired)?","Arc::clone(&shared.trainer)","Arc::clone(&shared.evaluator)","owner.into_evaluated_command_owner("))
            self.rejects(COMMAND,name,"self.origin == RetainedVersionOriginV1::Recovered && !readback_only","self.origin == RetainedVersionOriginV1::Recovered || !readback_only")
            self.rejects_unused_body(COMMAND,name)
            self.rejects_unused_branch(COMMAND,name,"tokio::task::spawn_blocking(move || {")
        self.reject_each(COMMAND,"bind_original_evaluated_selection_owner",("OriginalCircuitSelectionReceiptOwnerV1::original_command_profile(&owner)","OriginalCircuitLearningReadClientV1::require_original_evaluated_selection(","OriginalCircuitLearningReadClientV1::read_current(&live)","require_original_evaluated_version_selection("))
        self.reject_each(COMMAND,"bind_original_evaluated_next_use_owner",("OriginalCircuitNextUseReceiptOwnerV1::original_command_profile(&owner)","OriginalCircuitLearningReadClientV1::require_original_evaluated_next_use(","LearningIterationEvidenceClientV1::readback(","&signature != selection.attestation()","selection.original_receipt_predecessors("))
        self.reject_each(COMMAND,"require_evaluated_command_context",("RetainedVersionHostPhaseV1::Installed","RetainedVersionHostPhaseV1::Recovered","state.shared_evaluated.is_none()","context.snapshot() != cut.evaluated.snapshot()","context.receipt_context_binding() != cut.evaluated.receipt_context_binding()","scope != self.material.scope","verifier.trust_digest() != self.material.verifier.trust_digest()","verifier.scope_digest() != self.material.verifier.scope_digest()","verifier.objective_digest() != self.material.verifier.objective_digest()"))

    def test_original_shared_clients_and_readiness_channel_are_not_exported(self):
        for path,struct,fields in (
            (OLDHOST,"SharedEvaluatedReadbacks",("trainer","evaluator")),
            (PRODUCER,"OriginalCircuitEvaluatedReadinessChannelV1",("channel",)),
            (CLIENT,"OriginalCircuitRetainedVersionClientV1",("channel","cut","retained")),
            (READINESS,"OriginalCircuitEvaluatedCompletionReadinessClientV1",("context","material","dataset","binding","channel","retained")),
        ):
            source=(ROOT/path).read_text();code=PROOF._strip_rust_non_code(source);start=code.index("struct "+struct);end=PROOF._rust_item_end(code,start)+1
            for field in fields:
                match=re.search(r"(?m)^(\s*)"+field+r":",source[start:end]);self.assertIsNotNone(match,(path,field))
                at=start+match.start()+len(match.group(1))
                for visibility in ("pub ","pub(crate) ","pub(super) "):
                    self.rejects_source(path,source[:at]+visibility+source[at:])

    def test_readiness_uses_original_signed_five_cut_and_never_legacy_frames(self):
        self.reject_each(READINESS,"bind_original_stage_channel",("scope != material.scope","verifier.trust_digest() != material.verifier.trust_digest()","verifier.scope_digest() != material.verifier.scope_digest()","verifier.objective_digest() != material.verifier.objective_digest()","OriginalCircuitEvaluatedLearningReadContextV1::for_original_next_use(selection.clone())?","require_evaluated_next_use(&context)?","initial.snapshot() != &material.initial","&original_dataset != dataset.snapshot()","peer.check_peer_lifetime()?","owner.require_current_context(started)?"))
        self.reject_each(READINESS,"require_evaluated_next_use",("!matches!(context, ReadProfile::Evaluated(_))","context.mode()? != wire::Mode::NextUse"))
        self.reject_each(READINESS,"require_context",("require_evaluated_next_use(context)?","self.purpose != PURPOSE","!(1..=128).contains(&request_id)","context.require_request(&self.original, binding, request_id)"))
        self.rejects_unused_body(READINESS,"bind_original_stage_channel")

    def test_missing_pending_are_readiness_only_and_other_errors_remain_fatal(self):
        self.reject_each(PHYSICAL,"read_original_readiness",("self.require_task_input_current()?","self.context.decision()?","PublishedCircuitCellOwnerV1::read_learning_selection(","CircuitTaskSourceReadbackV1::read_run_publication(","Err(CircuitTaskErrorV1::ReconciliationRequired) => {","PublishedCircuitCellOwnerV1::snapshot(","Err(error) => return Err(Error::Source(error))","let current = self.read_original()?","current.source_publication != Some(before.publication_digest())","!= selection"))
        self.rejects(PHYSICAL,"read_original_readiness","Err(error) => return Err(Error::Source(error))","Err(_) => None")
        self.rejects_unused_branch(PHYSICAL,"read_original_readiness","Ok(before) => {")
        self.reject_each(READINESS_SERVER,"evaluated_readiness_response",("request.require_context(&self.context, self.binding, request_id)?","self.context.binding(started)? != self.binding","self.read_original_readiness()?","fresh < started || self.context.binding(fresh)? != self.binding","wire::OriginalRead::from_original(read)?","bytes.len() > 16_384"))

    def test_cancellation_queued_failure_and_completed_regression_consume_channel(self):
        self.reject_each(READINESS,"read_current",(".take().ok_or(Error::Unavailable)?","self.require_current_context(started)?","!(1..=128).contains(&channel.next_request_id)","request_id.checked_add(1)","cancelled.load(Ordering::Acquire)","channel.peer.request(&bytes)?","response.request.require_context(","channel.peer.check_peer_lifetime()?","current.as_ref() != Some(prior)","*self.channel.try_lock().map_err(|_| Error::Unavailable)? = Some(channel)"))
        self.rejects(READINESS,"read_current","current.as_ref() != Some(prior)","current.as_ref() == Some(prior)")
        self.rejects(READINESS,"drop","self.0.store(true, Ordering::Release)")
        self.rejects_unused_branch(READINESS,"read_current","tokio::task::spawn_blocking(move || {")
        for function in ("read_current","require_current_context"):self.rejects_unused_body(READINESS,function)

    def test_server_consumes_real_stream_pidfd_fixed_deadline_and_original_limits(self):
        self.reject_each(PRODUCER,"from_original_stream",("stream: UnixStream","original_consumer_pidfd: OwnedFd","timeout > Duration::from_millis(500)","lifetime > Duration::from_secs(300)","original_owner_command_channel_v1(","stream, consumer, consumer_uid, original_consumer_pidfd, timeout, lifetime"))
        self.reject_each(PRODUCER,"admit_original_readiness_server",("self.purpose != VersionPurpose::Evaluated","original.channel.check_peer_lifetime()?","Arc::clone(&self.connections).try_acquire_owned()"))
        self.reject_each(PRODUCER,"serve_original_evaluated_completion_readiness",("self.admit_original_readiness_server(&original)?","let mut channel = original.channel","channel.check_peer_lifetime()?","self.prepare_evaluated_readiness_reader(selection)?","self.serve_evaluated_readiness_frames("))
        self.reject_each(PRODUCER,"serve_evaluated_readiness_frames",("for request_id in 1..=128","require_not_cancelled(cancelled)?","self.require_lifetime()?","OriginalCircuitLearningReadOwnerV1::evaluated_readiness_response(","failure = Some(error)","failure.unwrap_or(Error::Transport(error))"))
        self.rejects(PRODUCER,"drop","self.0.store(true, Ordering::Release)")
        self.rejects(OLDHOST,"new","Semaphore::new(4)","Semaphore::new(5)")

    def test_host_readiness_is_from_held_c_and_rereads_owners_after_last_await(self):
        self.reject_each(PRODUCER,"prepare_evaluated_readiness_reader",("self.bind_original_predecessor(&mut state)?","selection.original_receipt_predecessors(","selection.original_context().snapshot() != cut.evaluated.snapshot()","selection.original_context().receipt_context_binding() != cut.evaluated.receipt_context_binding()","RetainedVersionHostPhaseV1::Installed","RetainedVersionHostPhaseV1::Recovered","OriginalCircuitEvaluatedLearningReadContextV1::for_original_next_use(selection)","OriginalCircuitLearningReadOwnerV1::from_original_evaluated_owners(","original.cell.clone()","original.source.as_ref().clone()","original.identity.clone()"))
        for n in (0,1):self.rejects(PRODUCER,"prepare_evaluated_readiness_reader","self.read_original(&state)?",occurrence=n)
        self.rejects_unused_body(PRODUCER,"prepare_evaluated_readiness_reader")
        self.rejects_unused_branch(PRODUCER,"serve_original_evaluated_completion_readiness","tokio::task::spawn_blocking(move || {")


if __name__=="__main__":unittest.main()
