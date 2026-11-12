//! Actual installed C and sealed S/C command owners share Version's fourth
//! original Trainer session. Nothing returns or reconstructs T/B clients.
use super::*;
use crate::OriginalCircuitEvaluatedNextUseReceiptConfigV1;
use crate::OriginalCircuitNextUseReceiptOwnerV1;
use crate::circuit_feature_current::original_learning_read_fixture as reads;
use crate::learning_iteration_evidence_client::evaluated_next_use_command_test_support as observers;
use crate::learning_iteration_evidence_client::evaluated_selection_command_test_support as selectors;

pub(super) async fn run_shared_s_c(
    f: &PublicationFixture,
    version: Arc<VersionHost>,
    material: &crate::OriginalCellQ24MaterialReceiptConfigV1,
    dataset: &crate::OriginalCellQ24MaterialCommandReceiptV1,
    c: &support::Session,
) -> anyhow::Result<()> {
    let context = ReadContext::for_original_selection(f.context()?)?;
    let task = Arc::new(ReadOwner::from_original_evaluated_owners(
        c.cell.clone(),
        c.source.as_ref().clone(),
        c.runtime.identity.clone(),
        context.clone(),
    )?);
    let (live, channel) = reads::evaluated_client(context)?;
    let task_peer = reads::serve(Arc::clone(&task), channel);
    let files = SelectorFiles::new()?;
    let empty = files.bytes().ok();
    assert!(empty.is_none(), "no S journal before original create");
    let owner = files.owner(f, OpenReceipt::Fresh)?;
    let initial = files.bytes()?;
    let selector = Arc::new(
        VersionHost::bind_original_evaluated_selection_owner(Arc::clone(&version), owner, live)
            .await?,
    );
    let (client, channel) =
        selectors::stage_client(material, dataset, &f.training, &f.evaluation, false)?;
    let command_peer = selectors::serve(Arc::clone(&selector), channel);
    let executed = client.execute_selection().await?;
    let selected = client.readback().await?;
    assert_eq!(
        selected.original_receipt_binding(),
        executed.original_receipt_binding()
    );
    assert_eq!(selected.attestation(), executed.attestation());
    selected
        .original_context()
        .require_new_original_receipt(now()?)?;
    assert_eq!(
        &selected.snapshot().receipts[..4],
        &f.evaluation.snapshot().receipts
    );
    assert_ne!(files.bytes()?, initial);
    let original_s = files.bytes()?;
    commands::original_version_fifth_connection_refuses(Arc::clone(&f.trainer)).await?;

    // The same legal full S signature read by another Fresh client has no
    // Execute ACK provenance. Version's successful publication cannot upgrade
    // it: original C custody refuses it before any journal claim.
    let (unacknowledged, channel) =
        selectors::stage_client(material, dataset, &f.training, &f.evaluation, false)?;
    let unacknowledged_peer = selectors::serve(Arc::clone(&selector), channel);
    let read_only = unacknowledged.readback().await?;
    assert_eq!(read_only.snapshot(), selected.snapshot());
    assert_eq!(read_only.attestation(), selected.attestation());
    assert!(matches!(
        read_only
            .original_context()
            .require_new_original_receipt(now()?),
        Err(crate::OriginalCircuitRetainedPublicationErrorV1::Binding(
            "recovered evaluated retention is read-only"
        ))
    ));
    let refused_files = SelectorFiles::new()?;
    let (journal, witness) = refused_files.files(f, &OpenReceipt::Fresh)?;
    let refused_before = refused_files.bytes()?;
    assert!(matches!(
        OriginalCircuitNextUseReceiptOwnerV1::create_evaluated(
            journal,
            witness,
            OriginalCircuitEvaluatedNextUseReceiptConfigV1 {
                selection: read_only,
                signer: f.host.original.credentials.observer.clone(),
                maximum_signature_lifetime_seconds: 300,
            },
            ed25519_dalek::SigningKey::from_bytes(&[43; 32]),
        ),
        Err(crate::OriginalCircuitNextUseReceiptErrorV1::Evaluated(
            crate::OriginalCircuitRetainedPublicationErrorV1::Binding(
                "recovered evaluated retention is read-only"
            ),
        ))
    ));
    assert_eq!(refused_files.bytes()?, refused_before);
    assert_eq!(files.bytes()?, original_s);
    drop(unacknowledged);
    assert_eq!(
        unacknowledged_peer
            .join()
            .expect("unacknowledged original S readback")?,
        1
    );

    // The actual bootstrap was taken exactly once from the Version-installed
    // config. Normal AuthBus ingress now starts the already-created C owners.
    let publication = execute(c, 1).await?;
    let actual = read_receipt(c, &f.definition, &publication)?;
    assert_eq!(actual.bundle_digest, f.bundle.digest()?);
    assert_ne!(actual.bundle_digest, f.host.original.candidate.digest()?);
    assert_eq!(
        actual.representation.prediction_q24,
        vec![Q / 4, Q, 0, 0, 0]
    );
    let (original_s_reader, channel) = selectors::evidence_client(&selector)?;
    let evidence_peer = selectors::serve_evidence(Arc::clone(&selector), channel);
    let context = ReadContext::for_original_next_use(selected.clone())?;
    let next_task = Arc::new(ReadOwner::from_original_evaluated_owners(
        c.cell.clone(),
        c.source.as_ref().clone(),
        c.runtime.identity.clone(),
        context.clone(),
    )?);
    let (live, channel) = reads::evaluated_client(context)?;
    let next_task_peer = reads::serve(Arc::clone(&next_task), channel);
    let next_files = SelectorFiles::new()?;
    let (journal, witness) = next_files.files(f, &OpenReceipt::Fresh)?;
    let next = OriginalCircuitNextUseReceiptOwnerV1::create_evaluated(
        journal,
        witness,
        OriginalCircuitEvaluatedNextUseReceiptConfigV1 {
            selection: selected.clone(),
            signer: f.host.original.credentials.observer.clone(),
            maximum_signature_lifetime_seconds: 300,
        },
        ed25519_dalek::SigningKey::from_bytes(&[43; 32]),
    )?;
    let initial_c = next_files.bytes()?;
    let observer = Arc::new(
        VersionHost::bind_original_evaluated_next_use_owner(
            Arc::clone(&version),
            next,
            live,
            original_s_reader,
        )
        .await?,
    );
    let (next_client, channel) = observers::stage_client(material, dataset, &selected, false)?;
    let next_command_peer = observers::serve(Arc::clone(&observer), channel);
    let completed = next_client.attest_completed_task().await?;
    assert_eq!(completed.snapshot().receipts.len(), 6);
    assert_eq!(
        &completed.snapshot().receipts[..5],
        &selected.snapshot().receipts
    );
    assert!(matches!(completed.receipt().observation,
        LearningIterationObservationV1::RetainedModelNextUse { retained_bundle, .. }
        if retained_bundle == f.bundle.digest()?));
    let read = next_client.readback().await?;
    assert_eq!(read.snapshot(), completed.snapshot());
    assert_eq!(read.attestation(), completed.attestation());
    assert_ne!(next_files.bytes()?, initial_c);
    assert_eq!(files.bytes()?, original_s);
    assert_eq!(c.cell.snapshot(&f.source_c.scope)?.revision, 1);
    commands::original_version_fifth_connection_refuses(Arc::clone(&f.trainer)).await?;
    drop(next_client);
    assert_eq!(next_command_peer.join().expect("same sealed C command")?, 2);
    drop(observer);
    // C Execute reads its task three times and Readback twice. Each reads S
    // twice; the Version C factory made one earlier original S read itself.
    assert_eq!(next_task_peer.join().expect("same actual C task read")?, 5);
    drop(next_task);
    assert_eq!(
        evidence_peer
            .join()
            .expect("same readonly original S command")?,
        5
    );
    drop(client);
    assert_eq!(command_peer.join().expect("same sealed S command")?, 2);
    drop(selector);
    // One factory read, S Execute+Readback (3+2), unacknowledged Readback (2),
    // and five S evidence reads (2 each).
    assert_eq!(
        task_peer.join().expect("same actual Selection task read")?,
        18
    );
    drop(task);
    Ok(())
}
