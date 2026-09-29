//! Cross-process archive qualification through the real owner and signed host CLI.

#![cfg(target_os = "linux")]

use std::error::Error;
use std::path::Path;
use std::process::Command;

use codex_hepta_contracts::AgentId;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::ForgetMemoryDraft;
use codex_hepta_memory::KgFactSetDraft;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::SourceDraft;
use codex_hepta_paths::HeptaFleetRoot;
use tempfile::TempDir;

#[tokio::test]
#[ignore = "requires the archive Python dependencies; explicitly run by cognitive qualification"]
async fn signed_archive_restores_real_correction_and_tombstone_history()
-> Result<(), Box<dyn Error>> {
    let temp = TempDir::new()?;
    let root = temp.path().canonicalize()?;
    let fleet = root.join("fleet");
    std::fs::create_dir_all(&fleet)?;
    let owner = AgentId::parse("00000000-0000-4000-8000-00000000ca81")?;
    let layout = HeptaFleetRoot::parse(fleet)?.layout().agent(&owner);
    let access = CognitiveAccess::agent_private(owner);
    let store = CognitiveStore::open(&layout).await?;
    let source = |index: usize, content: &str| SourceDraft {
        scope: CognitiveScope::AgentPrivate,
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: format!("archive-oracle-{index}"),
        content: content.as_bytes().to_vec(),
        observed_at_unix_seconds: 1,
    };
    let revision = |content: &str| MemoryRevisionDraft {
        scope: CognitiveScope::AgentPrivate,
        content: content.to_string(),
        verification: MemoryVerification::Verified,
        lifecycle: MemoryLifecycleState::Active,
        valid_from_unix_seconds: 1,
        valid_to_unix_seconds: None,
        citations: Vec::new(),
    };
    let remembered = store
        .remember_with_kg(
            &access,
            &source(1, "original historical source"),
            &MemoryDraft {
                stable_key: "archive-oracle-memory".to_string(),
                revision: revision("original historical source"),
            },
            &KgFactSetDraft::default(),
        )
        .await?;
    let id = remembered.memory.id.memory_id;
    store
        .correct_with_kg(
            &access,
            &id,
            1,
            &source(2, "corrected historical source"),
            &revision("corrected historical source"),
            &KgFactSetDraft::default(),
        )
        .await?;
    store
        .forget_with_kg(
            &access,
            &id,
            2,
            &source(3, "terminal archive fixture tombstone"),
            &ForgetMemoryDraft {
                scope: CognitiveScope::AgentPrivate,
                reason: "terminal archive fixture tombstone".to_string(),
                valid_from_unix_seconds: 2,
                citations: Vec::new(),
            },
        )
        .await?;
    let anchor = store.recovery_anchor().await?;
    let witness = root.join("independently-supplied-test-cut.json");
    std::fs::write(&witness, serde_json::to_vec(&anchor)?)?;
    let repository = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .ok_or("missing repository root")?;
    let python = std::env::var_os("HEPTA_COGNITIVE_ARCHIVE_PYTHON")
        .ok_or("archive qualification requires its pinned Python environment")?;
    if !Path::new(&python).is_absolute() {
        return Err("archive qualification Python must be an absolute path".into());
    }
    let verifier = root.join("cognitive-store-archive-check");
    std::fs::copy(
        env!("CARGO_BIN_EXE_cognitive-store-archive-check"),
        &verifier,
    )?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&verifier, std::fs::Permissions::from_mode(0o700))?;
    }
    std::fs::File::open(&verifier)?.sync_all()?;
    let output = Command::new(python)
        .arg(repository.join("tools/cognitive-store-host-bootstrap/test_archive.py"))
        .arg("--owner-image")
        .arg(store.path())
        .arg("--anchor")
        .arg(witness)
        .arg("--verifier")
        .arg(&verifier)
        .output()?;
    assert!(
        output.status.success(),
        "real-owner archive/restore failed\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
    assert_eq!(store.recovery_anchor().await?, anchor);
    Ok(())
}
