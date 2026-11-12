//! Explicit same-process transport and future B clock for mechanisms only.
//! All successful material bytes originate in the actual consumed Panel host.
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_neuron::CellBackendManifestV2;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use super::*;
use super::super::codec::Body;
use crate::OriginalCellEvaluationHostV1;

type Peer = std::thread::JoinHandle<anyhow::Result<u64>>;
type Pause = (std::sync::mpsc::Sender<()>, std::sync::mpsc::Receiver<()>);

fn fixture_channel(stream: UnixStream) -> anyhow::Result<HostAuthorityPeerChannel> {
    Ok(HostAuthorityPeerChannel::from_stream(stream, HostAuthorityPeerPolicy {
        peer: HostIssuerPeer { uid: rustix::process::geteuid().as_raw(), pid: std::process::id() },
        timeout: Duration::from_secs(/*secs*/ 30), lifetime: Duration::from_secs(/*secs*/ 300),
        request_bound: 16_384, response_bound: 16_384,
    }, rustix::process::pidfd_open(rustix::process::getpid(), rustix::process::PidfdFlags::empty())?)?)
}

impl OriginalCellEvaluationHostV1 {
    pub(crate) fn fixture_model_material_commands(
        self: &Arc<Self>, expected: Option<Receipt>, fault: &'static str,
        pause: Option<Pause>,
    ) -> anyhow::Result<(OriginalCellEvaluationModelMaterialClientV1, Peer)> {
        let current = self.owners.try_lock().map_err(|_| anyhow::anyhow!("original Evaluator lock"))?
            .current_time()?;
        let (stream, server) = UnixStream::pair()?;
        let connection = OriginalCellEvaluationModelMaterialConnectionV1 {
            channel: fixture_channel(stream)?, initial: self.context.initial()?,
            scope: self.context.scope.clone(), registration: self.context.registration.clone(),
            verifier: self.context.verifier.clone(), observed_at: current,
        };
        connection.require_initial(&self.context.initial()?, &self.context.scope,
            &self.context.registration, &self.context.verifier)?;
        let mut other_initial = self.context.initial()?;
        other_initial.request.evaluation_profile = Digest32::ZERO;
        assert!(connection.require_initial(&other_initial, &self.context.scope,
            &self.context.registration, &self.context.verifier).is_err());
        let client = OriginalCellEvaluationModelMaterialClientV1 {
            channel: Mutex::new(Some(Channel { peer: connection.channel, next: 1 })),
            context: self.context.clone(), expected: Mutex::new(expected),
            binding: wire::context_binding(&self.context, current)?, observed_at: current,
            retained: Mutex::new(None),
        };
        let owner = Arc::clone(self);
        let channel = fixture_channel(server)?;
        let peer = std::thread::spawn(move || owner.fixture_model_material_server(channel, fault, pause));
        Ok((client, peer))
    }

    pub(crate) fn fixture_model_material_renewed_evaluation(
        &self, original: &Receipt, current: u64,
    ) -> anyhow::Result<Receipt> {
        let mut signed = original.attestation().clone();
        signed.expires_at = signed.expires_at.checked_add(1)
            .ok_or_else(|| anyhow::anyhow!("original test signature expiry"))?;
        signed.signature = SigningKey::from_bytes(&[42; 32]).sign(&signed.signing_bytes()).to_bytes();
        let renewed = super::super::super::wire::authenticate_completed(
            &self.context, original.snapshot().clone(), signed, current,
        )?;
        assert_ne!(&renewed, original);
        Ok(renewed)
    }

    pub(crate) async fn fixture_model_material_cancel_queued(self: &Arc<Self>) -> anyhow::Result<()> {
        let current = self.owners.try_lock().map_err(|_| anyhow::anyhow!("original Evaluator lock"))?
            .current_time()?;
        let (client, peer) = self.fixture_model_material_commands(
            /*expected*/ None, "original", /*pause*/ None,
        )?;
        tokio::task::spawn_blocking(move || -> anyhow::Result<()> {
            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_all().max_blocking_threads(/*val*/ 1).build()?;
            runtime.block_on(async move {
                let (occupied, waiting) = tokio::sync::oneshot::channel();
                let (release, blocked) = std::sync::mpsc::channel();
                let blocker = tokio::task::spawn_blocking(move || -> anyhow::Result<()> {
                    let _ = occupied.send(());
                    blocked.recv().map_err(|_| anyhow::anyhow!("release queued material read"))?;
                    Ok(())
                });
                waiting.await?;
                let mut request = Box::pin(client.read_current_with_clock(|| Ok(current)));
                let pending = std::future::poll_fn(|cx| std::task::Poll::Ready(
                    std::future::Future::poll(request.as_mut(), cx).is_pending(),
                )).await;
                drop(request);
                release.send(())?;
                blocker.await??;
                assert!(pending, "the actual readonly request was queued");
                assert!(matches!(client.read_current().await, Err(Error::Unavailable)));
                drop(client);
                assert_eq!(peer.join().expect("original material peer")?, 0);
                Ok(())
            })
        }).await.map_err(|_| anyhow::anyhow!("queued material runtime"))?
    }
}

impl OriginalCellEvaluationModelMaterialClientV1 {
    pub(crate) async fn fixture_read_current_at(&self, current: u64)
        -> Result<OriginalCellEvaluationModelMaterialV1, Error>
    {
        self.read_current_with_clock(|| Ok(current)).await
    }

    pub(crate) fn fixture_exhaust_original_material_session(&self) -> anyhow::Result<()> {
        self.channel.try_lock().map_err(|_| anyhow::anyhow!("original material channel"))?
            .as_mut().ok_or_else(|| anyhow::anyhow!("missing original material channel"))?.next = 129;
        Ok(())
    }
}

impl OriginalCellEvaluationModelMaterialV1 {
    pub(crate) fn fixture_original_material_pages(&self) -> usize {
        self.bytes.len().div_ceil(PAGE_BYTES)
    }

    pub(crate) fn fixture_original_material_preimages(&self, current: u64) -> anyhow::Result<()> {
        self.authenticate_current(current)?;
        let checked = verify::material(&self.context, &self.evaluation, &self.bytes, current)?;
        assert!(!checked.qualified, "actual B and nonempty retention are Ineligible in this fixture");
        assert!(matches!(self.require_original_model_input(&self.context.training,
            &self.context.training_evidence, current), Err(Error::Binding("NoUpdate has no model proposal"))));
        let body = Body::decode(&self.bytes)?;
        assert_eq!(body.members.len(), 2);
        assert!(self.fixture_original_material_pages() > 1);
        assert!(self.fixture_original_material_pages() <= MAX_PAGES);
        let raw = &body.members[0];
        let record: serde_json::Value = serde_json::from_slice(&raw.record)?;
        let candidate: CellBackendManifestV2 = serde_json::from_value(record["candidate"]["manifest"].clone())?;
        let baseline: CellBackendManifestV2 = serde_json::from_value(record["fixed_expert"]["manifest"].clone())?;
        let candidate_cut: Digest32 = serde_json::from_value(record["candidate"]["journal_cut"].clone())?;
        let baseline_cut: Digest32 = serde_json::from_value(record["fixed_expert"]["journal_cut"].clone())?;
        let generator = self.context.authenticate(current)?;
        let original = super::super::member::verify(raw, &self.context,
            self.context.registration.primary(), &generator, current)?;
        let training = self.context.training.receipts.last().expect("actual Training");
        // The literal pre-refactor local algorithm, with the same actual
        // original inputs. No Qualified receipt or Model seal is synthesized.
        let local = Digest32::of_parts(&[
            b"hepta.cell.q24.model-proposal-material.v1\0", training.evidence_digest.as_array(),
            &serde_json::to_vec(&candidate)?, &serde_json::to_vec(&baseline)?,
            candidate_cut.as_array(), baseline_cut.as_array(), original.plan.as_array(),
            original.qualification.as_array(),
        ]);
        assert_eq!(checked.material, local);
        assert_ne!(local, crate::cell_q24_model_material::original_model_material_digest(
            training.evidence_digest, &baseline, &candidate, candidate_cut, baseline_cut,
            original.plan, original.qualification,
        )?);
        // Alter a byte in each authenticated preimage independently; keeping
        // claimed digests and the original signatures cannot make it valid.
        for field in 0..15 {
            let mut body = Body::decode(&self.bytes)?;
            let member = &mut body.members[0];
            let value = match field {
                0 => &mut member.record, 1 => &mut member.holdout, 2 => &mut member.plan,
                3 => &mut member.request, 4 => &mut member.decision, 5 => &mut member.qualification,
                6 => &mut member.estimand, 7 => &mut member.roles, 8 => &mut member.generator,
                9 => &mut member.evaluator, 10 => &mut member.execution,
                11 => &mut member.execution_record, 12 => &mut member.cohort, 13 => &mut member.freeze,
                _ => &mut body.evaluation,
            };
            let last = value.last_mut().expect("nonempty original preimage");
            *last ^= 1;
            assert!(verify::material(&self.context, &self.evaluation, &body.encode()?, current).is_err(),
                "changed original preimage {field}");
        }
        let mut missing = Body::decode(&self.bytes)?;
        missing.members.pop();
        assert!(missing.encode().is_err());
        let mut reordered = Body::decode(&self.bytes)?;
        reordered.members.swap(0, 1);
        assert!(verify::material(&self.context, &self.evaluation, &reordered.encode()?, current).is_err());
        let mut renewed_context = self.context.clone();
        renewed_context.training_evidence.expires_at += 1;
        renewed_context.training_evidence.signature = SigningKey::from_bytes(&[41; 32])
            .sign(&renewed_context.training_evidence.signing_bytes()).to_bytes();
        // Verify legal Generator re-signing over the actual unchanged T first.
        renewed_context.verifier.verify(codex_hepta_learning_ledger::LearningEvidenceRoleV1::Generator,
            &renewed_context.training_evidence, &learning_iteration_receipt_signing_bytes_v1(training)?, current)?;
        assert!(verify::material(&renewed_context, &self.evaluation, &self.bytes, current).is_err());
        assert!(self.authenticate_current(self.evaluation.attestation().expires_at).is_err());
        assert!(self.authenticate_current(self.observed_at - 1).is_err());
        Ok(())
    }
}
