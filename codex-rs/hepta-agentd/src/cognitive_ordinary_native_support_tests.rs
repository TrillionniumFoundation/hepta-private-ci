//! Exact native binaries and original owners for the retained ordinary study.
//! Temporary signing keys exercise production gates in one local namespace;
//! they do not establish independent organizational custody.
use super::*;
use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_automation::AuthorizedEffectIntent;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_memory::H7ArtifactSigner;
use codex_hepta_memory::H7QualificationRuntime;
use codex_hepta_memory::H7SignedArtifactTransition;
use codex_hepta_memory::H7TrajectoryEvent;
use codex_hepta_supervisor::H7H89ProductionGrantSigner;
use codex_hepta_supervisor::H7H89ProductionTransition;
use codex_hepta_supervisor::SupervisorEpoch;
use codex_hepta_supervisor::SupervisorError;
use codex_hepta_supervisor::SupervisordAgentStatus;
use codex_hepta_supervisor::SupervisordClient;
use codex_hepta_supervisor::SupervisordMutation;
use codex_hepta_supervisor::SupervisordMutationAccepted;
use codex_model_provider::HttpProviderEffectContractAttestation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::os::unix::fs::PermissionsExt;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

pub(super) struct Binary {
    pub path: PathBuf,
    pub digest: Sha256Digest,
}

impl Binary {
    pub fn pinned(name: &str) -> Result<Self> {
        let path =
            PathBuf::from(std::env::var(name).with_context(|| format!("missing native {name}"))?);
        ensure!(path.is_absolute(), "native binary path must be absolute");
        let digest = Sha256Digest::parse(std::env::var(format!("{name}_SHA256"))?)
            .map_err(anyhow::Error::msg)?;
        let result = Self { path, digest };
        result.verify()?;
        Ok(result)
    }

    pub fn verify(&self) -> Result<()> {
        ensure!(
            Sha256Digest::for_bytes(&std::fs::read(&self.path)?) == self.digest,
            "native binary differs from the externally pinned build"
        );
        Ok(())
    }

    pub fn run(&self, root: &std::path::Path, label: &str, args: &[String]) -> Result<Value> {
        self.verify()?;
        let start = Instant::now();
        let at = support::micros();
        let result = Command::new(&self.path).args(args).output()?;
        std::fs::write(root.join(format!("{label}-stdout.json")), &result.stdout)?;
        std::fs::write(root.join(format!("{label}-stderr.log")), &result.stderr)?;
        save(
            &root.join(format!("{label}-execution.json")),
            &json!({
            "binary":self.path,"binary_sha256":self.digest,"args":args,"exit_code":result.status.code(),
            "started_at_unix_micros":at,"finished_at_unix_micros":support::micros(),
            "monotonic_elapsed_micros":start.elapsed().as_micros(),
            "stdout_sha256":Digest32::of_bytes(&result.stdout).to_string(),
            "stderr_sha256":Digest32::of_bytes(&result.stderr).to_string()}),
        );
        self.verify()?;
        ensure!(
            result.status.success(),
            "native {label} failed: {}",
            String::from_utf8_lossy(&result.stderr)
        );
        Ok(serde_json::from_slice(&result.stdout)?)
    }
}

pub(super) struct Chain {
    pub binary: Binary,
    pub genesis: u64,
    pub store: PathBuf,
    pub fixture: Value,
}

impl Chain {
    pub fn command(
        &self,
        root: &std::path::Path,
        label: &str,
        operation: &str,
        extra: &[String],
    ) -> Result<Value> {
        let mut args = vec![
            operation.to_owned(),
            "--development".to_owned(),
            "--store".to_owned(),
            self.store.display().to_string(),
            "--state-backend".to_owned(),
            "authenticated-v1".to_owned(),
            "--genesis-time".to_owned(),
            self.genesis.to_string(),
            "--evaluation-policy".to_owned(),
            "legacy-first-two-v3".to_owned(),
            "--task-profile".to_owned(),
            "legacy-task-v1".to_owned(),
            "--model-profile".to_owned(),
            "linear-expert-dev-v1".to_owned(),
            "--workers".to_owned(),
            "1".to_owned(),
        ];
        args.extend_from_slice(extra);
        self.binary.run(root, label, &args)
    }

    pub fn confirm_acceptance(&self, root: &std::path::Path) -> Result<String> {
        let packet = root.join("confirmation.packet");
        let made = self.command(
            root,
            "confirmation-make",
            "make",
            &[
                "--parent".to_owned(),
                self.fixture["accept_block"]
                    .as_str()
                    .context("accept block")?
                    .to_owned(),
                "--timestamp".to_owned(),
                (self.genesis + 40).to_string(),
                "--output".to_owned(),
                packet.display().to_string(),
            ],
        )?;
        self.command(
            root,
            "confirmation-submit",
            "submit",
            &["--packet".to_owned(), packet.display().to_string()],
        )?;
        Ok(made["result"]["block"]
            .as_str()
            .context("native confirmation block")?
            .to_owned())
    }
}

pub(super) fn host_file(
    root: &std::path::Path,
    binary: &Binary,
    store: &std::path::Path,
    genesis: u64,
) -> Result<PathBuf> {
    let scope = Sha256Digest::for_bytes(b"ordinary-native-upgrade-final-use");
    // The Chain fixture creates this directory before either Agentd starts.
    let packet_root = root.canonicalize()?.join("chain");
    let contract = json!({"schema":"hepta-agentd-pon-provider-contract-v3",
        "provider_kind":"trillionnium-pon-local-v1","provider_scope":"pon/ordinary-study-v1","destination_id":"pon:ordinary-study",
        "chain_binary":binary.path,"chain_binary_sha256":binary.digest,"chain_store":store,"pon_packet_root":packet_root,"chain_state_backend":"authenticated-v1",
        "chain_genesis_time":genesis,"chain_evaluation_policy":"legacy-first-two-v3","chain_task_profile":"legacy-task-v1",
        "chain_model_profile":"linear-expert-dev-v1","chain_workers":1,"chain_min_confirmation_depth":1,
        "chain_min_confirmation_work_depth_hex":format!("{}01","00".repeat(63)),"timeout_ms":5000});
    let mut bytes = b"hepta.agentd.pon-provider-contract.v3\0".to_vec();
    bytes.extend(serde_json::to_vec(&contract)?);
    let digest = Sha256Digest::for_bytes(&bytes);
    let contract_signer = SigningKey::from_bytes(&[23; 32]);
    let effect_signer = SigningKey::from_bytes(&[29; 32]);
    let signature = contract_signer.sign(&HttpProviderEffectContractAttestation::statement_for(
        "ordinary-native-task-contract",
        &digest,
        1,
    ));
    let revocations = root.join("ordinary-final-use-revocations.json");
    save(
        &revocations,
        &serde_json::to_value(FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: Default::default(),
        })?,
    );
    let mut file = contract;
    file.as_object_mut()
        .context("contract object")?
        .remove("schema");
    for (key,value) in json!({"schema_version":3,"final_use_scope_sha256":scope,
        "contract_id":"ordinary-native-task-contract","contract_sha256":digest,"contract_authority_epoch":1,
        "contract_signature_hex":support::hex(&signature.to_bytes()),"contract_verifying_key_hex":support::hex(&contract_signer.verifying_key().to_bytes()),
        "final_use_signer_id":"automation-security-owner","final_use_verifying_key_hex":support::hex(&effect_signer.verifying_key().to_bytes()),
        "final_use_revocations_file":revocations}).as_object().context("host additions")? {
        file[key]=value.clone();
    }
    let path = root.join("ordinary-effect-host.json");
    save(&path, &file);
    for owned in [&path, &revocations] {
        std::fs::set_permissions(owned, std::fs::Permissions::from_mode(0o600))?;
    }
    Ok(path)
}

pub(super) struct Daemon {
    child: Child,
    pub client: SupervisordClient,
    pub binary: Binary,
    epoch: Option<SupervisorEpoch>,
}

impl Daemon {
    pub async fn start(root: &std::path::Path, host: &Host) -> Result<Self> {
        let binary = Binary::pinned("HEPTA_SUPERVISORD_BINARY")?;
        let h7 = H7ArtifactSigner::from_seed("h7-signer", 1, [7; 32])?;
        let signer = H7H89ProductionGrantSigner::from_seed("operator", 4, [9; 32])?;
        let h7_key = root.join("h7-verifier.key");
        let grant_key = root.join("supervisor-grant-verifier.key");
        std::fs::write(&h7_key, h7.verifying_key().to_bytes())?;
        std::fs::write(&grant_key, signer.verifying_key().to_bytes())?;
        let log = File::create(root.join("supervisord.log"))?;
        let child = Command::new(&binary.path)
            .arg("--fleet-root")
            .arg(&host.fleet_path)
            .arg("--grant-verifier-key")
            .arg(&grant_key)
            .args(["--grant-signer-id", "operator", "--grant-signer-epoch", "4"])
            .arg("--h7-verifier-key")
            .arg(&h7_key)
            .args(["--h7-signer-id", "h7-signer", "--h7-signer-epoch", "1"])
            .stdout(Stdio::from(log.try_clone()?))
            .stderr(Stdio::from(log))
            .spawn()?;
        let client = SupervisordClient::new(host.fleet.layout().supervisor_socket().to_path_buf())?;
        let mut result = Self {
            child,
            client,
            binary,
            epoch: None,
        };
        let deadline = Instant::now() + Duration::from_secs(15);
        loop {
            ensure!(
                result.child.try_wait()?.is_none(),
                "actual Supervisor exited; inspect retained supervisord.log"
            );
            if let Ok(health) = result.client.health().await
                && health.ready
            {
                break;
            }
            ensure!(
                Instant::now() < deadline,
                "actual Supervisor readiness deadline"
            );
            tokio::time::sleep(Duration::from_millis(50)).await;
        }
        let health = result.client.health().await?;
        ensure!(
            health.process_id == result.child.id(),
            "actual Supervisor health belongs to another process"
        );
        result.epoch = Some(health.supervisor_epoch.clone());
        save(
            &root.join("supervisor-process.json"),
            &json!({"binary":result.binary.path,"binary_sha256":result.binary.digest,
            "process_id":result.child.id(),"health":health,"production_authority_build_required":true,
            "operator_scope":"ephemeral single study namespace"}),
        );
        Ok(result)
    }

    pub fn epoch(&self) -> Result<&SupervisorEpoch> {
        self.epoch.as_ref().context("actual owned Supervisor epoch")
    }

    pub async fn cleanup(&self, root: &std::path::Path) -> Result<()> {
        let started = Instant::now();
        let at = support::micros();
        let deadline = tokio::time::Instant::from_std(started + Duration::from_secs(60));
        let mut rounds = Vec::<Value>::new();
        let mut kill_calls = 0_u64;
        let mut accepted: Option<SupervisordAgentStatus> = None;
        let result = tokio::time::timeout_at(deadline, async {
            let epoch = self.epoch()?;
            loop {
                let round = rounds.len();
                rounds.push(json!({"observation_index":round + 1,
                    "phase":if accepted.is_some() {"observe_accepted_kill_only"} else {"snapshot_before_kill"},
                    "monotonic_elapsed_micros":started.elapsed().as_micros()}));
                let status = match self.client.snapshot(owner()).await {
                    Ok(status) => status,
                    Err(error) => {
                        rounds[round]["snapshot_error"] = json!(error.to_string());
                        return Err(error.into());
                    }
                };
                rounds[round]["status"] = serde_json::to_value(&status)?;
                ensure!(
                    status.agent_id == owner()
                        && status.control_fence.agent_id == owner()
                        && &status.control_fence.supervisor_epoch == epoch,
                    "cleanup snapshot belongs to another Agent or Supervisor epoch"
                );
                let revision = status.control_revision.context("actual cleanup control revision")?;
                if let Some(prior) = &accepted {
                    ensure!(
                        status.control_revision == prior.control_revision,
                        "another control mutation followed the accepted cleanup Kill"
                    );
                }
                if !status.active {
                    ensure!(
                        status.lifecycle == AgentLifecycle::Stopped
                            && status.spawn_generation.is_none()
                            && status.runtime_generation.is_none()
                            && status.process_id.is_none()
                            && !status.release_change_pending
                            && !status.matrix.active,
                        "inactive cleanup snapshot is not a completed stop"
                    );
                    return Ok(json!({"state":"stopped","status":status}));
                }
                if let Some(prior) = &accepted {
                    ensure!(
                        status.spawn_generation == prior.spawn_generation
                            && status.current_release == prior.current_release
                            && status.process_id == prior.process_id,
                        "another runtime followed the accepted cleanup Kill"
                    );
                    rounds[round]["action"] = json!("observe_accepted_kill_only");
                } else {
                    ensure!(
                        kill_calls < 3,
                        "original Supervisor rejected all three cleanup Kill CAS attempts; owned Agent remains active"
                    );
                    let expected_revision = revision.checked_add(1).context("cleanup revision overflow")?;
                    rounds[round]["submitted_fence"] = serde_json::to_value(&status.control_fence)?;
                    kill_calls += 1;
                    rounds[round]["kill_attempt"] = json!(kill_calls);
                    match self.client.kill(status.control_fence.clone()).await {
                        Ok(receipt) => {
                            rounds[round]["kill_response"] = mutation_observation(&receipt);
                            ensure!(
                                receipt.operation == SupervisordMutation::Kill
                                    && receipt.accepted_state_digest == status.control_fence.state_digest
                                    && receipt.agent.agent_id == owner()
                                    && &receipt.agent.control_fence.supervisor_epoch == epoch
                                    && receipt.agent.control_revision == Some(expected_revision),
                                "cleanup Kill receipt differs from the original request"
                            );
                            accepted = Some(receipt.agent);
                        }
                        Err(error) => {
                            rounds[round]["kill_error"] = json!(error.to_string());
                            if !is_original_stale_fence(&error) {
                                return Err(error.into());
                            }
                            // The original CAS rejected this request before mutation.
                            // Only this exact rejection permits a fresh fenced attempt.
                            rounds[round]["action"] = json!("refresh_after_original_stale_fence");
                        }
                    }
                }
                tokio::time::sleep(Duration::from_millis(100)).await;
            }
        }).await;
        let result: Result<Value> = match result {
            Ok(result) => result,
            Err(_) => Err(anyhow::anyhow!("owned cleanup exceeded the absolute 60s observation bound")),
        };
        let mut observation = match &result {
            Ok(value) => value.clone(),
            Err(error) => json!({"state":"failed","reason":format!("{error:#}")}),
        };
        observation["snapshot_observations"] = json!(rounds.len());
        observation["rounds"] = json!(rounds);
        observation["kill_cas_attempt_limit"] = json!(3);
        observation["kill_calls"] = json!(kill_calls);
        observation["kill_accepted"] = json!(accepted.is_some());
        observation["started_at_unix_micros"] = json!(at);
        observation["monotonic_elapsed_micros"] = json!(started.elapsed().as_micros());
        save(
            &root.join("native-cleanup.json"),
            &observation,
        );
        result.map(|_| ())
    }
}

impl Drop for Daemon {
    fn drop(&mut self) {
        if self.child.try_wait().ok().flatten().is_none() {
            let _ = self.child.kill();
        }
        let _ = self.child.wait();
    }
}

fn is_original_read_timeout(error: &SupervisorError) -> bool {
    matches!(error, SupervisorError::Invalid(message) if message == "supervisord read timed out")
}

fn is_original_stale_fence(error: &SupervisorError) -> bool {
    matches!(error, SupervisorError::Invalid(message) if message ==
        "supervisord rejected request (stale_control_fence): selected Agent changed; refresh before retry")
}

fn mutation_observation(receipt: &SupervisordMutationAccepted) -> Value {
    json!({"operation":receipt.operation,"accepted_state_digest":receipt.accepted_state_digest,
        "agent":receipt.agent,"production_receipt":receipt.production_receipt})
}

pub(super) async fn start_once_and_running(
    root: &std::path::Path,
    client: &SupervisordClient,
    epoch: &SupervisorEpoch,
    release: &ReleaseId,
    generation: u64,
) -> Result<SupervisordAgentStatus> {
    let started = Instant::now();
    let deadline = tokio::time::Instant::from_std(started + Duration::from_secs(60));
    let path = root.join("source-start-observation.json");
    let mut trace = json!({"schema":"hepta.ordinary-source-start-observation.v1",
        "started_at_unix_micros":support::micros(),"supervisor_epoch":epoch,
        "release":release,"spawn_generation":generation,"start_calls":0,"readbacks":[]});
    let result = tokio::time::timeout_at(deadline, async {
        let before = client.snapshot(owner()).await?;
        trace["before"] = serde_json::to_value(&before)?;
        let revision = before.control_revision.context("actual pre-Start control revision")?;
        let next_revision = revision.checked_add(1).context("source Start revision overflow")?;
        let running_generation = generation.checked_add(1).context("source running generation overflow")?;
        ensure!(
            before.agent_id == owner()
                && before.control_fence.agent_id == owner()
                && &before.control_fence.supervisor_epoch == epoch,
            "pre-Start snapshot belongs to another Agent or Supervisor epoch"
        );
        ensure!(
            before.lifecycle == AgentLifecycle::Stopped
                && before.lifecycle_generation.checked_add(1) == Some(generation)
                && !before.active
                && !before.healthy
                && before.process_id.is_none()
                && before.spawn_generation.is_none()
                && before.runtime_generation.is_none()
                && before.current_release.is_none()
                && before.previous_release.is_none()
                && !before.release_change_pending,
            "source Start requires the original inactive fixture generation"
        );
        trace["request"] = json!({"fence":before.control_fence,"release_id":release});
        trace["start_calls"] = json!(1);
        save(&root.join("source-start-request.json"), &trace);
        let mut revision_observed = false;
        // This is the only Start call. A read timeout is retained as Unknown;
        // neither it nor an unchanged snapshot authorizes another dispatch.
        match client.start(before.control_fence.clone(), release.clone()).await {
            Ok(receipt) => {
                trace["start_result"] = json!({"state":"accepted","response":mutation_observation(&receipt)});
                ensure!(
                    receipt.operation == SupervisordMutation::Start
                        && receipt.accepted_state_digest == before.control_fence.state_digest
                        && receipt.agent.agent_id == owner()
                        && &receipt.agent.control_fence.supervisor_epoch == epoch
                        && receipt.agent.control_revision == Some(next_revision),
                    "source Start receipt differs from the original request"
                );
                revision_observed = true;
            }
            Err(error) => {
                trace["start_result"] = json!({"state":if is_original_read_timeout(&error) {"unknown"} else {"failed"},
                    "error":error.to_string()});
                if !is_original_read_timeout(&error) {
                    return Err(error.into());
                }
            }
        }
        save(&root.join("source-start-response.json"), &trace);
        loop {
            let observed = client.snapshot(owner()).await;
            trace["readbacks"].as_array_mut().context("source readback observations")?.push(
                match &observed {
                    Ok(status) => json!({"monotonic_elapsed_micros":started.elapsed().as_micros(),"status":status}),
                    Err(error) => json!({"monotonic_elapsed_micros":started.elapsed().as_micros(),"error":error.to_string()}),
                }
            );
            let status = match observed {
                Ok(status) => status,
                Err(error) if is_original_read_timeout(&error) => {
                    // Read-only observations may wait for the original owner;
                    // the one absolute readiness deadline is never reset.
                    tokio::time::sleep(Duration::from_millis(100)).await;
                    continue;
                }
                Err(error) => return Err(error.into()),
            };
            ensure!(
                status.agent_id == owner()
                    && status.control_fence.agent_id == owner()
                    && &status.control_fence.supervisor_epoch == epoch,
                "source readback belongs to another Agent or Supervisor epoch"
            );
            let current_revision = status.control_revision.context("actual source readback control revision")?;
            if current_revision == revision {
                ensure!(
                    !revision_observed && status == before,
                    "source state changed without the exact Start revision"
                );
            } else {
                ensure!(
                    current_revision == next_revision,
                    "source readback crossed the one expected Start revision"
                );
                revision_observed = true;
                ensure!(
                    status.active
                        && status.process_id.is_some_and(|pid| pid > 0)
                        && status.current_release.as_ref() == Some(release)
                        && status.previous_release == before.previous_release
                        && status.spawn_generation == Some(generation)
                        && !status.release_change_pending,
                    "consumed Start revision does not identify the intended source runtime"
                );
                match status.lifecycle {
                    AgentLifecycle::Starting => ensure!(
                        status.lifecycle_generation == generation
                            && status.runtime_generation == Some(generation),
                        "source Starting state differs from its original spawn"
                    ),
                    AgentLifecycle::Running => {
                        ensure!(
                            status.lifecycle_generation == running_generation
                                && status.runtime_generation == Some(running_generation),
                            "source Running state differs from its original spawn"
                        );
                        if status.healthy {
                            return Ok(status);
                        }
                    }
                    _ => anyhow::bail!("source Start reached an unexpected lifecycle: {:?}", status.lifecycle),
                }
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
    }).await;
    let result: Result<SupervisordAgentStatus> = match result {
        Ok(result) => result,
        Err(_) => Err(anyhow::anyhow!("source Start/readback exceeded the original absolute 60s ready boundary")),
    };
    trace["result"] = match &result {
        Ok(status) => json!({"state":"ready","status":status}),
        Err(error) => json!({"state":"failed","reason":format!("{error:#}")}),
    };
    trace["monotonic_elapsed_micros"] = json!(started.elapsed().as_micros());
    save(&path, &trace);
    result
}

pub(super) async fn plan(
    client: &SupervisordClient,
    chain: &Chain,
    commitment: crate::CognitiveUpgradeCommitmentV1,
) -> Result<crate::PublishedCognitiveUpgradePlanV1> {
    let status = client.snapshot(owner()).await?;
    let revision = status
        .control_revision
        .context("actual Supervisor control revision is required, never default zero")?;
    let now = support::micros() / 1_000_000;
    let mut runtime = H7QualificationRuntime::new();
    runtime.append_trajectory_event(H7TrajectoryEvent::new(
        "ordinary-native-trajectory",
        1,
        "reload",
        100,
        true,
        1,
        1,
        1,
        Sha256Digest::for_bytes(b"ordinary-native-fence"),
    )?)?;
    runtime.evaluate_trajectory("ordinary-native-trajectory")?;
    let artifact = runtime.propose_artifact(
        "ordinary-native-h7-artifact",
        "ordinary-native-trajectory",
        1,
    )?;
    let h7_envelope = H7ArtifactSigner::from_seed("h7-signer", 1, [7; 32])?.sign(
        &artifact,
        None,
        H7SignedArtifactTransition::Reload,
        0,
        None,
        now,
        now + 600,
    )?;
    let production_grant = H7H89ProductionGrantSigner::from_seed("operator", 4, [9; 32])?.sign(
        &owner(),
        commitment.source.source_release.as_str(),
        commitment.source.target_release.as_str(),
        H7H89ProductionTransition::Upgrade,
        &h7_envelope,
        revision,
        status.lifecycle_generation,
        codex_hepta_supervisor::authority_epoch_for_supervisor_epoch(
            client.health().await?.supervisor_epoch.as_str(),
        ),
        now,
        now + 600,
    )?;
    let packet_path = PathBuf::from(
        chain.fixture["accept_packet"]
            .as_str()
            .context("exact accept packet")?,
    );
    let packet = std::fs::read(&packet_path)?;
    let intent = AuthorizedEffectIntent {
        run_id: "ordinary-native-upgrade".to_owned(),
        step_id: "effect".to_owned(),
        attempt: 1,
        operation_id: "provider.deliver".to_owned(),
        subject_id: owner().to_string(),
        destination_id: "pon:ordinary-study".to_owned(),
        payload_digest: Sha256Digest::for_bytes(&packet),
        final_use_scope_digest: Sha256Digest::for_bytes(b"ordinary-native-upgrade-final-use"),
        policy_generation: 1,
        expected_predecessor_digest: None,
        dependencies: Vec::new(),
        compensation_for: None,
    };
    let now_ms = support::micros() / 1_000;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "automation-security-owner".to_owned(),
        authority_epoch: 9,
        grant_id: "ordinary-native-upgrade-grant".to_owned(),
        nonce: [31; 32],
        binding: intent.final_use_binding()?,
        not_before_unix_ms: now_ms.saturating_sub(1_000),
        expires_at_unix_ms: now_ms + 30_000,
    };
    let final_use_grant = SignedFinalUseGrant {
        signature: SigningKey::from_bytes(&[29; 32])
            .sign(&grant.signing_bytes()?)
            .to_bytes()
            .to_vec(),
        grant,
    };
    let provider_effect_key =
        ProviderEffectKey::for_operation("pon/ordinary-study-v1", &intent.run_id, &intent.step_id)
            .map_err(|error| anyhow::anyhow!("provider key: {error:?}"))?;
    Ok(crate::PublishedCognitiveUpgradePlanV1 {
        commitment,
        production_grant,
        h7_envelope,
        task: serde_json::from_value(
            json!({"task_id":chain.fixture["task_id"],"owner":chain.fixture["owner"],"provider":chain.fixture["provider"]}),
        )?,
        effect: crate::CognitiveUpgradeEffectV1 {
            intent,
            provider_effect_key,
            packet_path,
            packet_byte_length: Some(packet.len() as u64),
            final_use_grant,
            command_id: "ordinary-native-accept".to_owned(),
        },
    })
}
