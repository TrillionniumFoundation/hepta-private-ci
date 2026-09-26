#![allow(clippy::unwrap_used)]
//! A valid signature on the V1 compatibility index cannot replace V2 lineage.
use super::current_artifacts::Artifacts;
use super::digest;
use super::id;
use codex_hepta_agentd::AgentdSharedReplayHostV1;
use codex_hepta_agentd::SharedTerminalCandidateV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_learning_artifacts::ProvenanceModeV1;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::FederationConsumerAccess;
use std::path::Path;
use std::sync::Arc;

pub(super) async fn rejects_mismatched_admitted_lineage(
    source: Arc<CognitiveStore>,
    consumer: FederationConsumerAccess,
    receiver: AgentId,
    ledger: &LedgerWriter,
    candidate: &SharedTerminalCandidateV1,
    root: &Path,
) {
    let payload = candidate.encode_payload().unwrap();
    for case in [
        "other-dataset",
        "extra-dataset",
        "wrong-lineage",
        "independent",
    ] {
        let artifacts = Artifacts::open(&root.join(case), None);
        let selection =
            artifacts.publish_with_manifest(candidate.artifact(), &payload, |m| match case {
                "other-dataset" => m.source_dataset_digests = vec![digest("unrelated")],
                "extra-dataset" => m.source_dataset_digests.push(digest("unrelated")),
                "wrong-lineage" => m.lineage_digests = vec![digest("another-model")],
                "independent" => {
                    m.provenance_mode = ProvenanceModeV1::DatasetIndependent;
                    m.source_dataset_digests.clear();
                }
                _ => unreachable!(),
            });
        let host = AgentdSharedReplayHostV1::new(
            Arc::clone(&source),
            consumer.clone(),
            "domain.terminal".into(),
            receiver.clone(),
        )
        .unwrap()
        .with_artifact_owner(Arc::clone(&artifacts.owner), artifacts.selector.clone());
        // The selection is genuinely signed and CURRENT, and the payload hash is
        // exact. Only the disagreement with authoritative V2 lineage is wrong.
        assert!(
            host.load(ledger, selection, 50).await.is_err(),
            "accepted {case}"
        );
    }

    // Sign exact altered bytes through the real artifact owner. These inputs
    // pass hash/signature checks and fail only the new recovery epoch contract.
    let original = String::from_utf8(payload.clone()).unwrap();
    let encoded_trust = ledger.trust_distribution_digest().to_string();
    for (case, changed, expected) in [
        (
            "legacy-recovery-v1",
            original.replacen("\"version\":2", "\"version\":1", 1),
            "recovery version or canonical form",
        ),
        (
            "other-learning-trust",
            original.replacen(&encoded_trust, &digest("different-trust").to_string(), 1),
            "current learning trust changed",
        ),
    ] {
        assert_ne!(changed, original);
        let artifacts = Artifacts::open(&root.join(case), None);
        let selection = artifacts.publish(candidate.artifact(), changed.as_bytes());
        let host = AgentdSharedReplayHostV1::new(
            Arc::clone(&source),
            consumer.clone(),
            "domain.terminal".into(),
            receiver.clone(),
        )
        .unwrap()
        .with_artifact_owner(Arc::clone(&artifacts.owner), artifacts.selector.clone());
        let result = host.load(ledger, selection, 50).await;
        assert!(
            matches!(result, Err(codex_hepta_agentd::SharedTerminalCellError::Binding(message))
            if message == expected),
            "wrong recovery rejection: {case}"
        );
    }

    let artifacts = Artifacts::open(&root.join("short-manifest-lifetime"), None);
    let selection = artifacts.publish_with_manifest(candidate.artifact(), &payload, |m| {
        m.expires_at = 51;
        m.lineage_digests
            .extend((0..800).map(|i| digest(&format!("support-{i}"))));
    });
    let host = AgentdSharedReplayHostV1::new(source, consumer, "domain.terminal".into(), receiver)
        .unwrap()
        .with_artifact_owner(Arc::clone(&artifacts.owner), artifacts.selector.clone());
    let path = artifacts
        .root
        .join("transactions")
        .join(format!("{}.manifest-v2", selection.support_digest));
    let metadata = std::fs::read(&path).unwrap();
    assert!(metadata.len() > 16 * 1024);
    std::fs::rename(&path, path.with_extension("offline")).unwrap();
    assert!(host.load(ledger, selection.clone(), 50).await.is_err());
    std::fs::rename(path.with_extension("offline"), &path).unwrap();
    std::fs::write(&path, &metadata[..metadata.len() - 1]).unwrap();
    assert!(host.load(ledger, selection.clone(), 50).await.is_err());
    std::fs::write(&path, &metadata).unwrap();
    let mut model = host.load(ledger, selection.clone(), 50).await.unwrap();
    assert!(
        host.predict(
            &mut model,
            ledger,
            &id("single-approved-state"),
            &id("read"),
            50
        )
        .await
        .is_ok()
    );
    assert!(
        host.predict(
            &mut model,
            ledger,
            &id("single-approved-state"),
            &id("read"),
            52
        )
        .await
        .is_err()
    );
    // Failure closes this handle even when the native caller rewinds its clock.
    assert!(
        host.predict(
            &mut model,
            ledger,
            &id("single-approved-state"),
            &id("read"),
            50
        )
        .await
        .is_err()
    );
    assert!(host.load(ledger, selection, 52).await.is_err());
}
