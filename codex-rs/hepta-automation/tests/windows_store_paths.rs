#![cfg(windows)]
#![allow(
    clippy::expect_used,
    reason = "integration assertions and fixture setup must fail the test immediately"
)]

use std::path::Component;
use std::path::Prefix;
use std::process::Command;

use codex_hepta_automation::AutomationError;
use codex_hepta_automation::AutomationSchedule;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::AutomationTaskDraft;
use codex_hepta_contracts::AgentId;
use codex_hepta_paths::HeptaFleetRoot;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const THREAD_ID: &str = "019153a4-3088-7e03-a56a-9b1964f75ddd";

fn ordinary_fleet_root(temp: &tempfile::TempDir, name: &str) -> HeptaFleetRoot {
    let canonical = temp
        .path()
        .canonicalize()
        .expect("canonical temporary root");
    let ordinary = AbsolutePathBuf::try_from(canonical)
        .expect("ordinary Windows namespace")
        .join(name);
    assert!(matches!(
        ordinary.components().next(),
        Some(Component::Prefix(prefix))
            if matches!(prefix.kind(), Prefix::Disk(_) | Prefix::UNC(..))
    ));
    HeptaFleetRoot::parse(ordinary.to_path_buf()).expect("absolute ordinary fleet root")
}

#[tokio::test]
async fn ordinary_fleet_root_persists_tasks_across_verbatim_reopen() {
    let temp = tempfile::tempdir().expect("private test root");
    let fleet = ordinary_fleet_root(&temp, "fleet");
    let agent_id = AgentId::parse(AGENT_ID).expect("agent identity");
    let layout = fleet.layout().agent(&agent_id);
    let store = AutomationStore::open(&layout)
        .await
        .expect("open production store from ordinary fleet root");
    let draft = AutomationTaskDraft::new(
        THREAD_ID,
        "persist across Windows namespace aliases",
        AutomationSchedule::Once,
        /*first_run_at_ms*/ 10,
        /*created_at_ms*/ 1,
    );
    let task = store.create_task(&draft).await.expect("durable task");
    store.close().await;

    let canonical = fleet.as_path().canonicalize().expect("verbatim fleet root");
    assert!(matches!(
        canonical.components().next(),
        Some(Component::Prefix(prefix))
            if matches!(prefix.kind(), Prefix::VerbatimDisk(_) | Prefix::VerbatimUNC(..))
    ));
    let verbatim = HeptaFleetRoot::parse(canonical).expect("absolute verbatim fleet root");
    let reopened = AutomationStore::open(&verbatim.layout().agent(&agent_id))
        .await
        .expect("reopen same durable store from verbatim fleet root");
    assert_eq!(reopened.owner_agent_id(), &agent_id);
    assert_eq!(
        reopened.task(task.task_id).await.expect("retained task"),
        Some(task)
    );
    reopened.close().await;
}

#[tokio::test]
async fn junction_fleet_root_is_rejected_before_opening_a_database() {
    let temp = tempfile::tempdir().expect("private test root");
    let actual = ordinary_fleet_root(&temp, "actual");
    let alias = ordinary_fleet_root(&temp, "alias");
    std::fs::create_dir(actual.as_path()).expect("junction target");
    // Junction creation needs no symlink privilege. Failure is a fixture
    // failure, never a skip or evidence that the store rejected redirection.
    let output = Command::new("cmd")
        .args(["/D", "/C", "mklink", "/J"])
        .arg(alias.as_path())
        .arg(actual.as_path())
        .output()
        .expect("create junction with cmd");
    assert!(
        output.status.success(),
        "mklink /J failed: stdout={} stderr={}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
    let agent_id = AgentId::parse(AGENT_ID).expect("agent identity");
    let layout = alias.layout().agent(&agent_id);
    assert!(matches!(
        AutomationStore::open(&layout).await,
        Err(AutomationError::Invalid)
    ));
    let actual_layout = actual.layout().agent(&agent_id);
    assert!(
        !actual_layout
            .automation_root()
            .join("automation_1.sqlite3")
            .exists(),
        "a redirected fleet root must not create a database"
    );
}
