//! Actual Root image admission; controlled owner files, no deployed writer.

use super::*;
use crate::authority_host_material::PreparedCheckpointMaterial;
use crate::authority_host_material::RegisteredMaterialArchive;

fn protected_exchange(
    backend: &HostCognitiveCheckpoint,
    request: &CognitiveCheckpointRequest,
    material: Option<&PreparedCheckpointMaterial>,
) -> CognitiveCheckpointResponse {
    serde_json::from_slice(&backend.exchange_with_material(&serde_json::to_vec(request).unwrap(), material).unwrap()).unwrap()
}

fn dirty(f: &Fixture) -> CognitiveCheckpointResponse {
    let first = protected_exchange(&f.backend, &f.request(1, CognitiveCheckpointCommand::ReadHead, None, None), None);
    protected_exchange(&f.backend, &f.request(2, CognitiveCheckpointCommand::BeginWrites, first.token, None), None)
}

fn owner_layout(f: &Fixture) -> codex_hepta_paths::HeptaAgentLayout {
    let layout = HeptaFleetRoot::parse(f._temp.path().join("fleet")).unwrap().layout().agent(&f.initial_cut.owner_agent_id);
    for entry in std::fs::read_dir(layout.cognitive_root()).unwrap() {
        let path = entry.unwrap().path();
        if path.is_file() {
            std::os::unix::fs::chown(&path, Some(60001), Some(60001)).unwrap();
        }
    }
    std::os::unix::fs::chown(layout.cognitive_root(), Some(60001), Some(60001)).unwrap();
    layout
}

fn archive_root(f: &Fixture) -> std::path::PathBuf {
    let path = f._temp.path().join("physical-material");
    std::fs::create_dir(&path).unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
    path
}

#[tokio::test]
#[ignore = "explicit actual Root protected image qualification"]
async fn root_material_prepare_without_image_never_advances_dirty_head() {
    let f = Fixture::new().await;
    let current = dirty(&f);
    ack(&current, CognitiveCheckpointPhase::Dirty, 2);
    let request = f.request(3, CognitiveCheckpointCommand::PreparePublication, current.token, Some(f.proposal()));
    let refused = protected_exchange(&f.backend, &request, None);
    assert_eq!(refused.status, CognitiveCheckpointStatus::Unknown);
    assert_eq!(f.reopen().load().unwrap(), current.head.unwrap());
    assert_eq!(protected_exchange(&f.backend, &f.request(4, CognitiveCheckpointCommand::ReadHead, None, None), None).status, CognitiveCheckpointStatus::Unknown);
}

#[tokio::test]
#[ignore = "explicit actual Root protected image qualification"]
async fn root_material_commit_without_image_never_promotes_proposal() {
    let f = Fixture::new().await;
    let current = dirty(&f);
    let request = f.request(3, CognitiveCheckpointCommand::PreparePublication, current.token, Some(f.proposal()));
    // Deliberate metadata-protocol setup, never the production service path.
    let publishing = exchange(&f.backend, &request);
    ack(&publishing, CognitiveCheckpointPhase::Publishing, 3);
    let commit = f.request(4, CognitiveCheckpointCommand::CommitPublication, publishing.token, None);
    assert_eq!(protected_exchange(&f.backend, &commit, None).status, CognitiveCheckpointStatus::Unknown);
    assert_eq!(f.reopen().load().unwrap(), publishing.head.unwrap());
}

#[tokio::test]
#[ignore = "explicit actual Root protected image qualification"]
async fn root_material_full_cycle_retains_exact_image_and_missing_duplicate_refuses() {
    let f = Fixture::new().await;
    let layout = owner_layout(&f);
    let root = archive_root(&f);
    let dirty = dirty(&f);
    let prepare = f.request(3, CognitiveCheckpointCommand::PreparePublication, dirty.token, Some(f.proposal()));
    let raw = serde_json::to_vec(&prepare).unwrap();
    let cut = f.initial_cut.clone();
    let backend = f.backend.clone();
    let registration = f.registration.clone();
    let final_response = std::thread::spawn(move || {
        let archive = RegisteredMaterialArchive::register(&layout, 60001, &root).unwrap();
        let prepared = archive.prepare(&raw, &cut).unwrap();
        assert!(prepared.validate(b"another request", &cut).is_err());
        let publishing = protected_exchange(&backend, &prepare, Some(&prepared));
        ack(&publishing, CognitiveCheckpointPhase::Publishing, 3);
        let commit = CognitiveCheckpointRequest {
            schema_version: 1, operation: OPERATION.into(),
            request_id: format!("{:016x}{:016x}", registration.publisher_epoch, 4),
            command: CognitiveCheckpointCommand::CommitPublication,
            expected: publishing.token.clone(), proposal: None,
        };
        let commit_raw = serde_json::to_vec(&commit).unwrap();
        let retained = archive.retained(&commit_raw, &cut).unwrap();
        let cache_entry = std::fs::read_dir(&root).unwrap().next().unwrap().unwrap().path();
        let destination = HeptaFleetRoot::parse(cache_entry).unwrap().layout().agent(&cut.owner_agent_id);
        let database = std::fs::read_dir(destination.cognitive_root()).unwrap()
            .map(|entry| entry.unwrap().path()).find(|path| path.extension().is_some_and(|extension| extension == "sqlite3")).unwrap();
        let before = std::fs::read(&database).unwrap();
        let current = protected_exchange(&backend, &commit, Some(&retained));
        ack(&current, CognitiveCheckpointPhase::Current, 4);
        let duplicate = archive.retained(&commit_raw, &cut).unwrap();
        assert_eq!(std::fs::read(&database).unwrap(), before);
        assert_eq!(protected_exchange(&backend, &commit, Some(&duplicate)), current);
        std::fs::remove_file(&database).unwrap();
        assert!(archive.retained(&commit_raw, &cut).is_err());
        assert_eq!(protected_exchange(&backend, &commit, Some(&duplicate)).status, CognitiveCheckpointStatus::Unknown);
        current
    }).join().unwrap();
    assert_eq!(f.reopen().load().unwrap(), final_response.head.unwrap());
}

#[tokio::test]
#[ignore = "explicit actual Root protected image qualification"]
async fn root_material_source_inode_replacement_is_not_automatically_registered() {
    let f = Fixture::new().await;
    let layout = owner_layout(&f);
    let root = archive_root(&f);
    let cut = f.initial_cut.clone();
    std::thread::spawn(move || {
        let archive = RegisteredMaterialArchive::register(&layout, 60001, &root).unwrap();
        archive.prepare(b"first exact request", &cut).unwrap();
        let source = std::fs::read_dir(layout.cognitive_root()).unwrap()
            .map(|entry| entry.unwrap().path()).find(|path| path.extension().is_some_and(|extension| extension == "sqlite3")).unwrap();
        let displaced = source.with_extension("retained-original");
        std::fs::rename(&source, &displaced).unwrap();
        std::fs::copy(&displaced, &source).unwrap();
        std::os::unix::fs::chown(&source, Some(60001), Some(60001)).unwrap();
        assert!(archive.prepare(b"another exact request", &cut).is_err());
        assert!(archive.retained(b"read existing retained image", &cut).is_ok());
    }).join().unwrap();
    assert_eq!(f.backend.load().unwrap().counter, 1);
}
