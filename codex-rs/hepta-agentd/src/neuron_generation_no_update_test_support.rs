//! Retained public-channel readback and independently signed negative fixtures.
//! The learning checkpoint remains in memory; no production restore is claimed.

use std::sync::Arc;

use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationOwnersV1;
use codex_hepta_learning_artifacts::LearningIterationRequestV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use pretty_assertions::assert_eq;
use tokio_util::sync::CancellationToken;

use super::host;
use crate::AgentdError;
use crate::AgentdLearningNoUpdateInputsV1;
use crate::learning_iteration_channel_v1;
use crate::neuron_generation_current::test_support::Fixture;
use crate::plasticity_runtime::lifetime_tests::learning_iteration_tests::IterationPorts;

pub(super) async fn submit_retained(
    host: &host::Fixture,
    ports: &Arc<IterationPorts>,
    request: LearningIterationRequestV1,
) -> anyhow::Result<LearningIterationSnapshotV1> {
    let (handle, owner) = learning_iteration_channel_v1(
        host.identity.agent_id.clone(),
        host.identity.spawn_generation,
        ports.owners(),
        ports.clone(),
        ports.verifier.clone(),
        /*capacity*/ 2,
    )?;
    // The fixture's signed evidence uses its fixed test clock. The real public
    // channel then reconciles that retained terminal result, including after
    // expiry, without executing stages or granting any new authority.
    let terminal = owner
        .process(host.state(), request.clone(), || Ok(50))
        .await?;
    let cancellation = CancellationToken::new();
    let worker = tokio::spawn(owner.run(Arc::clone(host.state()), cancellation.clone()));
    let received = handle.submit(request).await;
    cancellation.cancel();
    worker.await??;
    let received = received?;
    assert_eq!(received, terminal);
    Ok(received)
}

pub(super) struct SignedLearning {
    ports: Arc<IterationPorts>,
    request: LearningIterationRequestV1,
    owners: LearningIterationOwnersV1,
    snapshot: LearningIterationSnapshotV1,
}

impl SignedLearning {
    pub(super) async fn new(
        host: &host::Fixture,
        request: LearningIterationRequestV1,
    ) -> anyhow::Result<Self> {
        let ports = Arc::new(IterationPorts::new(
            /*proposal*/ None,
            LearningEvaluationDispositionV1::NoUpdate,
        ));
        let owners = ports.owners();
        let snapshot = submit_retained(host, &ports, request.clone()).await?;
        assert_eq!(snapshot.receipts.len(), 4);
        Ok(Self {
            ports,
            request,
            owners,
            snapshot,
        })
    }

    pub(super) fn inputs(&self) -> AgentdLearningNoUpdateInputsV1<'_> {
        AgentdLearningNoUpdateInputsV1 {
            ports: self.ports.as_ref(),
            verifier: &self.ports.verifier,
            request: &self.request,
            owners: &self.owners,
            expected_head: self.snapshot.head_digest,
            now_unix_seconds: 50,
        }
    }
}

pub(super) fn require_bundle_error<T>(result: Result<T, AgentdError>) -> anyhow::Result<()> {
    require_invalid_message(
        result,
        "learning bundle does not match the selected generation manifest",
    )
}

pub(super) fn require_publication_error<T>(result: Result<T, AgentdError>) -> anyhow::Result<()> {
    require_invalid_message(
        result,
        "NoUpdate successor does not match its committed owner publication",
    )
}

fn require_invalid_message<T>(
    result: Result<T, AgentdError>,
    expected: &str,
) -> anyhow::Result<()> {
    match result {
        Err(AgentdError::Invalid(message)) => assert_eq!(message, expected),
        _ => anyhow::bail!("expected authenticated owner binding rejection: {expected}"),
    }
    Ok(())
}

#[derive(Clone, Copy)]
pub(super) enum LiveInvalidation {
    ArtifactCurrent,
    FinalUseRevocation,
}

impl LiveInvalidation {
    pub(super) const fn directory(self) -> &'static str {
        match self {
            Self::ArtifactCurrent => "evaluated-no-update-current",
            Self::FinalUseRevocation => "evaluated-no-update",
        }
    }

    pub(super) fn apply(
        self,
        fixture: &Fixture,
        signed: &SignedFinalUseGrant,
    ) -> anyhow::Result<()> {
        match self {
            Self::ArtifactCurrent => fixture.advance_artifact_current(),
            Self::FinalUseRevocation => {
                let mut revocations = fixture.authority.revocation_head()?;
                revocations.revision += 1;
                revocations
                    .revoked_grant_ids
                    .insert(signed.grant.grant_id.clone());
                fixture.authority.update_revocations(revocations)?;
                Ok(())
            }
        }
    }
}
