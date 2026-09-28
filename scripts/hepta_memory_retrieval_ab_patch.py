"""Materialize reviewed A/B source edits only on their exact preimages.

Run without write credentials. Native rustfmt follows in the read-only job;
a separate publisher treats the resulting Rust files strictly as bounded data.
Line offsets are zero-based and preimage-bound. No qualification is claimed.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess

ROOT = "codex-rs/hepta-agentd/src/"
EDITS = {}
def item(name, before, edits):
    path = ROOT + name
    if path in EDITS:
        raise ValueError("duplicate path")
    EDITS[path] = (before, edits)

item("cognitive_context.rs", "3c972269bcffa638fd178254b41b79eda6c097e5", [
(982,982,'''    let deadline = request_work.deadline();
'''),
(984,985,'''            current.acquire_context_before(&owner, body_generation, deadline)
''')])
item("cognitive_retrieval_bootstrap.rs", "b98a0a59b5c2abb00cd3cec3354953468558cab8", [
(259,259,'''    fn acquire_context_before(
        &self,
        owner: &AgentId,
        body_generation: u64,
        deadline: std::time::Instant,
    ) -> Result<(RetrievalExecutionContextV1, Digest32, Option<u64>), String> {
        crate::cognitive_retrieval_context::check_retrieval_deadline(deadline)?;
        let bytes = read_host_file(&self.publication_path, MAX_PUBLICATION_BYTES)?;
        let publication = self.parsed.decode(&bytes, MAX_PUBLICATION_BYTES, decode_publication)?;
        self.inner.install_and_acquire_before(publication, owner, body_generation, deadline)
    }

''')])
item("cognitive_retrieval_context.rs", "26f525f3a4b82b7a12ddd9ee1a09f76825f6b223", [
(71,71,'''    /// Acquire within the request's existing absolute budget. Custom providers
    /// must override this to pass the deadline to blocking transports. The
    /// compatibility default rejects expired/late results but cannot preempt I/O.
    fn acquire_context_before(
        &self,
        owner: &AgentId,
        body_generation: u64,
        deadline: std::time::Instant,
    ) -> Result<(RetrievalExecutionContextV1, Digest32, Option<u64>), String> {
        check_retrieval_deadline(deadline)?;
        let result = self.acquire_context(owner, body_generation)?;
        check_retrieval_deadline(deadline)?;
        Ok(result)
    }

'''),
(87,87,'''
/// Expiry cannot be renewed by moving to another stage or provider operation.
pub(crate) fn check_retrieval_deadline(deadline: std::time::Instant) -> Result<(), String> {
    if std::time::Instant::now() >= deadline {
        Err("retrieval provider request deadline exceeded".to_string())
    } else {
        Ok(())
    }
}
''')])
item("cognitive_retrieval_learning.rs", "ab31feb45423e3c05641b8d2e0579ada380f5738", [
(29,29,'''    }

    /// Read-only reconciliation across the two existing durable owners. This
    /// does not create a second delivery journal or upgrade prepared events.
    /// The host must supply its expected native binding, not one copied from an
    /// untrusted receipt. A missing/revoked preparation fails closed.
    pub fn native_delivery_receipt(
        &self,
        preparation_record_id: &StableId,
        binding: &crate::retrieval_delivery::RetrievalNativeBindingV1,
        native_owner: &codex_hepta_infer_core::durable_control::DurableInferenceControl,
    ) -> Result<crate::retrieval_delivery::RetrievalDeliveryReceiptV1, String> {
        let writer = self.writer.lock()
            .map_err(|_| "retrieval learning ledger writer lock poisoned".to_string())?;
        // This is an offline reconciliation port, not the latency-sensitive
        // append path. Replay reuses the canonical correction/revocation rules.
        let ledger = codex_hepta_learning_ledger::LearningLedger::from_snapshot(
            writer.snapshot().map_err(|error| error.to_string())?,
        ).map_err(|error| error.to_string())?;
        let record = ledger.active_records().into_iter()
            .find(|record| record.event.record_id() == preparation_record_id)
            .ok_or_else(|| "retrieval preparation is absent or inactive".to_string())?;
        let LedgerEvent::RetrievalPrepared(preparation) = &record.event else {
            return Err("record is not a tag-10 retrieval preparation".to_string());
        };
        crate::retrieval_delivery::verify_retrieval_delivery_v1(
            preparation,
            binding,
            native_owner.native_record(&binding.request_id),
        )
        .map_err(|error| error.to_string())
''')])
item("cognitive_retrieval_learning_tests.rs", "7f9128674ee16340374089167d31b9e4283d58b6", [
(320,320,'''
#[test]
fn durable_native_reopen_never_promotes_write_ahead_dispatch_to_exposure() {
    use crate::retrieval_delivery::RetrievalDeliveryStageV1;
    use crate::retrieval_delivery::RetrievalNativeBindingV1;
    use codex_hepta_infer_core::durable_control::DurableInferenceControl;
    use codex_hepta_infer_core::durable_control::native::NativeDispatch;
    use codex_hepta_infer_core::durable_control::native::NativeRequest;
    use serde_json::json;

    let (temp, sink) = sink();
    let observation = observation("durable-reconciliation");
    let context = digest("exact-response");
    let first = sink.append_preparation(
        &owner(), 1, 707, &observation, &observation.selected_candidates,
        Some(context), None, ProbabilityQ32::ONE,
    ).expect("durable preparation");
    let snapshot = sink.writer.lock().expect("lock").snapshot().expect("snapshot");
    let preparation_id = snapshot.records()[0].event.record_id().clone();
    let binding = RetrievalNativeBindingV1 {
        request_id: "native-request".to_string(),
        principal_id: "principal".to_string(),
        worker_generation: 7,
    };
    let journal_path = temp.path().join("native.journal");
    let mut native = DurableInferenceControl::open(&journal_path, 16).expect("native owner");
    let prepared = sink.native_delivery_receipt(&preparation_id, &binding, &native).expect("prepared");
    assert_eq!(prepared.stage, RetrievalDeliveryStageV1::AssignmentPrepared);
    native.reserve_native(NativeRequest {
        request_id: binding.request_id.clone(), principal_id: binding.principal_id.clone(),
        worker_generation: binding.worker_generation, model: "model".to_string(),
        payload_digest: digest("payload").to_string(),
    }, 2).expect("reserve");
    let dispatch: NativeDispatch = serde_json::from_value(json!({
        "thread_id": "thread", "model_provider": "provider",
        "context_digest": digest("additional-context").to_string(),
        "owner_context_digest": context.to_string(),
    })).expect("dispatch");
    native.dispatch_native(&binding.request_id, dispatch).expect("write-ahead dispatch");
    let before_crash = sink.native_delivery_receipt(&preparation_id, &binding, &native).expect("WAL");
    assert_eq!(before_crash.stage, RetrievalDeliveryStageV1::AssignmentPrepared);
    drop(native);
    let mut native = DurableInferenceControl::open(&journal_path, 16).expect("reopen");
    let after_crash = sink.native_delivery_receipt(&preparation_id, &binding, &native).expect("reconcile");
    assert_eq!(after_crash, before_crash);
    native.native_started(&binding.request_id, "turn".to_string()).expect("durable native start");
    let started = sink.native_delivery_receipt(&preparation_id, &binding, &native).expect("start");
    assert_eq!(started.stage, RetrievalDeliveryStageV1::NativeStarted);
    drop(native);
    let native = DurableInferenceControl::open(&journal_path, 16).expect("reopen started");
    assert_eq!(sink.native_delivery_receipt(&preparation_id, &binding, &native).expect("stable"), started);
    let replay = sink.append_preparation(
        &owner(), 1, 707, &observation, &observation.selected_candidates,
        Some(context), None, ProbabilityQ32::ONE,
    ).expect("idempotent retry");
    assert_eq!(replay.event_digest, first.event_digest);
    assert_eq!(replay.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(sink.writer.lock().expect("lock").snapshot().expect("snapshot").records().len(), 1);
    assert!(sink.native_delivery_receipt(&id("absent"), &binding, &native).is_err());
    let wrong = RetrievalNativeBindingV1 { principal_id: "another-principal".to_string(), ..binding };
    assert!(sink.native_delivery_receipt(&preparation_id, &wrong, &native).is_err());
}
''')])
item("cognitive_retrieval_provider_core.rs", "e3fcdcc82d46fc7be190464810e7964d69ea683e", [
(83,83,'''    /// The concrete product transport overrides this and bounds every syscall.
    /// Legacy owners only get before/after expiry checks; they remain supervised
    /// and charged until their actual operation exits.
    fn observe_before(
        &self,
        owner: &AgentId,
        body_generation: u64,
        challenge: [u8; 32],
        deadline: Instant,
    ) -> Result<MemoryRetrievalFrontierV1, String> {
        crate::cognitive_retrieval_context::check_retrieval_deadline(deadline)?;
        let result = self.observe(owner, body_generation, challenge)?;
        crate::cognitive_retrieval_context::check_retrieval_deadline(deadline)?;
        Ok(result)
    }

'''),
(142,143,'''        self.install_observed(publication, None).map(|_| ())
'''),
(155,156,'''        let frontier = self.install_observed(publication, None)?;
'''),
(157,157,'''    }

    /// Request-scoped variant: publication parsing, verification and frontier
    /// observation consume the caller's deadline without restarting its clock.
    pub fn install_and_acquire_before(
        &self,
        publication: SignedMemoryRetrievalContextV1,
        owner: &AgentId,
        body_generation: u64,
        deadline: Instant,
    ) -> Result<(RetrievalExecutionContextV1, Digest32, Option<u64>), String> {
        self.check_identity(owner, body_generation)?;
        crate::cognitive_retrieval_context::check_retrieval_deadline(deadline)?;
        let frontier = self.install_observed(publication, Some(deadline))?;
        let result = self.acquire_observed(frontier)?;
        crate::cognitive_retrieval_context::check_retrieval_deadline(deadline)?;
        Ok(result)
'''),
(169,169,'''        deadline: Option<Instant>,
'''),
(170,170,'''        if let Some(deadline) = deadline {
            crate::cognitive_retrieval_context::check_retrieval_deadline(deadline)?;
        }
'''),
(198,199,'''        let frontier = self.observe_frontier_before(deadline)?;
'''),
(258,258,'''        self.observe_frontier_before(None)
    }

    fn observe_frontier_before(&self, deadline: Option<Instant>) -> Result<FrontierIdentity, String> {
        if let Some(deadline) = deadline {
            crate::cognitive_retrieval_context::check_retrieval_deadline(deadline)?;
        }
'''),
(262,265,'''        let response = match deadline {
            Some(deadline) => self.frontier_owner.observe_before(
                &self.owner, self.body_generation, challenge, deadline,
            )?,
            None => self.frontier_owner.observe(&self.owner, self.body_generation, challenge)?,
        };
'''),
(311,311,'''    fn acquire_context_before(
        &self,
        owner: &AgentId,
        body_generation: u64,
        deadline: Instant,
    ) -> Result<(RetrievalExecutionContextV1, Digest32, Option<u64>), String> {
        self.check_identity(owner, body_generation)?;
        let frontier = self.observe_frontier_before(Some(deadline))?;
        let result = self.acquire_observed(frontier)?;
        crate::cognitive_retrieval_context::check_retrieval_deadline(deadline)?;
        Ok(result)
    }

''')])
item("cognitive_retrieval_provider_tests.rs", "682460e397cb7cb40d5216f8b3a688290b9abc6e", [
(349,349,'''
#[test]
fn expired_request_cannot_install_or_reuse_a_signed_publication() {
    let (publication, _frontier, provider) = fixture();
    let expired = Instant::now();
    assert!(provider.install_and_acquire_before(publication, &owner(), 9, expired).is_err());
    assert!(provider.acquire_context_before(&owner(), 9, expired).is_err());
}
''')])
item("cognitive_retrieval_transport.rs", "716a90dc7d2ccc2d873e52f492c695541108c844", [
(70,70,'''        self.observe_before(owner, body_generation, challenge, deadline)
    }

    fn observe_before(
        &self,
        owner: &AgentId,
        body_generation: u64,
        challenge: [u8; 32],
        request_deadline: Instant,
    ) -> Result<MemoryRetrievalFrontierV1, String> {
        let configured_deadline = Instant::now()
            .checked_add(self.timeout)
            .ok_or_else(|| "retrieval frontier deadline overflow".to_string())?;
        let deadline = request_deadline.min(configured_deadline);
        remaining(deadline)?;
''')])
item("cognitive_retrieval_transport_tests.rs", "a3179e7f82353c1deb0fd5b85cc7c8fad65d8d1e", [
(181,181,'''
#[test]
fn expired_request_budget_does_not_contact_the_frontier_owner() {
    let listener = TcpListener::bind("127.0.0.1:0").expect("listener");
    listener.set_nonblocking(true).expect("nonblocking");
    let client = LoopbackFrontierClient::new(listener.local_addr().expect("address"), Duration::from_secs(5)).expect("client");
    assert!(client.observe_before(&owner(), 9, [7; 32], Instant::now()).is_err());
    assert_eq!(listener.accept().expect_err("no connection").kind(), std::io::ErrorKind::WouldBlock);
}

#[test]
fn request_deadline_wins_over_a_long_configured_provider_timeout() {
    let listener = TcpListener::bind("127.0.0.1:0").expect("listener");
    let endpoint = listener.local_addr().expect("address");
    let (released_tx, released_rx) = std::sync::mpsc::channel();
    let server = std::thread::spawn(move || {
        let (mut socket, _) = listener.accept().expect("accept");
        socket.set_read_timeout(Some(Duration::from_secs(2))).expect("bound server");
        let mut buffer = [0_u8; 512];
        loop {
            match socket.read(&mut buffer) {
                Ok(0) => break,
                Ok(_) => {},
                Err(_) => return false,
            }
        }
        released_tx.send(()).expect("release observed");
        true
    });
    let client = LoopbackFrontierClient::new(endpoint, Duration::from_secs(5)).expect("client");
    assert!(client.observe_before(&owner(), 9, [7; 32], Instant::now() + Duration::from_millis(100)).is_err());
    released_rx.recv_timeout(Duration::from_secs(2)).expect("socket closed after request expiry");
    assert!(server.join().expect("server"));
}
''')])
item("retrieval_delivery.rs", "89901c72860fd85d08b0303a3e41b1178c7f73df", [
(15,16,'''use codex_hepta_learning_ledger::RetrievalPreparationFactV1;
'''),
(20,21,'''const RECEIPT_DOMAIN: &[u8] = b"hepta.retrieval-native-delivery-receipt.v3";
'''),
(24,26,'''    /// An idempotent preparation is durable. Later freshness fences may still
    /// fail. Neither publication nor consumer use is claimed.
'''),
(40,40,'''    pub native_principal_id: String,
    pub native_worker_generation: u64,
'''),
(43,43,'''    /// Exact candidate identities in prepared position order, never a sorted set.
    pub prepared_candidate_digests: Vec<Digest32>,
'''),
(53,53,'''/// The native owner supplies the expected run identity independently of the
/// record being inspected. Context equality alone cannot correlate two runs.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalNativeBindingV1 {
    pub request_id: String,
    pub principal_id: String,
    pub worker_generation: u64,
}

'''),
(55,55,'''        if self.native_principal_id.is_empty() || self.native_worker_generation == 0 {
            return Err(RetrievalDeliveryError::NativeIdentityMismatch);
        }
'''),
(64,64,'''        }
        if self.prepared_candidate_digests.len() > 16
            || self.prepared_candidate_digests.iter().any(|value| value.is_zero())
            || self.prepared_candidate_digests.iter().collect::<std::collections::BTreeSet<_>>().len()
                != self.prepared_candidate_digests.len()
            || self.context_digest.is_some() == self.prepared_candidate_digests.is_empty()
        {
            return Err(RetrievalDeliveryError::AssignmentPreparationMismatch);
        }
        if self.native_request_id.as_ref().is_some_and(|value| value.is_empty())
            || self.native_revision == Some(0)
            || self.turn_id.as_ref().is_some_and(|value| value.is_empty())
        {
            return Err(RetrievalDeliveryError::InvalidStageEvidence);
'''),
(119,119,'''        push_text(&mut bytes, &self.native_principal_id);
        bytes.extend_from_slice(&self.native_worker_generation.to_be_bytes());
'''),
(120,120,'''        bytes.extend_from_slice(&(self.prepared_candidate_digests.len() as u64).to_be_bytes());
        for candidate in &self.prepared_candidate_digests {
            bytes.extend_from_slice(candidate.as_array());
        }
'''),
(144,144,'''    NativeIdentityMismatch,
'''),
(162,163,'''/// Join a tag-10 unexposed preparation with one independently named native run.
/// Inputs must come from their owning durable stores, not caller wire structs.
/// The returned digest is an integrity receipt, never an authority credential.
'''),
(170,171,'''    preparation: &RetrievalPreparationFactV1,
    binding: &RetrievalNativeBindingV1,
'''),
(173,176,'''    preparation
        .validate()
        .map_err(|_| RetrievalDeliveryError::AssignmentPreparationMismatch)?;
    if binding.request_id.is_empty()
        || binding.principal_id.is_empty()
        || binding.worker_generation == 0
        || native.is_some_and(|record| {
            record.request.request_id != binding.request_id
                || record.request.principal_id != binding.principal_id
                || record.request.worker_generation != binding.worker_generation
                || record.revision == 0
        })
'''),
(177,178,'''        return Err(RetrievalDeliveryError::NativeIdentityMismatch);
'''),
(179,182,'''    let prepared = preparation.prepared_context_digest;
'''),
(228,228,'''            if record.pre_dispatch_stop.is_some()
                && (record.turn_id.is_some() || record.observation.is_some()
                    || record.dispatch_rejection.is_some())
            {
                return Err(RetrievalDeliveryError::InvalidStageEvidence);
            }
'''),
(229,229,'''                if record.turn_id.is_some() || record.observation.is_some()
                    || record.dispatch_rejection.is_some()
                {
                    return Err(RetrievalDeliveryError::InvalidStageEvidence);
                }
'''),
(230,231,'''                    preparation,
                    binding,
'''),
(295,296,'''                    if observation.turn_id != *turn_id
                        || observation.thread_id != dispatch.thread_id
                        || observation.model != record.request.model
                        || observation.model_provider != dispatch.model_provider
                    {
'''),
(322,323,'''        preparation,
        binding,
'''),
(332,332,'''#[allow(clippy::too_many_arguments)]
'''),
(333,334,'''    preparation: &RetrievalPreparationFactV1,
    binding: &RetrievalNativeBindingV1,
'''),
(342,343,'''        assignment_record_id: preparation.assignment.record_id.clone(),
'''),
(344,345,'''        native_principal_id: binding.principal_id.clone(),
        native_worker_generation: binding.worker_generation,
        context_digest: preparation.prepared_context_digest,
        prepared_candidate_digests: preparation
            .prepared_candidate_indices
            .iter()
            .map(|index| {
                preparation.assignment.enumerated_candidate_digests
                    .get(*index as usize)
                    .copied()
                    .ok_or(RetrievalDeliveryError::AssignmentPreparationMismatch)
            })
            .collect::<Result<Vec<_>, _>>()?,
''')])
item("retrieval_delivery_tests.rs", "4f0e697b96f211a370c564f199aa42800e0a30a0", [
(26,28,'''fn assignment(prepared: bool) -> RetrievalPreparationFactV1 {
    RetrievalPreparationFactV1 {
        assignment: RetrievalAssignmentFact {
'''),
(38,41,'''        delivered_candidate_indices: Vec::new(),
        context_exposed: false,
        published_context_digest: None,
'''),
(47,47,'''        },
        prepared_candidate_indices: prepared.then_some(0).into_iter().collect(),
        prepared_context_digest: prepared.then(|| digest("prepared-context")),
    }
}

fn binding() -> RetrievalNativeBindingV1 {
    RetrievalNativeBindingV1 {
        request_id: "native-request".to_string(),
        principal_id: "principal".to_string(),
        worker_generation: 7,
'''),
(91,92,'''    let prepared = verify_retrieval_delivery_v1(&assignment, &binding(), None).expect("prepared");
'''),
(96,97,'''    let mut run = native(assignment.prepared_context_digest);
'''),
(98,99,'''        verify_retrieval_delivery_v1(&assignment, &binding(), Some(&run)).expect("dispatch prepared");
'''),
(113,114,'''        verify_retrieval_delivery_v1(&assignment, &binding(), Some(&run)).expect("published response");
'''),
(124,125,'''    let started = verify_retrieval_delivery_v1(&assignment, &binding(), Some(&run)).expect("started");
'''),
(143,144,'''    let outcome = verify_retrieval_delivery_v1(&assignment, &binding(), Some(&run)).expect("outcome");
'''),
(152,153,'''    let mut run = native(assignment.prepared_context_digest);
'''),
(154,155,'''    let unknown = verify_retrieval_delivery_v1(&assignment, &binding(), Some(&run)).expect("unknown");
'''),
(159,160,'''    let aborted = verify_retrieval_delivery_v1(&assignment, &binding(), Some(&run)).expect("aborted");
'''),
(166,169,'''    let run = native(assignment.prepared_context_digest);
    let first = verify_retrieval_delivery_v1(&assignment, &binding(), Some(&run)).expect("first");
    let replay = verify_retrieval_delivery_v1(&assignment, &binding(), Some(&run)).expect("replay");
'''),
(178,179,'''        verify_retrieval_delivery_v1(&unprepared, &binding(), Some(&run)),
'''),
(185,186,'''        verify_retrieval_delivery_v1(&prepared, &binding(), Some(&wrong)),
'''),
(193,194,'''    let mut run = native(assignment.prepared_context_digest);
'''),
(211,212,'''        verify_retrieval_delivery_v1(&assignment, &binding(), Some(&run)),
'''),
(215,215,'''
#[test]
fn legacy_exposure_flags_are_not_accepted_as_a_preparation() {
    let mut prepared = assignment(true);
    prepared.assignment.context_exposed = true;
    assert_eq!(
        verify_retrieval_delivery_v1(&prepared, &binding(), None),
        Err(RetrievalDeliveryError::AssignmentPreparationMismatch)
    );
}

#[test]
fn equal_context_cannot_join_another_native_request_or_owner() {
    let prepared = assignment(true);
    for field in 0..3 {
        let mut run = native(prepared.prepared_context_digest);
        match field {
            0 => run.request.request_id = "other-request".to_string(),
            1 => run.request.principal_id = "other-principal".to_string(),
            _ => run.request.worker_generation += 1,
        }
        assert_eq!(
            verify_retrieval_delivery_v1(&prepared, &binding(), Some(&run)),
            Err(RetrievalDeliveryError::NativeIdentityMismatch)
        );
    }
}

#[test]
fn preparation_bounds_and_selected_membership_are_checked_before_join() {
    for indices in [vec![0, 0], vec![1], vec![u32::MAX], vec![0; 17]] {
        let mut prepared = assignment(true);
        prepared.prepared_candidate_indices = indices;
        assert_eq!(
            verify_retrieval_delivery_v1(&prepared, &binding(), None),
            Err(RetrievalDeliveryError::AssignmentPreparationMismatch)
        );
    }
    let mut prepared = assignment(true);
    prepared.assignment.selected_candidate_indices.clear();
    assert_eq!(
        verify_retrieval_delivery_v1(&prepared, &binding(), None),
        Err(RetrievalDeliveryError::AssignmentPreparationMismatch)
    );
}

#[test]
fn receipt_preserves_positions_and_binds_the_order() {
    let mut prepared = assignment(true);
    prepared.assignment.enumerated_candidate_digests.push(digest("second"));
    prepared.assignment.legal_candidate_indices.push(1);
    prepared.assignment.selected_candidate_indices.push(1);
    prepared.prepared_candidate_indices = vec![1, 0];
    let first = verify_retrieval_delivery_v1(&prepared, &binding(), None).expect("receipt");
    assert_eq!(first.prepared_candidate_digests, vec![digest("second"), digest("candidate")]);
    prepared.prepared_candidate_indices.reverse();
    let reordered = verify_retrieval_delivery_v1(&prepared, &binding(), None).expect("receipt");
    assert_ne!(first.receipt_digest, reordered.receipt_digest);
    let mut tampered = first;
    tampered.prepared_candidate_digests.reverse();
    assert_eq!(tampered.validate(), Err(RetrievalDeliveryError::DigestMismatch));
}
''')])
item("retrieval_executor.rs", "6fffb8f4b069d23f613e67eddff68fe62d3f8cf2", [
(6,6,'''use std::sync::atomic::AtomicU8;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
'''),
(22,22,'''    next_worker_id: AtomicU64,
'''),
(29,29,'''            next_worker_id: AtomicU64::new(1),
'''),
(60,61,'''            b"hepta.retrieval.executor.v4:delivery=2,800ms;shadow=1,40ms,parent-bounded;work=250000;queue=0;async=owned-supervised;shadow-cancellation=independent;provider-deadline=request-absolute;worker-exit=observed",
'''),
(81,81,'''        let worker_id = self.next_worker_id.fetch_update(
            Ordering::Relaxed, Ordering::Relaxed, |value| value.checked_add(1),
        ).map_err(|_| "retrieval worker identity exhausted".to_string())?;
        let activity = Arc::new(WorkerActivity {
            id: worker_id, class: request.class, started: Instant::now(), state: AtomicU8::new(0),
        });
        let worker_exit = WorkerExit(Arc::clone(&activity));
'''),
(84,84,'''            activity,
'''),
(91,91,'''            let _worker_exit = worker_exit;
'''),
(124,128,'''        request.checkpoint()?;
'''),
(135,135,'''        let worker_id = self.next_worker_id.fetch_update(
            Ordering::Relaxed, Ordering::Relaxed, |value| value.checked_add(1),
        ).map_err(|_| "retrieval worker identity exhausted".to_string())?;
        let activity = Arc::new(WorkerActivity {
            id: worker_id, class: request.class, started: Instant::now(), state: AtomicU8::new(0),
        });
        let worker_exit = WorkerExit(Arc::clone(&activity));
'''),
(138,138,'''            activity,
'''),
(142,142,'''            let _worker_exit = worker_exit;
'''),
(175,175,'''    pub(crate) fn deadline(&self) -> Instant {
        self.deadline
    }

'''),
(190,190,'''struct WorkerActivity {
    id: u64,
    class: RetrievalWorkClass,
    started: Instant,
    // 0 = owned, 1 = abandoned waiter / still owned, 2 = actual exit.
    state: AtomicU8,
}

struct WorkerExit(Arc<WorkerActivity>);

impl Drop for WorkerExit {
    fn drop(&mut self) {
        let previous = self.0.state.swap(2, Ordering::AcqRel);
        if previous == 1 {
            tracing::warn!(worker_id = self.0.id, class = ?self.0.class,
                elapsed_ms = u64::try_from(self.0.started.elapsed().as_millis()).unwrap_or(u64::MAX),
                "abandoned retrieval worker actually exited");
        } else {
            tracing::debug!(worker_id = self.0.id, class = ?self.0.class,
                "retrieval worker actually exited");
        }
    }
}

'''),
(192,192,'''    activity: Arc<WorkerActivity>,
'''),
(199,199,'''            if self.activity.state.compare_exchange(0, 1, Ordering::AcqRel, Ordering::Acquire).is_ok() {
                tracing::warn!(worker_id = self.activity.id, class = ?self.activity.class,
                    "retrieval waiter abandoned; worker retains capacity until actual exit");
            }
''')])
item("retrieval_executor_tests.rs", "eee1320901b1d9e12dff048bfe19e48d95094b18", [
(147,147,'''
#[test]
fn actual_worker_exit_and_abandonment_are_monotonic_observations() {
    let activity = Arc::new(WorkerActivity {
        id: 1, class: RetrievalWorkClass::Delivery, started: Instant::now(), state: AtomicU8::new(0),
    });
    let exit = WorkerExit(Arc::clone(&activity));
    let control = RecallWorkControlV1::bounded(Instant::now() + Duration::from_secs(1), 10);
    drop(CancelOnDrop { control, activity: Arc::clone(&activity), armed: true });
    assert_eq!(activity.state.load(Ordering::Acquire), 1);
    drop(exit);
    assert_eq!(activity.state.load(Ordering::Acquire), 2);
    let control = RecallWorkControlV1::bounded(Instant::now() + Duration::from_secs(1), 10);
    drop(CancelOnDrop { control, activity: Arc::clone(&activity), armed: true });
    assert_eq!(activity.state.load(Ordering::Acquire), 2);
}
''')])
EDITS["codex-rs/hepta-learning-ledger/src/retrieval_preparation.rs"] = (
"9304077f978ab5ebdb4ecffef2703bf1712ccc7e", [(27,27,'''    /// Validate the same bounded shape, provenance digests and index relations
    /// as the owner ledger without appending a fact or granting authority.
    pub fn validate(&self) -> Result<(), LedgerError> {
        self.validate_unexposed()?;
        crate::LearningLedger::new()
            .prepare(LedgerEvent::RetrievalPrepared(self.clone()))
            .map(|_| ())
    }

''')])

def blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()

def materialize(root):
    root = Path(root).resolve()
    prepared = {}
    for name, (before, edits) in EDITS.items():
        path = root / name
        if path.is_symlink() or path.resolve() != path or not path.is_file():
            raise ValueError("unsafe path: " + name)
        raw = path.read_bytes()
        if len(raw) > 500_000 or blob(raw) != before:
            raise ValueError("source preimage changed: " + name)
        lines = raw.decode("utf-8").splitlines(keepends=True)
        previous = 0
        for start, end, text in edits:
            if not previous <= start <= end <= len(lines) or not isinstance(text, str):
                raise ValueError("overlapping or invalid edit: " + name)
            previous = end
        for start, end, text in reversed(edits):
            lines[start:end] = [text]
        result = "".join(lines).encode()
        if len(result) > 500_000:
            raise ValueError("source postimage exceeds bound")
        prepared[name] = result
    for name, raw in prepared.items():
        (root / name).write_bytes(raw)

def manifest(root, output):
    root = Path(root).resolve()
    changed = set(subprocess.check_output(["git", "-C", str(root), "diff", "HEAD", "--name-only"], text=True).splitlines())
    if changed != set(EDITS):
        raise ValueError("changed paths differ from reviewed scope")
    changes = []
    for name, (before, _) in sorted(EDITS.items()):
        path = root / name
        if path.is_symlink() or path.resolve() != path:
            raise ValueError("redirected source")
        raw = path.read_bytes()
        changes.append({"path": name, "before": before, "after": blob(raw), "content": raw.decode("utf-8")})
    Path(output).write_text(json.dumps({"base": os.environ["GITHUB_SHA"], "patch_blob": os.environ["PATCH_BLOB"], "changes": changes}))

if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["apply"]:
        materialize(Path.cwd())
    elif len(sys.argv) == 3 and sys.argv[1] == "manifest":
        manifest(Path.cwd(), sys.argv[2])
    else:
        raise SystemExit("usage: script apply | manifest OUTPUT")
