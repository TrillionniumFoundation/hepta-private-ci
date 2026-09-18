use std::fs::File;
use std::fs::OpenOptions;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::ProductionAuthorityLease;
use codex_hepta_memory::ProductionAuthorityToken;
use codex_hepta_memory::ProductionAuthorityVerifier;
use codex_hepta_memory::ProductionDurableWriter;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_supervisor::DurableWriterHandoffJournalV1;
use codex_hepta_supervisor::WriterHandoffAdvanceV1;
use codex_hepta_supervisor::WriterHandoffPhaseV1;
use codex_hepta_supervisor::WriterHandoffPlanV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use tempfile::TempDir;

struct AllowVerifier;

impl ProductionAuthorityVerifier for AllowVerifier {
    fn verify(
        &self,
        _authority: &ProductionAuthorityLease,
        _expected_agent: &AgentId,
    ) -> Result<(), String> {
        Ok(())
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn owner() -> AgentId {
    AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2cde").expect("valid owner")
}

fn now_unix_seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock after epoch")
        .as_secs()
}

fn authority(agent: AgentId, owner_epoch: u64, label: &str) -> ProductionAuthorityLease {
    ProductionAuthorityLease::from_verified_parts(
        agent,
        Sha256Digest::for_bytes(format!("signed-grant:{label}").as_bytes()),
        9,
        owner_epoch,
        now_unix_seconds() + 3_600,
        ProductionAuthorityToken::from_verified_bytes(
            format!("opaque-supervisor-token:{label}").into_bytes(),
        )
        .expect("authority token"),
    )
    .expect("authority lease")
}

async fn store(temp: &TempDir) -> CognitiveStore {
    let root = temp.path().join("fleet");
    std::fs::create_dir_all(&root).expect("fleet root");
    let fleet = HeptaFleetRoot::parse(root.canonicalize().expect("canonical fleet"))
        .expect("typed fleet root");
    CognitiveStore::open(&fleet.layout().agent(&owner()))
        .await
        .expect("cognitive store")
}

fn handoff_file(temp: &TempDir) -> File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(temp.path().join("writer-handoff.log"))
        .expect("handoff journal")
}

fn step(
    phase: WriterHandoffPhaseV1,
    label: &str,
    outbox_watermark: Option<u64>,
) -> WriterHandoffAdvanceV1 {
    WriterHandoffAdvanceV1 {
        phase,
        evidence_digest: digest(label),
        outbox_watermark,
        unknown_effect_count: 0,
    }
}

#[tokio::test]
async fn recovered_handoff_physically_fences_old_writer_before_successor_admission() {
    let temp = TempDir::new().expect("temp");
    let store = store(&temp).await;
    let owner = store.owner_agent_id().clone();
    let lease_id = "production:handoff:memory";
    let old_authority = authority(owner.clone(), 4, "old");
    let old =
        ProductionDurableWriter::open(store.clone(), old_authority, &AllowVerifier, lease_id, 1)
            .await
            .expect("old writer");

    old.admit("occurrence:before-handoff", "memory.write", "payload-v1")
        .await
        .expect("old writer admission");
    old.rollback_occurrence("occurrence:before-handoff", "handoff-drain")
        .await
        .expect("drain old occurrence");

    let plan = WriterHandoffPlanV1 {
        operation_id: id("handoff.memory.production.v1"),
        domain_id: id("memory.cognitive"),
        source_writer: id("memory.writer.old"),
        target_writer: id("memory.writer.new"),
        old_generation: Generation::new(1).expect("old generation"),
        new_generation: Generation::new(2).expect("new generation"),
        authority_epoch: 9,
        migration_plan_digest: digest("migration-plan"),
        schema_digest: digest("schema"),
        rollback_predecessor_digest: digest("rollback-predecessor"),
    };
    let mut journal =
        DurableWriterHandoffJournalV1::create(handoff_file(&temp), plan).expect("create journal");
    journal
        .advance(step(
            WriterHandoffPhaseV1::AdmissionStopped,
            "admission-stopped",
            None,
        ))
        .expect("stop admission");
    journal
        .advance(step(WriterHandoffPhaseV1::Drained, "drained", Some(1)))
        .expect("record drain");

    old.release().await.expect("physically release old lease");
    journal
        .advance(step(
            WriterHandoffPhaseV1::OldWriterFenced,
            "old-writer-fenced",
            None,
        ))
        .expect("record old fence");

    let stale_old = old
        .admit("occurrence:stale-old", "memory.write", "must-not-commit")
        .await;
    assert!(
        stale_old.is_err(),
        "released predecessor handle must be rejected by the durable lease fence"
    );
    drop(old);
    drop(journal);

    let mut recovered = DurableWriterHandoffJournalV1::recover(handoff_file(&temp))
        .expect("recover handoff after old fence");
    assert_eq!(
        recovered.checkpoint().phase,
        WriterHandoffPhaseV1::OldWriterFenced
    );
    assert!(!recovered.checkpoint().old_writer_valid());
    assert!(!recovered.checkpoint().new_writer_admission_open());

    recovered
        .advance(step(WriterHandoffPhaseV1::Snapshotted, "snapshot", None))
        .expect("snapshot");
    recovered
        .advance(step(WriterHandoffPhaseV1::Migrated, "migrated", None))
        .expect("migrate");
    recovered
        .advance(step(WriterHandoffPhaseV1::Validated, "validated", None))
        .expect("validate");

    let successor = ProductionDurableWriter::open(
        store,
        authority(owner, 5, "successor"),
        &AllowVerifier,
        lease_id,
        2,
    )
    .await
    .expect("successor writer after durable predecessor release");
    recovered
        .advance(step(
            WriterHandoffPhaseV1::NewWriterFenced,
            "new-writer-fenced",
            None,
        ))
        .expect("record successor fence");
    assert!(!recovered.checkpoint().new_writer_admission_open());

    recovered
        .advance(step(
            WriterHandoffPhaseV1::RoutePublished,
            "route-published",
            None,
        ))
        .expect("publish route");
    assert!(recovered.checkpoint().new_writer_admission_open());
    successor
        .admit("occurrence:after-handoff", "memory.write", "payload-v2")
        .await
        .expect("successor admission after route publication");
    recovered
        .advance(step(WriterHandoffPhaseV1::Retired, "retired", None))
        .expect("retire old writer");
}
