//! The actual Source/Cell/Driver fixture below establishes source bytes, not
//! a real supervisor disclosure, process identity or a cross-UID exchange.

use super::*;
use crate::circuit_task::original_prefreeze_source::test_support::{EvidenceFixture, AT};
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;

#[tokio::test]
async fn prefreeze_request_reads_actual_source_without_future_evidence() -> anyhow::Result<()> {
    let fixture = completed_source().await?;
    let input = original::source("A", b"actual Material source fixture");
    let task = crate::circuit_feature_task_digest_v1(&cell::definition(), &input)?;
    let evidence = EvidenceFixture::new(input, task, "prefreeze-test-operation", cell::d("initial intent"))?;
    let admitted = evidence.verify()?;
    let before = fixture.bytes()?;
    let view = fixture.source.readback();
    let payload = view.encode_original_material_publication(&fixture.identity, &fixture.publication)?;
    let observed = decode_current_root_payload(&payload)?;
    evidence.request.require_publication(&observed)?;
    anyhow::ensure!(observed == fixture.publication, "the full original publication changed");
    anyhow::ensure!(fixture.bytes()? == before, "pre-freeze observation wrote original journals");

    fixture.source.withdraw_source(&cell::id("A"))?;
    let withdrawn = fixture.bytes()?;
    anyhow::ensure!(evidence.verify()? == admitted, "the independent signature fixture changed");
    anyhow::ensure!(view.encode_original_material_publication(&fixture.identity, &observed)
        == Err(Error::Unavailable), "a still-valid signature cannot revive withdrawn Source");
    anyhow::ensure!(fixture.bytes()? == withdrawn, "refused observation changed the withdrawal");
    anyhow::ensure!(fixture.calls.load(Ordering::SeqCst) == 1, "pre-freeze read redispatched inference");
    Ok(())
}

#[tokio::test]
async fn prefreeze_request_refuses_rebinding_and_other_enrolled_generator() -> anyhow::Result<()> {
    let fixture = completed_source().await?;
    let input = original::source("A", b"actual Material source fixture");
    let task = crate::circuit_feature_task_digest_v1(&cell::definition(), &input)?;
    let mut evidence = EvidenceFixture::new(input, task, "prefreeze-test-operation", cell::d("initial intent"))?;
    let original_binding = evidence.verify()?;
    let before = fixture.bytes()?;

    evidence.request.consumer.pid += 1;
    anyhow::ensure!(evidence.verify() == Err(Error::InvalidBinding), "recipient substitution was accepted");
    evidence.request.consumer.pid -= 1;
    evidence.request.nonce[0] ^= 1;
    anyhow::ensure!(evidence.verify() == Err(Error::InvalidBinding), "nonce substitution was accepted");
    evidence.request.nonce[0] ^= 1;
    evidence.request.task_digest = cell::d("different task");
    anyhow::ensure!(evidence.verify() == Err(Error::InvalidBinding), "another task was accepted");
    evidence.request.task_digest = task;
    evidence.request.source.observation.push(1);
    anyhow::ensure!(evidence.verify() == Err(Error::InvalidBinding), "changed full input was accepted");
    evidence.request.source.observation.pop();
    let controller = evidence.request.generator.controller_id.clone();
    evidence.request.generator.controller_id = cell::id("different-controller");
    anyhow::ensure!(evidence.verify() == Err(Error::InvalidBinding), "changed signer controller was accepted");
    evidence.request.generator.controller_id = controller;

    let other = evidence.another_valid_generator()?;
    evidence.verifier.verify(LearningEvidenceRoleV1::Generator, &other,
        &evidence.request.signing_payload()?, AT)?;
    anyhow::ensure!(evidence.request.require_evidence(&evidence.verifier,
        evidence.request.trust_distribution_digest, evidence.request.trust_generation, &other, AT)
        == Err(Error::InvalidBinding), "another valid enrolled Generator selected this disclosure");
    anyhow::ensure!(evidence.verify()? == original_binding, "the original complete binding no longer verifies");
    evidence.request.require_publication(&fixture.publication)?;
    anyhow::ensure!(fixture.bytes()? == before, "signature refusal wrote original Source/Cell evidence");
    anyhow::ensure!(fixture.calls.load(Ordering::SeqCst) == 1, "signature refusal redispatched inference");
    Ok(())
}
