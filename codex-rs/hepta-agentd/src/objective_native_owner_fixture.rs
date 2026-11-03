//! Existing Fleet/Agentd, signed ingress, seven owners and original Core queue.
//! Test keys represent independently installed authorities, never a production
//! default or a signer synthesized by the native loop.

use super::*;
use std::path::{Path, PathBuf};

use codex_hepta_evidence::HeptaEvidenceStore;
use codex_hepta_types::Generation;

use crate::authbus_ingress::TextIngress;

pub(super) struct ObjectiveFixture {
    pub(super) base: Fixture,
    pub(super) core: TestCodex,
    pub(super) queue: Arc<OriginalQueueTransport>,
    pub(super) host: Arc<ObjectiveRuntimeHost>,
    pub(super) owners: Arc<CanonicalObjectiveTestOwners>,
    pub(super) request: AuthBusObjectiveIngress,
    pub(super) trust_file: PathBuf,
    key: SigningKey,
}

impl ObjectiveFixture {
    pub(super) async fn new(server: &MockServer, fault: ReplyFault) -> Result<Self> {
        Self::with_agent(server, fault, agent()).await
    }

    pub(super) async fn with_agent(server: &MockServer, fault: ReplyFault, native_agent: NativeAgent) -> Result<Self> {
        Self::with_compiler(server, fault, native_agent, Arc::new(NoToolCompiler)).await
    }

    pub(super) async fn with_compiler(server: &MockServer, fault: ReplyFault, native_agent: NativeAgent,
        compiler: Arc<dyn NativeToolCompiler>) -> Result<Self> {
        Self::with_executor_adapter(server, fault, native_agent, compiler, |executor, _| executor).await
    }

    pub(super) async fn with_executor_adapter<F>(server: &MockServer, fault: ReplyFault,
        native_agent: NativeAgent, compiler: Arc<dyn NativeToolCompiler>, adapter: F) -> Result<Self>
    where F: FnOnce(Arc<dyn codex_core::hosted_turn::HostedTurnExecutor>, Arc<AgentdNativeHost>)
        -> Arc<dyn codex_core::hosted_turn::HostedTurnExecutor> {
        let mut base = Fixture::new(format!("{}/v1/responses", server.uri())).await?;
        base.native.compiler = compiler;
        let identity = base.state.identity();
        #[cfg(unix)]
        fs::set_permissions(&identity.home_root, fs::Permissions::from_mode(0o700))?;
        let (owners, runner) = CanonicalObjectiveTestOwners::new(&identity.home_root.join("objective-authority.json"))?;
        ensure!(base.state.intelligence_product.set(runner).is_ok(), "canonical runner already installed");
        ensure!(base.state.intelligence_invocation.set(owners.clone()).is_ok(), "canonical provider already installed");

        let key = SigningKey::from_bytes(&[83; 32]);
        let trust_file = identity.home_root.join("objective-trust.json");
        write_trust(&trust_file, identity, &key, ThreadId::new(), /*revoked*/ false, /*key_epoch*/ 1)?;
        // The independent checkpoint records the real evidence owner's empty
        // replay frontier; it is not a digest invented by the test/native path.
        let evidence = HeptaEvidenceStore::open(&SqliteConfig::from_sqlite_home(
            AbsolutePathBuf::try_from(identity.home_root.clone())?)).await?;
        let frontier = evidence.authbus_replay_frontier_digest().await?;
        drop(evidence);
        let checkpoint = base._temp.path().join("objective-authbus-checkpoint.json");
        private_file(&checkpoint, &serde_json::to_vec(&json!({
            "schema_version":1, "agent_id":identity.agent_id.as_str(),
            "generation":1, "digest":frontier.to_string(),
        }))?)?;
        let authbus = TextIngress::open(identity, trust_file.clone(), checkpoint).await?;
        ensure!(base.state.authbus.set(Arc::new(authbus)).is_ok(), "original AuthBus already installed");
        let profile = identity.home_root.join("objective-profile.json");
        private_file(&profile, &owners.profile_json()?)?;
        let queue = Arc::new(OriginalQueueTransport::new(fault));
        let mut host = ObjectiveRuntimeHost::open(identity, &profile)?;
        host.queue_transport = queue.clone();
        let host = Arc::new(host);
        ensure!(base.state.objective_runtime.set(host.clone()).is_ok(), "original Objective journal already installed");
        let native = Arc::new(AgentdNativeHost { gate: base.native.gate.clone(), host: base.native.host.clone(),
            model: base.native.model.clone(), runtime: base.native.runtime.clone(), compiler: base.native.compiler.clone() });
        let executor = NativeHostedRuntimeConfig::CanonicalObjective {
            agent: Arc::new(native_agent), scope: base.scope.clone(),
        }.attach(&base.state, native.clone())?;
        let executor = adapter(executor, native);
        let core = original_core(server, &queue, executor, identity, base.queue.clone()).await?;
        write_trust(&trust_file, identity, &key, core.session_configured.thread_id, /*revoked*/ false, /*key_epoch*/ 1)?;
        let digest = |label: &str| Digest32::of_bytes(label.as_bytes()).to_string();
        let request = AuthBusObjectiveIngress {
            issuer_id: "adapter.console".to_owned(), key_epoch: 1,
            message_id: "message.objective-native.1".to_owned(), sequence: 1,
            expires_at_ms: now_ms()? + 60_000, signature_hex: String::new(),
            body: AuthBusObjectiveBody {
                spawn_generation: identity.spawn_generation,
                run_id: "run.objective-native".to_owned(), objective_revision: 1,
                source_envelope_json: owners.source_json()?, runtime_body_digest: digest("objective runtime body"),
                preference_state_digest: digest("objective preferences"), model_tuple_digest: digest("objective model tuple"),
                prompt_registry_digest: digest("objective prompt registry"), artifact_set_digest: digest("objective artifacts"),
                authority_epoch: 11, queued_input: Some(ObjectiveQueuedInputV1 {
                    thread_id: core.session_configured.thread_id.to_string(), text: "Return the native owner result.".to_owned(),
                }),
            },
        };
        let mut value = Self { base, core, queue, host, owners, request, trust_file, key };
        let mut request = value.request.clone();
        value.sign(&mut request)?;
        value.request = request;
        Ok(value)
    }

    pub(super) fn sign(&self, request: &mut AuthBusObjectiveIngress) -> Result<()> {
        sign_objective(self.base.state.identity(), &self.key, request)
    }

    pub(super) async fn submit(&self, request: AuthBusObjectiveIngress) -> Result<ObjectiveRunAdmission> {
        match self.host.submit(&self.base.state, request, self.base.state.current_generation()?).await? {
            ObjectiveStartResult::Admitted(receipt) => Ok(receipt),
            ObjectiveStartResult::Conflict { run_id, conflict_digest } => {
                anyhow::bail!("unexpected original Objective conflict: {run_id}/{conflict_digest}")
            }
        }
    }

    pub(super) fn change_trust_at_grant(&self, revoked: bool, key_epoch: u64) -> Result<()> {
        let path = self.trust_file.clone();
        let identity = self.base.state.identity().clone();
        let key = self.key.clone();
        let thread = self.core.session_configured.thread_id;
        *self.base.issuer.before_grant_return.lock().map_err(|error| anyhow::anyhow!(error.to_string()))? = Some(Box::new(move || {
            write_trust(&path, &identity, &key, thread, revoked, key_epoch)
                .map_err(|error| AgentdError::Invalid(format!("original trust fixture: {error:#}")))
        }));
        Ok(())
    }

    pub(super) async fn shutdown(self) -> Result<()> {
        self.core.codex.shutdown_and_wait().await?;
        self.base.live.shutdown().await?;
        Ok(())
    }
}

fn sign_objective(identity: &crate::AgentdIdentity, key: &SigningKey, request: &mut AuthBusObjectiveIngress) -> Result<()> {
    let mut scope = b"hepta:agentd:signed-objective:v1\0".to_vec();
    scope.extend_from_slice(identity.agent_id.as_str().as_bytes());
    let claims = SignedMessageClaims {
        issuer_id: StableId::new(&request.issuer_id)?, key_epoch: Generation::new(request.key_epoch)?,
        message_id: StableId::new(&request.message_id)?, subject_id: StableId::new(identity.agent_id.as_str())?,
        scope_digest: Digest32::of_bytes(&scope), payload_digest: Digest32::of_bytes(&serde_json::to_vec(&request.body)?),
        sequence: request.sequence, expires_at_ms: request.expires_at_ms,
    };
    request.signature_hex = key.sign(&claims.signing_bytes()).to_bytes().iter()
        .map(|byte| format!("{byte:02x}")).collect();
    Ok(())
}

fn private_file(path: &Path, bytes: &[u8]) -> Result<()> {
    fs::write(path, bytes)?;
    #[cfg(unix)]
    fs::set_permissions(path, fs::Permissions::from_mode(0o600))?;
    Ok(())
}

fn write_trust(path: &Path, identity: &crate::AgentdIdentity, key: &SigningKey,
    thread: ThreadId, revoked: bool, key_epoch: u64) -> Result<()> {
    let public_key: String = key.verifying_key().to_bytes().iter().map(|byte| format!("{byte:02x}")).collect();
    private_file(path, &serde_json::to_vec(&json!({
        "schema_version":1, "agent_id":identity.agent_id.as_str(), "issuer_id":"adapter.console",
        "key_epoch":key_epoch, "public_key_hex":public_key, "revoked":revoked,
        "thread_ids":[thread.to_string()],
    }))?)
}

#[cfg(target_os = "linux")]
#[path = "native_daemon_lifecycle_tests.rs"]
mod daemon_lifecycle_tests;
