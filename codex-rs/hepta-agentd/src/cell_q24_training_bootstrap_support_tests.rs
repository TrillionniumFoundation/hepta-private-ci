//! Explicit same-UID mechanism harness. The Material endpoints below read the
//! actual original pair every time; no replayed-signature responder is used.
use std::thread::JoinHandle;

use super::super::super::wire;
use super::*;
use crate::OriginalCellQ24DatasetCommandReadbackV1;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24TrainingCommandClientV1;
use crate::OriginalCellQ24TrainingCommandContextV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;
use crate::OriginalCellQ24TrainingSourceConfigV1;
use crate::cell_q24_material_receipt_owner::MaterialCommandFixture;
use crate::learning_iteration_evidence_client::command_test_support as transport;
use crate::learning_iteration_evidence_client::material::bootstrap_ports as material;
use codex_hepta_neuron::FileAnchorWitnessStore;
use pretty_assertions::assert_eq;

pub(super) type Host =
    OriginalCellQ24TrainingBootstrapOwnerV1<FileAnchorWitnessStore, FileAnchorWitnessStore>;
pub(super) type Custody =
    OriginalCellQ24TrainingBootstrapCustodyV1<FileAnchorWitnessStore, FileAnchorWitnessStore>;
pub(super) type Peers = [material::Peer; 4];
pub(super) type Server = JoinHandle<Result<u64, Error>>;
type Role = crate::OriginalCellQ24MaterialEvidenceRoleV1;

pub(super) fn inputs(
    fixture: &MaterialCommandFixture,
    origin: Origin,
) -> anyhow::Result<(Custody, OriginalCellQ24DatasetCommandReadbackV1, Peers)> {
    let (dataset, dataset_peer) = material::commands(fixture, Role::Dataset)?;
    let dataset = dataset.into_original_dataset_readback(&fixture.config)?;
    let (source, source_peer) = material::source_connection(fixture, Duration::from_secs(300))?;
    let (experience, experience_peer) = material::evidence(fixture, Role::Experience)?;
    let (data_evidence, data_peer) = material::evidence(fixture, Role::Dataset)?;
    let custody = match origin {
        Origin::Fresh => fixture.fresh_training_custody(source, experience, data_evidence)?,
        Origin::Recovered => {
            fixture.recovered_training_custody(source, experience, data_evidence)?
        }
    };
    Ok((
        custody,
        dataset,
        [dataset_peer, source_peer, experience_peer, data_peer],
    ))
}

pub(super) fn owner(
    fixture: &MaterialCommandFixture,
    origin: Origin,
) -> anyhow::Result<(Arc<Host>, Peers)> {
    let (custody, dataset, peers) = inputs(fixture, origin)?;
    let owner = match origin {
        Origin::Fresh => Host::from_original_custody(
            custody,
            fixture.training_configuration(),
            dataset,
            Arc::new(AtomicBool::new(false)),
        )?,
        Origin::Recovered => Host::recover_original_custody(
            custody,
            fixture.training_configuration(),
            dataset,
            Arc::new(AtomicBool::new(false)),
        )?,
    };
    Ok((Arc::new(owner), peers))
}

pub(super) async fn complete_material(
    fixture: &MaterialCommandFixture,
) -> anyhow::Result<OriginalCellQ24MaterialCommandReceiptV1> {
    let (experience, e_peer) = material::commands(fixture, Role::Experience)?;
    let original_e = experience.execute().await?;
    drop(experience);
    assert_eq!(material::finish(e_peer)?, 1);
    let (dataset, d_peer) = material::commands(fixture, Role::Dataset)?;
    let original_d = dataset.execute().await?;
    assert_eq!(original_d.snapshot().receipts[0], *original_e.receipt());
    assert_eq!(original_d.attestations()[0], *original_e.attestation());
    drop(dataset);
    assert_eq!(material::finish(d_peer)?, 1);
    Ok(original_d)
}

pub(super) fn context(
    fixture: &MaterialCommandFixture,
    cut: &OriginalCellQ24MaterialCommandReceiptV1,
) -> OriginalCellQ24TrainingCommandContextV1 {
    OriginalCellQ24TrainingCommandContextV1 {
        dataset: cut.snapshot().clone(),
        scope: fixture.config.scope.clone(),
        verifier: fixture.config.verifier.clone(),
    }
}

pub(super) fn source_config(
    fixture: &MaterialCommandFixture,
    cut: &OriginalCellQ24MaterialCommandReceiptV1,
) -> OriginalCellQ24TrainingSourceConfigV1 {
    let config = fixture.training_configuration();
    OriginalCellQ24TrainingSourceConfigV1 {
        dataset: cut.snapshot().clone(),
        scope: config.material.scope,
        rule: config.material.rule,
        optimizer: config.optimizer,
        freeze_plan: config.material.freeze_plan,
        freeze_evidence: config.material.freeze_evidence,
        experience_evidence: cut.attestations()[0].clone(),
        dataset_evidence: cut.attestations()[1].clone(),
        verifier: config.material.verifier,
    }
}

pub(super) fn connected<
    TW: AnchorWitnessStore + Send + 'static,
    RW: AnchorWitnessStore + Send + 'static,
>(
    owner: Arc<OriginalCellQ24TrainingBootstrapOwnerV1<TW, RW>>,
    context: OriginalCellQ24TrainingCommandContextV1,
    origin: Origin,
    expected: Option<OriginalCellQ24TrainingCommandReceiptV1>,
) -> anyhow::Result<(OriginalCellQ24TrainingCommandClientV1, Server)> {
    let (client, mut channel) =
        transport::client(context, matches!(origin, Origin::Recovered), expected)?;
    let thread = std::thread::spawn(move || owner.serve_command_channel(&mut channel));
    Ok((client, thread))
}

pub(super) fn lose_ack(
    owner: Arc<Host>,
    context: OriginalCellQ24TrainingCommandContextV1,
) -> anyhow::Result<(
    OriginalCellQ24TrainingCommandClientV1,
    JoinHandle<anyhow::Result<()>>,
)> {
    let (client, mut channel) = transport::client(context, /*readback_only*/ false, None)?;
    let thread = std::thread::spawn(move || {
        let mut completed = false;
        let result = channel.exchange(|bytes| {
            let response = owner
                .command_response(bytes, 1)
                .map_err(|_| codex_hepta_contracts::HostIssuerTransportError::InvalidRequest)?;
            let response: wire::Response = serde_json::from_slice(&response)
                .map_err(|_| codex_hepta_contracts::HostIssuerTransportError::InvalidRequest)?;
            completed = matches!(response.result, wire::CommandResult::Completed { .. });
            Err(codex_hepta_contracts::HostIssuerTransportError::Unavailable)
        });
        anyhow::ensure!(
            completed && result.is_err(),
            "only the ACK is lost after actual original completion"
        );
        Ok(())
    });
    Ok((client, thread))
}

pub(super) fn finish(
    client: OriginalCellQ24TrainingCommandClientV1,
    server: Server,
) -> anyhow::Result<u64> {
    drop(client);
    Ok(server.join().expect("deferred original Trainer server")?)
}

pub(super) fn finish_material(peers: Peers) -> anyhow::Result<[u64; 4]> {
    let [dataset, source, experience, data] = peers;
    Ok([
        material::finish(dataset)?,
        material::finish(source)?,
        material::finish(experience)?,
        material::finish(data)?,
    ])
}

pub(super) async fn raw_response(
    owner: Arc<Host>,
    mut request: wire::Request,
) -> anyhow::Result<Result<wire::Response, Error>> {
    request.request_id = 1;
    tokio::task::spawn_blocking(move || {
        let bytes = serde_json::to_vec(&request).expect("fixed test request");
        owner
            .command_response(&bytes, 1)
            .map(|bytes| serde_json::from_slice(&bytes).expect("original response"))
    })
    .await
    .map_err(anyhow::Error::from)
}

pub(in super::super) struct WriterGate {
    pub(super) captured: Arc<tokio::sync::Notify>,
    pub(super) release: Arc<tokio::sync::Notify>,
}

impl<TW: AnchorWitnessStore + Send + 'static, RW: AnchorWitnessStore + Send + 'static>
    OriginalCellQ24TrainingBootstrapOwnerV1<TW, RW>
{
    pub(in super::super) async fn wait_before_writer_for_test(&self) {
        let gate = self.writer_gate.lock().expect("fixture writer gate").take();
        if let Some(gate) = gate {
            gate.captured.notify_one();
            gate.release.notified().await;
        }
    }
}


/// Bind the actual Trainer transport while only the original initial context
/// exists. Dataset completion cannot restart its session or replace its peer.
pub(super) fn prebound(
    owner: Arc<Host>,
    config: crate::OriginalCellQ24MaterialReceiptConfigV1,
    origin: Origin,
    expected: Option<OriginalCellQ24TrainingCommandReceiptV1>,
    lifetime: Duration,
) -> anyhow::Result<(crate::OriginalCellQ24TrainingCommandConnectionV1, Server)> {
    use super::super::super::connection;
    let (connection, mut channel) = match origin {
        Origin::Fresh => connection::fresh_peer(config, lifetime)?,
        Origin::Recovered => connection::recovered_peer(config, expected, lifetime)?,
    };
    let server = std::thread::spawn(move || owner.serve_command_channel(&mut channel));
    Ok((connection, server))
}
