#![cfg(test)]

//! Real control server and original production composition. Keys, checkpoints
//! and final-use probes here are explicit qualification fixtures, not product trust.

use super::fixture::Checkpoint;
use super::fixture::Fixture;
use super::fixture::Probes;
use super::*;
use crate::AgentdClient;
use crate::AgentdIdentity;
use crate::AgentdObjectiveClient;
use crate::AgentdObjectivePeer;
use crate::AgentdState;
use crate::AuthBusObjectiveBody;
use crate::AuthBusObjectiveIngress;
use crate::ObjectiveClientMode;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_memory::ObjectiveSenderOrigin;
use codex_hepta_memory::ObjectiveSenderRequest;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::json;
use std::error::Error;
use std::fs::File;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio_util::sync::CancellationToken;

pub(super) type TestResult<T = ()> = Result<T, Box<dyn Error>>;

#[derive(Clone, Copy)]
pub(super) enum ReplyDelivery {
    Complete,
    DropFirstSubmissionAck,
}

pub(super) struct ControlFixture {
    pub identity: AgentdIdentity,
    pub state: Arc<AgentdState>,
    pub host: Arc<crate::AgentdProductionWriterHost>,
    pub attachment: Option<AgentdProductionHostAttachment<Checkpoint>>,
    pub original: ObjectiveSenderRequest,
    pub probes: Probes,
    pub starts: Arc<AtomicUsize>,
    pub relay_path: PathBuf,
    cancellation: CancellationToken,
    tasks: Vec<tokio::task::JoinHandle<Result<(), AgentdError>>>,
    _writer_lock: File,
    _issuer_peer: UnixStream,
    _fixture: Fixture,
}

impl ControlFixture {
    pub async fn new(run_id: &str, draft: &str, replies: ReplyDelivery) -> TestResult<Self> {
        let (mut config, fixture) = Fixture::new().await?;
        let (inputs, probes, issuer_peer) = fixture.inputs()?;
        let attachment = attach_production_operation_host(&mut config, inputs).await?;
        let host = config
            .production_writer_host()
            .ok_or("original host missing")?;
        let operations = config
            .take_production_operations()
            .ok_or("original operations missing")?;
        let (host, _) = operations.attach(host).await?;
        let (identity, registry, writer_lock) = config.into_parts();
        let state = Arc::new(AgentdState::new(identity.clone(), registry.clone(), 128)?);
        let cognitive = host.cognitive_runtime();
        state.attach_cognitive_store(Arc::clone(
            cognitive
                .available_store()
                .ok_or("original store missing")?,
        ))?;
        state.attach_production_operations(Arc::clone(&host))?;
        let root = identity.fleet_root.parent().ok_or("test root missing")?;
        let trust = identity.home_root.join("original-objective-ui-trust.json");
        let key = SigningKey::from_bytes(&[83; 32]);
        write_private(
            &trust,
            &serde_json::to_vec(&json!({
                "schema_version":1, "agent_id":identity.agent_id.as_str(),
                "issuer_id":"issuer.production", "key_epoch":1,
                "public_key_hex":hex(key.verifying_key().as_bytes()),
                "revoked":false, "thread_ids":["thread.objective"]
            }))?,
        )?;
        let checkpoint = root.join("independent-authbus-checkpoint.json");
        // Capture the canonical empty fixture owner's initial frontier before
        // accepting any request. A recovered/suspect store must never supply
        // its own external trust checkpoint.
        let evidence = codex_hepta_evidence::HeptaEvidenceStore::open(
            &codex_state::SqliteConfig::from_sqlite_home(
                codex_utils_absolute_path::AbsolutePathBuf::from_absolute_path(
                    &identity.home_root,
                )?,
            ),
        )
        .await?;
        if evidence.authbus_restore_checkpoint().await?.is_some() {
            return Err("new control fixture already has an AuthBus checkpoint".into());
        }
        let frontier = evidence.authbus_replay_frontier_digest().await?;
        drop(evidence);
        write_private(
            &checkpoint,
            &serde_json::to_vec(&json!({
                "schema_version":1, "agent_id":identity.agent_id.as_str(), "generation":1,
                "digest":frontier.to_string()
            }))?,
        )?;
        let ingress =
            crate::authbus_ingress::TextIngress::open(&identity, trust, checkpoint).await?;
        state
            .authbus
            .set(Arc::new(ingress))
            .map_err(|_| "AuthBus already installed")?;
        let profile = identity.home_root.join("original-objective-profile.json");
        write_private(&profile, &profile_json()?)?;
        let objective = crate::objective_runtime::ObjectiveRuntimeHost::open(&identity, &profile)?;
        state
            .objective_runtime
            .set(Arc::new(objective))
            .map_err(|_| "Objective already installed")?;
        state.mark_runtime_prerequisites_ready()?;
        registry.compare_and_transition(
            &identity.agent_id,
            1,
            codex_hepta_fleet::AgentLifecycle::Running,
        )?;
        state.refresh_generation()?;
        // This suite qualifies control admission, not a model execution. The
        // original prerequisite transition is explicit; no model is invoked.
        state.mark_app_server_ready()?;
        let cancellation = CancellationToken::new();
        let control = crate::control::AgentdControlServer::bind(
            identity.control_socket.clone(),
            Arc::clone(&state),
            cancellation.clone(),
        )
        .await?;
        let control_task = tokio::spawn(control.run());
        let relay_path = root.join("objective-control-relay.sock");
        let relay = tokio::net::UnixListener::bind(&relay_path)?;
        std::fs::set_permissions(&relay_path, std::fs::Permissions::from_mode(0o600))?;
        let starts = Arc::new(AtomicUsize::new(0));
        let relay_task = tokio::spawn(relay_frames(
            relay,
            identity.control_socket.clone(),
            cancellation.clone(),
            starts.clone(),
            replies,
        ));
        let original = signed_request(&identity, &relay_path, run_id, draft, &key)?;
        Ok(Self {
            identity,
            state,
            host,
            attachment: Some(attachment),
            original,
            probes,
            starts,
            relay_path,
            cancellation,
            tasks: vec![control_task, relay_task],
            _writer_lock: writer_lock,
            _issuer_peer: issuer_peer,
            _fixture: fixture,
        })
    }

    pub fn peer(&self) -> AgentdObjectivePeer {
        AgentdObjectivePeer {
            // SAFETY: geteuid reads the current process identity.
            uid: unsafe { libc::geteuid() },
            pid: std::process::id(),
        }
    }

    pub fn transport(&self) -> Result<AgentdClient, AgentdError> {
        AgentdClient::new(self.relay_path.clone(), self.identity.agent_id.clone(), 1)
    }

    pub fn take_attachment(&mut self) -> TestResult<AgentdProductionHostAttachment<Checkpoint>> {
        match self.attachment.take() {
            Some(attachment) => Ok(attachment),
            None => Ok(AgentdProductionHostAttachment {
                notes_identity: None,
                original_sender: self.host.writer().objective_sender(
                    Arc::clone(&self.probes.checkpoint),
                    Duration::from_secs(1),
                )?,
            }),
        }
    }

    pub fn client(
        &mut self,
        mode: ObjectiveClientMode,
    ) -> TestResult<AgentdObjectiveClient<Checkpoint>> {
        let attachment = self.take_attachment()?;
        Ok(self.transport()?.bind_original_objective(
            attachment.original_sender,
            self.original.clone(),
            self.peer(),
            mode,
        )?)
    }

    pub async fn finish(mut self) -> TestResult {
        self.cancellation.cancel();
        for task in self.tasks.drain(..) {
            tokio::time::timeout(Duration::from_secs(3), task).await???;
        }
        Ok(())
    }
}

impl Drop for ControlFixture {
    fn drop(&mut self) {
        self.cancellation.cancel();
    }
}

// Fault injection forwards exact frames to the actual AgentdControlServer and
// only discards one real response. It does not synthesize admission or history.
async fn relay_frames(
    listener: tokio::net::UnixListener,
    actual: PathBuf,
    cancellation: CancellationToken,
    starts: Arc<AtomicUsize>,
    replies: ReplyDelivery,
) -> Result<(), AgentdError> {
    loop {
        let (stream, _) = tokio::select! {
            _ = cancellation.cancelled() => return Ok(()),
            accepted = listener.accept() => accepted?,
        };
        let (reader, mut caller) = tokio::io::split(stream);
        let mut reader = BufReader::new(reader).take(crate::MAX_CONTROL_FRAME_BYTES + 1);
        let mut bytes = Vec::new();
        if reader.read_until(b'\n', &mut bytes).await? == 0 {
            continue;
        }
        let request: crate::AgentdRequest = serde_json::from_slice(&bytes)?;
        let submission = matches!(request.method, crate::AgentdMethod::ObjectiveStart { .. });
        let count = if submission {
            starts.fetch_add(1, Ordering::SeqCst) + 1
        } else {
            0
        };
        let original = tokio::net::UnixStream::connect(&actual).await?;
        let (reader, mut writer) = tokio::io::split(original);
        writer.write_all(&bytes).await?;
        let mut reader = BufReader::new(reader).take(crate::MAX_CONTROL_FRAME_BYTES + 1);
        let mut reply = Vec::new();
        reader.read_until(b'\n', &mut reply).await?;
        if submission && count == 1 && matches!(replies, ReplyDelivery::DropFirstSubmissionAck) {
            continue;
        }
        caller.write_all(&reply).await?;
        caller.shutdown().await?;
    }
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn write_private(path: &Path, bytes: &[u8]) -> TestResult {
    std::fs::write(path, bytes)?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
    Ok(())
}

fn resource(name: &str, class: &str, suffix: usize) -> serde_json::Value {
    json!({"constraintId":format!("resource.{name}.{suffix}"),"axis":format!("resource.{name}"),
        "class":class,"q32PerSourceUnit":1,"evidenceSource":"profile.resource"})
}

fn profile_json() -> TestResult<Vec<u8>> {
    let risk = json!({
        "evidenceSource":"profile.risk","class":"principal","riskConstraintId":"risk.class","riskAxis":"risk.value",
        "lowValueQ32":0,"mediumValueQ32":1,"highValueQ32":2,"criticalValueQ32":3,
        "rollbackConstraintId":"risk.rollback","rollbackAxis":"risk.rollback.value",
        "rollbackNoneValueQ32":0,"rollbackReversibleValueQ32":1,"rollbackCompensatableValueQ32":2,"rollbackIrreversibleValueQ32":3,
        "compensationConstraintId":"risk.compensation","compensationAxis":"risk.compensation.value",
        "compensationFalseValueQ32":0,"compensationTrueValueQ32":1,
        "abstentionConstraintId":"risk.abstention","abstentionAxis":"risk.abstention.value",
        "abstentionRules":[{"sourceRule":"ask","valueQ32":1}]
    });
    Ok(serde_json::to_vec(&json!({
        "profileId":"objective.profile.production.v1","profileRevision":1,
        "expectedInputSchemaDigest":"1".repeat(64),"expectedNormalizationProfileDigest":"2".repeat(64),
        "principalScopeDigest":"3".repeat(64),"principalScope":"principal.production",
        "allowedLocales":["en-US"],"maximumSourceAgeMicros":60000000,"maximumFutureSkewMicros":1000000,
        "deadlineRequired":true,"allowedTrustedSourceIdentities":["issuer.production"],
        "constraints":[{"sourceConstraintId":"latency.ceiling","expectedUnit":"micros","class":"task","axis":"latency.micros"}],
        "predicates":[
            {"sourcePredicateId":"task.success","expectedUnit":"ratio","axis":"task.success.ratio"},
            {"sourcePredicateId":"task.terminal","expectedUnit":"boolean","axis":"task.terminal"}
        ],
        "actions":[{"sourceActionClass":"read","actionId":"action.read"}],
        "softDimensions":[{"sourceDimensionId":"quality","expectedUnit":"ratio","expectedDirection":"maximize","dimension":"quality.ratio","baselineWeightQ32":2147483648_i64}],
        "evidenceRequirements":[{"sourceRequirementId":"evidence.quality","axis":"evidence.confidence"}],
        "resources":{
            "timeMicros":resource("time","task",1),"tokenCount":resource("tokens","task",2),
            "computeMicros":resource("compute","environment",3),"memoryBytes":resource("memory","environment",4),
            "networkBytes":resource("network","principal",5),"externalEffectCount":resource("effects","principal",6)
        },
        "risk":risk
    }))?)
}

fn timestamp(seconds: u64) -> TestResult<String> {
    // The original composition is Linux-specific. Use the system's UTC calendar
    // conversion rather than freezing a test date that will expire in CI.
    let output = std::process::Command::new("date")
        .args([
            "--utc",
            "--date",
            &format!("@{seconds}"),
            "+%Y-%m-%dT%H:%M:%SZ",
        ])
        .output()?;
    if !output.status.success() {
        return Err("UTC test timestamp failed".into());
    }
    Ok(String::from_utf8(output.stdout)?.trim().to_string())
}

fn signed_request(
    identity: &AgentdIdentity,
    socket: &Path,
    run_id: &str,
    draft: &str,
    key: &SigningKey,
) -> TestResult<ObjectiveSenderRequest> {
    let now = crate::authbus_ingress::now_ms()?;
    let mut source = json!({
        "requestId":"desktop.original.request","principalScopeDigest":"3".repeat(64),
        "intentDigest":"0".repeat(64),
        "structuredIntent":{
            "successPredicates":[{"predicateId":"task.success","unit":"ratio","comparator":"gte","boundQ32":2147483648_i64,"evidenceSourceId":"observer.task","terminal":false}],
            "terminalConditions":[{"predicateId":"task.terminal","unit":"boolean","comparator":"eq","boundQ32":4294967296_i64,"evidenceSourceId":"observer.task","terminal":true}],
            "legalActionClasses":["read"],"forbiddenActionClasses":[],"confirmationActionClasses":[],
            "constraints":[{"constraintId":"latency.ceiling","unit":"micros","comparator":"lte","boundQ32":5000,"evidenceSourceId":"observer.clock","terminal":false}],
            "softDimensions":[{"dimensionId":"quality","unit":"ratio","direction":"maximize","minimumWeightQ32":0,"maximumWeightQ32":4294967296_i64}],
            "evidenceRequirements":[{"requirementId":"evidence.quality","evidenceSourceId":"observer.evidence","minimumConfidencePpm":900000,"terminal":true}],
            "resources":{"timeMicros":10000,"tokenCount":1000,"computeMicros":50000,"memoryBytes":1048576,"networkBytes":0,"externalEffectCount":0},
            "risk":{"riskClass":"low","abstentionRule":"ask","rollbackClass":"reversible","compensationRequired":false},
            "provenance":{"sourceDigest":Digest32::of_bytes(draft.as_bytes()).to_string(),"normalizationProfileDigest":"2".repeat(64)}
        },
        "sourceTrustClass":"authorized_adapter","locale":"en-US","observedAt":timestamp(now/1000)?,
        "deadline":timestamp(now/1000+120)?,"inputSchemaDigest":"1".repeat(64)
    });
    let decoded =
        codex_hepta_objective::decode_source_envelope_json_v1(&serde_json::to_vec(&source)?)?;
    source["intentDigest"] =
        json!(codex_hepta_objective::canonical_objective_intent_digest_v1(&decoded)?.to_string());
    let body = AuthBusObjectiveBody {
        spawn_generation: 1,
        run_id: run_id.to_string(),
        objective_revision: 1,
        source_envelope_json: serde_json::to_string(&source)?,
        runtime_body_digest: "11".repeat(32),
        preference_state_digest: "22".repeat(32),
        model_tuple_digest: "33".repeat(32),
        prompt_registry_digest: "44".repeat(32),
        artifact_set_digest: "55".repeat(32),
        authority_epoch: 13,
    };
    let mut scope = b"hepta:agentd:signed-objective:v1\0".to_vec();
    scope.extend_from_slice(identity.agent_id.as_str().as_bytes());
    let claims = SignedMessageClaims {
        issuer_id: StableId::new("issuer.production")?,
        key_epoch: Generation::new(1)?,
        message_id: StableId::new("desktop.original.message")?,
        subject_id: StableId::new(identity.agent_id.as_str())?,
        scope_digest: Digest32::of_bytes(&scope),
        payload_digest: Digest32::of_bytes(&serde_json::to_vec(&body)?),
        sequence: 1,
        expires_at_ms: now + 120000,
    };
    let ingress = AuthBusObjectiveIngress {
        issuer_id: claims.issuer_id.to_string(),
        key_epoch: 1,
        message_id: claims.message_id.to_string(),
        sequence: 1,
        expires_at_ms: claims.expires_at_ms,
        signature_hex: hex(&key.sign(&claims.signing_bytes()).to_bytes()),
        body,
    };
    Ok(ObjectiveSenderRequest::from_original(
        serde_json::to_string(&ingress)?,
        ObjectiveSenderOrigin {
            agent_id: identity.agent_id.clone(),
            spawn_generation: 1,
            request_id: 1,
            // SAFETY: geteuid only reads process identity.
            expected_peer_uid: unsafe { libc::geteuid() },
            expected_peer_pid: std::process::id(),
            endpoint_identity: socket.to_str().ok_or("UTF-8 socket required")?.to_string(),
        },
    )?)
}
