use std::path::Path;
use std::path::PathBuf;

use codex_extension_api::EPHEMERAL_MODEL_INPUT_MAX_CONTENT_BYTES;
use codex_extension_api::EPHEMERAL_MODEL_INPUT_MAX_CONTENT_TOKENS;
use codex_extension_api::EPHEMERAL_MODEL_INPUT_SCHEMA_VERSION;
use codex_extension_api::EphemeralModelInputContext;
use codex_extension_api::EphemeralModelInputContributor;
use codex_extension_api::EphemeralModelInputProposal;
use codex_extension_api::ExtensionData;
use codex_extension_api::ModelProviderRequestKind;
use codex_extension_api::ModelProviderSha256Digest;
use codex_extension_api::ModelProviderTransport;
use codex_extension_api::TurnInputContext;
use codex_extension_api::TurnInputContributor;
use codex_extension_api::TurnInputEnvironment;
use codex_hepta_contracts::AgentId;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveRuntime;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::FederationGrantRequest;
use codex_hepta_memory::FederationGrantScope;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::SourceDraft;
use codex_hepta_paths::HeptaFleetRoot;
use codex_protocol::user_input::UserInput;
use codex_utils_path_uri::PathUri;

use super::FederatedCognitiveExtension;
use super::now_unix_seconds;
use super::workspace_identity::from_transport;
use crate::extension::HeptaMemoryThreadState;
use crate::framing::workspace_digest;

const THREAD_ID: &str = "00000000-0000-4000-8000-000000000721";
const OWNER_ID: &str = "00000000-0000-4000-8000-000000000722";
const CONSUMER_ID: &str = "00000000-0000-4000-8000-000000000723";

struct Fixture {
    temp: tempfile::TempDir,
    workspace: PathBuf,
    owner: CognitiveStore,
    owner_access: CognitiveAccess,
    consumer_id: AgentId,
    runtime: CognitiveRuntime,
}

impl Fixture {
    async fn new() -> Self {
        let temp = tempfile::tempdir().expect("tempdir");
        let root = temp.path().canonicalize().expect("canonical root");
        let fleet_root = root.join("fleet");
        std::fs::create_dir_all(&fleet_root).expect("fleet root");
        let fleet = HeptaFleetRoot::parse(fleet_root).expect("fleet").layout();
        let owner_id = AgentId::parse(OWNER_ID).expect("owner id");
        let consumer_id = AgentId::parse(CONSUMER_ID).expect("consumer id");
        let owner_layout = fleet.agent(&owner_id);
        let owner = CognitiveStore::open(&owner_layout)
            .await
            .expect("owner store");
        let consumer = CognitiveStore::open(&fleet.agent(&consumer_id))
            .await
            .expect("consumer store");
        let owner_access = CognitiveAccess::agent_private(owner_id);
        let now = now_unix_seconds().expect("time");
        let citation = owner
            .append_source(
                &owner_access,
                &SourceDraft {
                    scope: CognitiveScope::AgentPrivate,
                    kind: LedgerSourceKind::ExplicitMemoryDirective,
                    event_key: "federation-workspace-identity-source".to_string(),
                    content: b"workspace identity copper observatory".to_vec(),
                    observed_at_unix_seconds: now,
                },
            )
            .await
            .expect("source");
        owner
            .remember_memory(
                &owner_access,
                &MemoryDraft {
                    stable_key: "federation-workspace-identity-memory".to_string(),
                    revision: MemoryRevisionDraft {
                        scope: CognitiveScope::AgentPrivate,
                        content: "workspace identity copper observatory verified memory"
                            .to_string(),
                        verification: MemoryVerification::Verified,
                        lifecycle: MemoryLifecycleState::Active,
                        valid_from_unix_seconds: now - 1,
                        valid_to_unix_seconds: None,
                        citations: vec![citation],
                    },
                },
            )
            .await
            .expect("memory");
        let workspace = root.join("consumer-workspace");
        std::fs::create_dir_all(&workspace).expect("workspace");
        let workspace = workspace.canonicalize().expect("canonical workspace");
        let runtime = CognitiveRuntime::from_open_result(Ok(consumer))
            .with_federation_sources(consumer_id.clone(), vec![owner_layout]);
        Self {
            temp,
            workspace,
            owner,
            owner_access,
            consumer_id,
            runtime,
        }
    }

    async fn grant(&self, workspace: &Path) {
        let now = now_unix_seconds().expect("time");
        self.owner
            .grant_federated_recall(
                &self.owner_access,
                &FederationGrantRequest {
                    consumer_agent_id: self.consumer_id.clone(),
                    scope: FederationGrantScope::new(
                        CognitiveScope::AgentPrivate,
                        workspace_digest(workspace),
                    ),
                    effective_at_unix_seconds: now - 1,
                    expires_at_unix_seconds: now + 3_600,
                },
            )
            .await
            .expect("grant");
    }

    async fn prepare(&self) -> Prepared {
        let extension = FederatedCognitiveExtension::from_runtime(self.runtime.clone());
        let session = ExtensionData::new("workspace-identity-session");
        let thread = ExtensionData::new(THREAD_ID);
        thread.insert(HeptaMemoryThreadState::for_cognitive_test(true));
        let turn = ExtensionData::new("workspace-identity-turn");
        let step = ExtensionData::new(turn.level_id());
        let fragments = TurnInputContributor::contribute(
            &extension,
            TurnInputContext {
                turn_id: turn.level_id().to_string(),
                user_input: vec![UserInput::Text {
                    text: "workspace identity copper observatory".to_string(),
                    text_elements: Vec::new(),
                }],
                environments: vec![TurnInputEnvironment {
                    environment_id: "primary".to_string(),
                    cwd: PathUri::from_host_native_path(&self.workspace).expect("workspace uri"),
                    is_primary: true,
                }],
            },
            None,
            &session,
            &thread,
            &turn,
            &step,
        )
        .await;
        assert!(fragments.is_empty());
        Prepared {
            extension,
            session,
            thread,
            turn,
        }
    }
}

struct Prepared {
    extension: FederatedCognitiveExtension,
    session: ExtensionData,
    thread: ExtensionData,
    turn: ExtensionData,
}

impl Prepared {
    fn is_active(&self) -> bool {
        EphemeralModelInputContributor::is_active(&self.extension, &self.thread, &self.turn)
    }

    async fn proposal(&self, cwd: &Path) -> Option<EphemeralModelInputProposal> {
        let base = ModelProviderSha256Digest::parse("3".repeat(64)).expect("base digest");
        EphemeralModelInputContributor::contribute(
            &self.extension,
            EphemeralModelInputContext {
                schema_version: EPHEMERAL_MODEL_INPUT_SCHEMA_VERSION,
                session_store: &self.session,
                thread_store: &self.thread,
                turn_store: &self.turn,
                attempt_id: "model-provider-attempt:v1:workspace-identity",
                base_logical_request_sha256: &base,
                thread_id: THREAD_ID,
                turn_id: self.turn.level_id(),
                cwd,
                request_kind: ModelProviderRequestKind::Turn,
                provider_id: "workspace-identity-provider",
                model: "workspace-identity-model",
                transport: ModelProviderTransport::Http,
                generate: true,
                model_context_window: Some(128_000),
                max_content_bytes: EPHEMERAL_MODEL_INPUT_MAX_CONTENT_BYTES,
                max_content_tokens: EPHEMERAL_MODEL_INPUT_MAX_CONTENT_TOKENS,
            },
        )
        .await
        .expect("contributor")
    }
}

fn junction(link: &Path, target: &Path) {
    let link = PathUri::from_host_native_path(link)
        .expect("junction link uri")
        .to_path_buf();
    let target = PathUri::from_host_native_path(target)
        .expect("junction target uri")
        .to_path_buf();
    let output = std::process::Command::new("cmd.exe")
        .args(["/C", "mklink", "/J"])
        .arg(link)
        .arg(target)
        .output()
        .expect("create junction command");
    assert!(output.status.success(), "{output:?}");
}

#[test]
fn canonical_workspace_restores_transport_without_equating_v1_digests() {
    let temp = tempfile::tempdir().expect("tempdir");
    let canonical = temp.path().canonicalize().expect("canonical workspace");
    let logical = PathUri::from_host_native_path(&canonical)
        .expect("workspace uri")
        .to_path_buf();
    assert_ne!(canonical, logical);
    assert_ne!(workspace_digest(&canonical), workspace_digest(&logical));
    assert_eq!(
        from_transport(&canonical).expect("canonical identity"),
        canonical
    );
    assert_eq!(
        from_transport(&logical).expect("transport identity"),
        canonical
    );
}

#[test]
fn canonical_workspace_rejects_symlink_alias_and_preserves_missing_error() {
    let temp = tempfile::tempdir().expect("tempdir");
    let root = temp.path().canonicalize().expect("canonical root");
    let target = root.join("target");
    std::fs::create_dir(&target).expect("target");
    let alias = root.join("alias");
    junction(&alias, &target);
    assert_eq!(
        from_transport(&alias).expect_err("alias rejected").kind(),
        std::io::ErrorKind::InvalidInput
    );
    std::fs::remove_dir(&alias).expect("remove junction");
    let missing = root.join("missing");
    let native = missing.canonicalize().expect_err("missing path");
    let actual = from_transport(&missing).expect_err("missing path rejected");
    assert_eq!(actual.kind(), native.kind());
    assert_eq!(actual.raw_os_error(), native.raw_os_error());
    let file = root.join("file");
    std::fs::write(&file, b"file").expect("file");
    assert_eq!(
        from_transport(&file).expect_err("file rejected").kind(),
        std::io::ErrorKind::InvalidInput
    );
}

#[tokio::test]
async fn normalized_byte_grant_does_not_authorize_canonical_workspace() {
    let fixture = Fixture::new().await;
    let logical = PathUri::from_host_native_path(&fixture.workspace)
        .expect("workspace uri")
        .to_path_buf();
    assert_ne!(
        workspace_digest(&logical),
        workspace_digest(&fixture.workspace)
    );
    fixture.grant(&logical).await;
    let rejected = fixture.prepare().await;
    assert!(!rejected.is_active());
    assert!(rejected.proposal(&fixture.workspace).await.is_none());
    fixture.grant(&fixture.workspace).await;
    let accepted = fixture.prepare().await;
    assert!(accepted.is_active());
    assert!(accepted.proposal(&fixture.workspace).await.is_some());
}

#[tokio::test]
async fn physical_send_rejects_other_moved_and_retargeted_workspace() {
    let fixture = Fixture::new().await;
    fixture.grant(&fixture.workspace).await;
    let prepared = fixture.prepare().await;
    assert!(prepared.is_active());
    assert!(prepared.proposal(&fixture.workspace).await.is_some());
    let other = fixture.temp.path().join("other-workspace");
    std::fs::create_dir(&other).expect("other workspace");
    let other = other.canonicalize().expect("canonical other workspace");
    assert!(prepared.proposal(&other).await.is_none());
    let moved = fixture.temp.path().join("moved-workspace");
    std::fs::rename(&fixture.workspace, &moved).expect("move workspace");
    assert!(prepared.proposal(&fixture.workspace).await.is_none());
    assert!(prepared.proposal(&moved).await.is_none());
    junction(&fixture.workspace, &other);
    assert!(prepared.proposal(&fixture.workspace).await.is_none());
    std::fs::remove_dir(&fixture.workspace).expect("remove junction");
}
