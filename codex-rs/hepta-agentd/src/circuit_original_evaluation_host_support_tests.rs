//! Actual B/retention and original Evaluator mechanism fixture.
//! Credentials, declared Product metadata, Root setup and future B time are
//! synthetic test inputs. No ordinary deployment or positive gain is claimed.
use std::fs::File;
use std::fs::OpenOptions;
use std::os::unix::fs::OpenOptionsExt;
use std::sync::Arc;

use ed25519_dalek::SigningKey;

use super::super::*;
use crate::OriginalCellEvaluationCommandClientV1;
use crate::OriginalCellEvaluationCommandReceiptV1;
use crate::OriginalCellEvaluationHostV1;
use crate::OriginalCellEvaluationReceiptConfigV1;
use crate::OriginalCellEvaluationReceiptOwnerV1;
use crate::OriginalCellEvaluationSigningConfigV1;
use codex_hepta_neuron::JournalScope;
use codex_hepta_types::Generation;

pub(super) struct HostFixture {
    pub(super) host: Option<Arc<OriginalCellEvaluationHostV1>>,
    pub(super) original: PositiveFixture,
    pub(super) primary_b: BFixture,
    pub(super) retention_b: BFixture,
    primary: PanelMemberFixture,
    retention: PanelMemberFixture,
    pub(super) config: OriginalCellEvaluationReceiptConfigV1,
    pub(super) at: u64,
    directory: tempfile::TempDir,
}
pub(super) type Peer = std::thread::JoinHandle<anyhow::Result<u64>>;

impl HostFixture {
    pub(super) async fn new(pending_claim: bool) -> anyhow::Result<Self> {
        let PanelFixture { panel, original, primary_b, retention_b, primary, retention, at } =
            PanelFixture::completed(TrainingPeer::Original).await?;
        let input = &primary.config;
        let config = OriginalCellEvaluationReceiptConfigV1 {
            training: input.training.clone(), scope: input.scope.clone(), plan: input.plan.clone(),
            signing: OriginalCellEvaluationSigningConfigV1 {
                plan: input.plan.product_plan().clone(),
                execution_namespace: input.execution_namespace,
                signer: original.credentials.evaluator.clone(),
                verifier: input.verifier.clone(), maximum_signature_lifetime_seconds: 600,
            },
        };
        let directory = tempfile::tempdir_in(std::env::temp_dir().canonicalize()?)?;
        let mut fixture = Self {
            host: None, original, primary_b, retention_b, primary, retention,
            config, at, directory,
        };
        let (file, witness) = fixture.files(/*create*/ true)?;
        let mut evaluator = OriginalCellEvaluationReceiptOwnerV1::create(
            file, witness, fixture.config.clone(), SigningKey::from_bytes(&[42; 32]),
        )?;
        if pending_claim { evaluator.fixture_pending_original_host()?; }
        let mut host = evaluator.into_original_evaluation_host(panel)?;
        host.fixture_original_clock(at)?;
        fixture.host = Some(Arc::new(host));
        Ok(fixture)
    }

    fn files(&self, create: bool) -> anyhow::Result<(File, FileAnchorWitnessStore)> {
        let open = |name: &str| -> anyhow::Result<File> {
            let mut options = OpenOptions::new();
            options.read(true).write(true).mode(0o600);
            if create { options.create_new(true); }
            Ok(options.open(self.directory.path().join(name))?)
        };
        let file = open("original-evaluation")?;
        let witness = FileAnchorWitnessStore::open(
            open("original-evaluation-witness")?,
            JournalScope {
                scope_digest: self.config.scope.binding(),
                objective_digest: self.config.signing.verifier.objective_digest(),
            }, Generation::new(/*value*/ 1)?, /*max_records*/ 64,
        )?;
        Ok((file, witness))
    }

    pub(super) fn original_files(&self) -> anyhow::Result<[Vec<u8>; 2]> {
        Ok([
            std::fs::read(self.directory.path().join("original-evaluation"))?,
            std::fs::read(self.directory.path().join("original-evaluation-witness"))?,
        ])
    }

    pub(super) fn upstream_files(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        let mut bytes = self.primary.bytes()?;
        bytes.extend(self.retention.bytes()?);
        bytes.extend(self.primary_b.all_source_bytes()?);
        bytes.extend(self.retention_b.all_source_bytes()?);
        bytes.extend(self.host.as_ref().expect("original host").fixture_original_cohort_files()?);
        Ok(bytes)
    }

    pub(super) fn commands(
        &self, readback_only: bool, expected: Option<OriginalCellEvaluationCommandReceiptV1>,
        fault: &'static str,
    ) -> anyhow::Result<(OriginalCellEvaluationCommandClientV1, Peer)> {
        self.host.as_ref().expect("original host")
            .fixture_commands(readback_only, expected, fault)
    }

    pub(super) fn recover(&mut self) -> anyhow::Result<()> {
        let host = Arc::try_unwrap(self.host.take().expect("original host"))
            .map_err(|_| anyhow::anyhow!("all original command peers must be closed before recovery"))?;
        let panel = host.fixture_take_original_panel()?;
        let (file, witness) = self.files(/*create*/ false)?;
        let evaluator = OriginalCellEvaluationReceiptOwnerV1::recover(
            file, witness, self.config.clone(), SigningKey::from_bytes(&[42; 32]),
        )?;
        let mut host = evaluator.into_original_evaluation_host(panel)?;
        host.fixture_original_clock(self.at)?;
        self.host = Some(Arc::new(host));
        Ok(())
    }

    pub(super) async fn finish(mut self) -> anyhow::Result<[usize; 2]> {
        drop(self.host.take());
        let counts = [self.primary.finish()?, self.retention.finish()?];
        drop(self.primary_b);
        drop(self.retention_b);
        self.original.finish().await?;
        Ok(counts)
    }
}

pub(super) fn finish(
    client: OriginalCellEvaluationCommandClientV1, peer: Peer,
) -> anyhow::Result<u64> {
    drop(client);
    peer.join().map_err(|_| anyhow::anyhow!("original Evaluation command peer panicked"))?
}
