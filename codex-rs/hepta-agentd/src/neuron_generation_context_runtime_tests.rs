//! Ordinary runtime settlement against real publication, CURRENT, FinalUse,
//! journal and witness owners. The supplied computation is explicitly a
//! synthetic fault injector; these tests make no numerical-verifier claim.

use std::io::Read;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::Ordering;

use codex_hepta_neuron::CellBackendManifestV2;
use codex_hepta_neuron::CellGenerationControlPortV2;
use codex_hepta_neuron::CellGenerationDispositionV2;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_neuron::CellGenerationProposalV2;
use codex_hepta_neuron::CellGenerationRequestV2;
use codex_hepta_types::AuthorityPosture;
use pretty_assertions::assert_eq;

use super::host;
use super::support;
use crate::AgentdGenerationUpdateRequestV1;
use crate::AgentdGenerationUpdateRuntimeOptionsV1;
use crate::neuron_generation_current::test_support::Fixture;
use crate::prepare_agentd_generation_update_v1;

enum DispatchResponse {
    Return,
    WrongRequest,
    Pending,
    Uncertain,
}

type BoundaryHook = Box<dyn FnOnce() -> anyhow::Result<()> + Send>;

struct BoundaryControl {
    inner: support::Control,
    response: DispatchResponse,
    after_dispatch: Option<BoundaryHook>,
    after_read: Option<BoundaryHook>,
}

impl CellGenerationControlPortV2 for BoundaryControl {
    fn execute_generation(
        &mut self,
        manifest: &CellBackendManifestV2,
        request: &CellGenerationRequestV2,
    ) -> Result<CellGenerationProposalV2, CellGenerationErrorV2> {
        let mut proposal = self.inner.execute_generation(manifest, request)?;
        if let Some(hook) = self.after_dispatch.take() {
            hook().map_err(|_| CellGenerationErrorV2::Unavailable)?;
        }
        match self.response {
            DispatchResponse::Return => Ok(proposal),
            DispatchResponse::WrongRequest => {
                let mut foreign = request.clone();
                foreign.input.push(99);
                proposal.request_digest = foreign.digest()?;
                Ok(proposal)
            }
            DispatchResponse::Pending => Err(CellGenerationErrorV2::Pending),
            DispatchResponse::Uncertain => Err(CellGenerationErrorV2::CommitUncertain),
        }
    }

    fn read_generation(
        &mut self,
        request: &CellGenerationRequestV2,
    ) -> Result<Option<CellGenerationProposalV2>, CellGenerationErrorV2> {
        let proposal = self.inner.read_generation(request)?;
        if let Some(hook) = self.after_read.take() {
            hook().map_err(|_| CellGenerationErrorV2::Unavailable)?;
        }
        Ok(proposal)
    }

    fn cancel_generation(
        &mut self,
        request: &CellGenerationRequestV2,
    ) -> Result<(), CellGenerationErrorV2> {
        self.inner.cancel_generation(request)
    }
}

#[tokio::test]
async fn ordinary_runtime_recovers_original_identity_after_foreign_or_uncertain_result()
-> anyhow::Result<()> {
    for (response, error) in [
        (
            DispatchResponse::WrongRequest,
            CellGenerationErrorV2::Conflict,
        ),
        (
            DispatchResponse::Uncertain,
            CellGenerationErrorV2::CommitUncertain,
        ),
    ] {
        let mut host = host::Fixture::new().await;
        let update = Fixture::new(host.config.clone())?;
        let prepared = prepare_agentd_generation_update_v1(
            update.current.clone(),
            update.authorities()?,
            update.stopped_old()?,
            update.selection()?,
            update.target_create()?,
            AgentdGenerationUpdateRequestV1 {
                operation_id: "context-runtime-publication".into(),
            },
        )?;
        let grant = update.sign(prepared.final_use_binding())?;
        let ready = prepared.publish(&grant)?;
        let consumed = update.authority.current_external_frontier()?;
        assert_eq!(update.authority.capacity()?.used_nonces, 1);
        let control = support::Control::default();
        let mut runtime = ready.into_runtime(
            support::next_config(&mut host, 2).await?,
            BoundaryControl {
                inner: control.clone(),
                response,
                after_dispatch: None,
                after_read: None,
            },
            host.clock(),
            AgentdGenerationUpdateRuntimeOptionsV1::default(),
        )?;
        let (mut tasks, _lifetime) = support::start(&mut runtime, &host)?;
        let initial = runtime.handle.snapshot().await?;
        let original = support::request(&update.target_config, initial.clone());
        assert_eq!(runtime.handle.step(original.clone()).await, Err(error));
        assert_eq!(runtime.handle.snapshot().await?, initial);
        assert_eq!(
            runtime.handle.pending_request().await?,
            Some(original.clone())
        );
        assert_eq!(runtime.handle.pending_output().await?, None);
        let pending = (
            update.bytes("target-journal")?,
            update.bytes("target-witness")?,
        );
        let mut conflicting = original.clone();
        conflicting.input.push(99);
        assert_eq!(
            runtime.handle.step(conflicting).await,
            Err(CellGenerationErrorV2::Conflict)
        );
        assert_eq!(
            (
                update.bytes("target-journal")?,
                update.bytes("target-witness")?
            ),
            pending
        );
        let receipt = runtime.handle.reconcile(original.digest()?).await?;
        assert_eq!(receipt.authority(), AuthorityPosture::DENY_ALL);
        assert_eq!(runtime.handle.pending_request().await?, None);
        assert_eq!(runtime.handle.snapshot().await?.prefix, support::OUTPUT);
        let committed = (
            update.bytes("target-journal")?,
            update.bytes("target-witness")?,
        );
        assert_ne!(committed, pending);
        assert_eq!(runtime.handle.step(original).await?, receipt);
        assert_eq!(
            (
                update.bytes("target-journal")?,
                update.bytes("target-witness")?
            ),
            committed
        );
        assert_eq!(
            (
                control.executions.load(Ordering::SeqCst),
                control.reads.load(Ordering::SeqCst)
            ),
            (1, 1)
        );
        assert_eq!(update.authority.current_external_frontier()?, consumed);
        tasks.shutdown().await;
    }
    Ok(())
}

#[tokio::test]
async fn ordinary_runtime_rechecks_revocation_after_dispatch_and_readback() -> anyhow::Result<()> {
    for during_read in [false, true] {
        let mut host = host::Fixture::new().await;
        let update = Fixture::new(host.config.clone())?;
        let prepared = prepare_agentd_generation_update_v1(
            update.current.clone(),
            update.authorities()?,
            update.stopped_old()?,
            update.selection()?,
            update.target_create()?,
            AgentdGenerationUpdateRequestV1 {
                operation_id: "context-runtime-revocation".into(),
            },
        )?;
        let grant = update.sign(prepared.final_use_binding())?;
        let ready = prepared.publish(&grant)?;
        let retained = Arc::new(Mutex::new(None));
        let mut journal_file = update.file("target-journal")?;
        let mut witness_file = update.file("target-witness")?;
        let authority = update.authority.clone();
        let before_settlement = retained.clone();
        let hook: BoundaryHook = Box::new(move || {
            let mut journal = Vec::new();
            let mut witness = Vec::new();
            journal_file.read_to_end(&mut journal)?;
            witness_file.read_to_end(&mut witness)?;
            *before_settlement
                .lock()
                .map_err(|_| anyhow::anyhow!("retained test observation poisoned"))? =
                Some((journal, witness));
            let mut head = authority.revocation_head()?;
            head.revision += 1;
            head.revoked_grant_ids.insert(grant.grant.grant_id);
            authority.update_revocations(head)?;
            Ok(())
        });
        let control = support::Control::default();
        let (response, after_dispatch, after_read) = if during_read {
            (DispatchResponse::Pending, None, Some(hook))
        } else {
            (DispatchResponse::Return, Some(hook), None)
        };
        let mut runtime = ready.into_runtime(
            support::next_config(&mut host, 2).await?,
            BoundaryControl {
                inner: control.clone(),
                response,
                after_dispatch,
                after_read,
            },
            host.clock(),
            AgentdGenerationUpdateRuntimeOptionsV1::default(),
        )?;
        let (mut tasks, _lifetime) = support::start(&mut runtime, &host)?;
        let request = support::request(&update.target_config, runtime.handle.snapshot().await?);
        if during_read {
            assert_eq!(
                runtime.handle.step(request.clone()).await,
                Err(CellGenerationErrorV2::Pending)
            );
            assert_eq!(
                runtime.handle.reconcile(request.digest()?).await,
                Err(CellGenerationErrorV2::Unavailable)
            );
        } else {
            assert_eq!(
                runtime.handle.step(request).await,
                Err(CellGenerationErrorV2::Unavailable)
            );
        }
        assert_eq!(
            (
                control.executions.load(Ordering::SeqCst),
                control.reads.load(Ordering::SeqCst)
            ),
            (1, usize::from(during_read))
        );
        let expected = retained
            .lock()
            .map_err(|_| anyhow::anyhow!("retained test observation poisoned"))?
            .clone()
            .ok_or_else(|| anyhow::anyhow!("revocation boundary was never entered"))?;
        assert_eq!(
            (
                update.bytes("target-journal")?,
                update.bytes("target-witness")?
            ),
            expected
        );
        let capacity = update.authority.capacity()?;
        assert_eq!((capacity.used_nonces, capacity.revoked_grants), (1, 1));
        tasks.shutdown().await;
    }
    Ok(())
}

#[tokio::test]
async fn guarded_no_contact_deadline_commits_original_identity_without_model_dispatch()
-> anyhow::Result<()> {
    let mut host = host::Fixture::new().await;
    let update = Fixture::new(host.config.clone())?;
    let prepared = prepare_agentd_generation_update_v1(
        update.current.clone(),
        update.authorities()?,
        update.stopped_old()?,
        update.selection()?,
        update.target_create()?,
        AgentdGenerationUpdateRequestV1 {
            operation_id: "context-runtime-no-contact".into(),
        },
    )?;
    let grant = update.sign(prepared.final_use_binding())?;
    let ready = prepared.publish(&grant)?;
    let consumed = update.authority.current_external_frontier()?;
    let control = support::Control::default();
    let mut runtime = ready.into_runtime(
        support::next_config(&mut host, 2).await?,
        control.clone(),
        host.clock(),
        AgentdGenerationUpdateRuntimeOptionsV1::default(),
    )?;
    let (mut tasks, _lifetime) = support::start(&mut runtime, &host)?;
    let initial = runtime.handle.snapshot().await?;
    let mut request = support::request(&update.target_config, initial.clone());
    host.ticks.store(20, Ordering::SeqCst);
    request.deadline_micros = 21;
    let receipt = runtime.handle.step(request.clone()).await?;
    assert_eq!(
        receipt.disposition,
        CellGenerationDispositionV2::DeadlineExceeded
    );
    assert_eq!(receipt.authority(), AuthorityPosture::DENY_ALL);
    assert_eq!(runtime.handle.pending_request().await?, None);
    assert_eq!(runtime.handle.pending_output().await?, None);
    assert_eq!(runtime.handle.snapshot().await?.state, initial.state);
    let committed = (
        update.bytes("target-journal")?,
        update.bytes("target-witness")?,
    );
    assert_eq!(runtime.handle.step(request).await?, receipt);
    assert_eq!(
        (
            update.bytes("target-journal")?,
            update.bytes("target-witness")?
        ),
        committed
    );
    assert_eq!(
        (
            control.executions.load(Ordering::SeqCst),
            control.reads.load(Ordering::SeqCst)
        ),
        (0, 0)
    );
    assert_eq!(update.authority.current_external_frontier()?, consumed);
    tasks.shutdown().await;
    Ok(())
}
