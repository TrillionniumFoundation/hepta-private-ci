//! Local PQ test trust and a pinned subprocess peer, never production custody.

use super::support::Service;
use super::support::frontier_service;
use super::support::key;
use super::support::write_private;
use super::*;
use codex_hepta_automation::TaskFlowCommand;
use codex_hepta_automation::TaskFlowDefinition;
use codex_hepta_automation::TaskFlowEdgeSpec;
use codex_hepta_automation::TaskFlowNodeKind;
use codex_hepta_automation::TaskFlowNodeSpec;
use codex_hepta_automation::TaskFlowTransition;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocationUpdate;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use codex_hepta_contracts::authority_trust_unix::PqTrustOperationV2;
use codex_hepta_contracts::authority_trust_unix::PqTrustOutcomeV2;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;

pub(super) struct PqFixture {
    pub(super) agent: AgentFixture,
    clock: Service,
    frontier: Service,
    pub(super) now: Arc<AtomicU64>,
    issuer: PqNativeSigningKey,
    feed_signer: PqNativeSigningKey,
    deployment_signer: PqNativeSigningKey,
    pub(super) head: FinalUseRevocations,
    pub(super) config: Value,
    pub(super) config_path: PathBuf,
    pub(super) feed_path: PathBuf,
    pub(super) script: PathBuf,
    pub(super) marker: PathBuf,
    // Test service sockets and durable CAS records outlive their joined threads.
    pub(super) root: tempfile::TempDir,
}

impl PqFixture {
    pub(super) async fn new() -> anyhow::Result<Self> {
        let agent = AgentFixture::new().await;
        let root = tempfile::tempdir()?;
        let private = root.path().canonicalize()?;
        let now = Arc::new(AtomicU64::new(NOW));
        let time = Arc::clone(&now);
        let clock = Service::start(&private, "clock.sock", /*seed*/ 84, move |operation| {
            Ok(match operation {
                PqTrustOperationV2::ClockNow => PqTrustOutcomeV2::Clock {
                    unix_ms: time.load(Ordering::SeqCst),
                },
                PqTrustOperationV2::FrontierLoad { .. }
                | PqTrustOperationV2::FrontierCompareAndSet { .. } => PqTrustOutcomeV2::Unavailable,
            })
        })?;
        let head = FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: Default::default(),
        };
        let frontier = frontier_service(
            &private,
            FinalUseFrontier::for_initial_head_with_profile(
                &head,
                FinalUseAuthenticationProfile::MlDsa65V2,
            )?,
        )?;
        let (issuer, issuer_pin) = key(/*seed*/ 81)?;
        let (feed_signer, feed_pin) = key(/*seed*/ 82)?;
        let (deployment_signer, deployment_pin) = key(/*seed*/ 83)?;
        let repo = private.join("source");
        let script = repo.join("qualification/hcsn_training/supervisor.py");
        fs::create_dir_all(script.parent().expect("script parent"))?;
        fs::create_dir_all(repo.join("qualification/hcsn"))?;
        let durable = private.join("supervisor-store");
        fs::create_dir(&durable)?;
        fs::set_permissions(&durable, fs::Permissions::from_mode(0o700))?;
        let marker = durable.join("provider-contact.jsonl");
        // This intentionally small peer exercises real native process transport.
        // It is not the HCSN training supervisor or a numerical worker.
        write_private(&script, br#"import hashlib,json,pathlib,sys
command=json.load(sys.stdin)
root=pathlib.Path(sys.argv[-1])
with (root/'provider-contact.jsonl').open('a') as stream:
    stream.write(json.dumps(command,sort_keys=True)+'\n')
print(json.dumps(dict(schema_version=1,dispatch=command['dispatch'],target=command['target'],
    state='failed',process=None,evidence=dict(receipt_sha256=hashlib.sha256(b'fixture-failure').hexdigest(),
    candidate_sha256=None,handoff_sha256=None))))
"#)?;
        let python = Path::new("/usr/bin/python3").canonicalize()?;
        let config_path = private.join("host.json");
        let feed_path = private.join("signed-feed.json");
        let config = serde_json::json!({
            "schema_version": 3, "provider": "hcsn_process_v1", "authority_profile": "production_ml_dsa65_v2",
            "deployment": { "schema_version": 1, "contract_id": "hcsn-local-pq-fixture", "authority_epoch": 9,
                "provider_scope": SCOPE, "final_use_scope_sha256": Sha256Digest::for_bytes(b"hcsn-pq-test-scope"),
                "python_executable": python, "python_sha256": Sha256Digest::for_bytes(&fs::read(&python)?),
                "repository_root": repo, "supervisor_sha256": Sha256Digest::for_bytes(&fs::read(&script)?),
                "source_manifest": { "qualification/hcsn_training/supervisor.py": Sha256Digest::for_bytes(&fs::read(&script)?) },
                "durable_root": durable, "timeout_ms": 2_000 },
            "deployment_key": deployment_pin, "deployment_signature": [],
            "final_use": { "signer_id": "hcsn-test-issuer", "issuer_keys": [issuer_pin], "head": head,
                "revocation_distributor_id": "hcsn-test-feed", "revocation_keys": [feed_pin],
                "signed_revocations_file": feed_path, "external_clock": clock.config_json(),
                "external_frontier": frontier.config_json() },
        });
        let mut fixture = Self {
            agent,
            clock,
            frontier,
            now,
            issuer,
            feed_signer,
            deployment_signer,
            head,
            config,
            config_path,
            feed_path,
            script,
            marker,
            root,
        };
        fixture.sign_deployment()?;
        fixture.publish_feed(fixture.head.clone(), NOW + 60_000)?;
        Ok(fixture)
    }

    pub(super) fn sign_deployment(&mut self) -> anyhow::Result<()> {
        let deployment: HcsnDeploymentV1 =
            serde_json::from_value(self.config["deployment"].clone())?;
        let mut message = b"hepta.hcsn.deployment-contract.pq.v1\0".to_vec();
        message.extend(serde_json::to_vec(&deployment)?);
        self.config["deployment_signature"] = serde_json::json!(
            self.deployment_signer
                .sign_exact_message(&message)?
                .to_vec()
        );
        self.write_config()
    }

    pub(super) fn write_config(&self) -> anyhow::Result<()> {
        write_private(&self.config_path, &serde_json::to_vec(&self.config)?)
    }

    pub(super) fn publish_feed(
        &self,
        head: FinalUseRevocations,
        expires: u64,
    ) -> anyhow::Result<()> {
        write_private(&self.feed_path, &self.feed_bytes(head, expires)?)
    }

    pub(super) fn feed_bytes(
        &self,
        head: FinalUseRevocations,
        expires: u64,
    ) -> anyhow::Result<Vec<u8>> {
        let update = FinalUseRevocationUpdate::new_pq(
            "hcsn-test-feed".to_string(),
            head,
            NOW - 1_000,
            expires,
        );
        let signature = self
            .feed_signer
            .sign_exact_message(&update.signing_bytes()?)?
            .to_vec();
        Ok(serde_json::to_vec(&SignedFinalUseRevocationUpdate {
            update,
            signature,
        })?)
    }

    pub(super) fn grant(
        &self,
        intent: &AuthorizedEffectIntent,
    ) -> anyhow::Result<SignedFinalUseGrant> {
        let grant = FinalUseGrant {
            schema_version: 2,
            signer_id: "hcsn-test-issuer".to_string(),
            authority_epoch: 9,
            grant_id: "hcsn-test-grant".to_string(),
            nonce: [91; 32],
            binding: intent.final_use_binding()?,
            not_before_unix_ms: NOW - 1_000,
            expires_at_unix_ms: NOW + 30_000,
        };
        let signature = self
            .issuer
            .sign_exact_message(&grant.signing_bytes()?)?
            .to_vec();
        Ok(SignedFinalUseGrant { grant, signature })
    }

    pub(super) fn trust_requests(&self) -> usize {
        self.clock.requests.load(Ordering::SeqCst) + self.frontier.requests.load(Ordering::SeqCst)
    }

    pub(super) async fn prepare(&self) -> anyhow::Result<(AuthorizedEffectIntent, TaskFlowFence)> {
        let owner = TaskFlowFence::new(
            self.agent.identity.agent_id.clone(),
            "hcsn-test-owner",
            1,
            1,
            "hcsn-test-fence",
        )?;
        let definition = TaskFlowDefinition::new(
            "hcsn-pq-test",
            1,
            "effect",
            vec![
                TaskFlowNodeSpec::effect("effect", "hcsn.training.start", "hcsn-pinned-test-peer"),
                TaskFlowNodeSpec::new("success", TaskFlowNodeKind::TerminalSuccess),
                TaskFlowNodeSpec::new("failure", TaskFlowNodeKind::TerminalFailure),
            ],
            vec![
                TaskFlowEdgeSpec::new("effect", "success"),
                TaskFlowEdgeSpec::new("effect", "failure"),
            ],
            vec!["hcsn.training.start".to_string()],
            Sha256Digest::for_bytes(b"hcsn-pq-test-policy"),
        )?;
        let intent = AuthorizedEffectIntent {
            run_id: "hcsn-pq-test-run".to_string(),
            step_id: "effect".to_string(),
            attempt: 1,
            operation_id: "hcsn.training.start".to_string(),
            subject_id: self.agent.identity.agent_id.to_string(),
            destination_id: SCOPE.to_string(),
            payload_digest: Sha256Digest::for_bytes(WIRE),
            final_use_scope_digest: Sha256Digest::for_bytes(b"hcsn-pq-test-scope"),
            policy_generation: 1,
            expected_predecessor_digest: None,
            dependencies: Vec::new(),
            compensation_for: None,
        };
        let store = &self.agent.store;
        store
            .register_taskflow_definition(&definition, &owner, NOW)
            .await?;
        store
            .create_taskflow_run(
                &intent.run_id,
                &definition.workflow_id,
                definition.version,
                definition.definition_digest(),
                "hcsn-test-thread",
                NOW,
            )
            .await?;
        let claimed = store
            .claim_taskflow_run(&intent.run_id, &owner, NOW, 120_000)
            .await?;
        store
            .apply_taskflow_command(&TaskFlowCommand::new(
                &intent.run_id,
                "start",
                owner.clone(),
                claimed.revision,
                TaskFlowTransition::Start,
                NOW,
            )?)
            .await?;
        let digest = intent.digest()?;
        store
            .prepare_taskflow_step(
                &intent.run_id,
                &intent.step_id,
                intent.attempt,
                &owner,
                &digest,
                &intent.payload_digest,
                "prepare",
                NOW,
            )
            .await?;
        store
            .claim_taskflow_step(
                &intent.run_id,
                &intent.step_id,
                intent.attempt,
                &owner,
                &digest,
                &intent.payload_digest,
                "claim",
                NOW,
            )
            .await?;
        Ok((intent, owner))
    }
}
