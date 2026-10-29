//! Real named-owner publication, independent selector and original Unix issuer.
//! Controlled test keys establish no product enrollment or efficacy.
use super::*;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_learning_artifacts::*;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use serde::Deserialize;
use std::collections::BTreeMap;
use std::error::Error;
use std::fs;
use std::os::unix::fs::PermissionsExt;

type TestResult<T> = Result<T, Box<dyn Error>>;
fn issuer_error(error: Box<dyn Error + Send + Sync>) -> Box<dyn Error> {
    error
}
fn id(s: &str) -> StableId {
    StableId::new(s).unwrap()
}
fn digest(s: &str) -> Digest32 {
    Digest32::of_bytes(s.as_bytes())
}

struct Fixture {
    root: PathBuf,
    service: LearningArtifactOwnerService,
    trust: ArtifactOwnerTrustV1,
    head: SignedCurrentArtifactHeadV1,
    owner_key: SigningKey,
    selector_key: SigningKey,
    now: u64,
}

impl Fixture {
    fn new(root: PathBuf, bytes: &[u8]) -> TestResult<Self> {
        Self::with_profile(
            root,
            bytes,
            "561414aec8b51f2a18ae3948dd44a321f924b1e12961a8e0139774b42387fcf0".parse()?,
        )
    }

    fn with_profile(
        root: PathBuf,
        bytes: &[u8],
        compatibility_digest: Digest32,
    ) -> TestResult<Self> {
        Self::with_study_objective(
            root,
            bytes,
            compatibility_digest,
            digest("initial-material-without-efficacy"),
        )
    }

    fn with_study_objective(
        root: PathBuf,
        bytes: &[u8],
        compatibility_digest: Digest32,
        objective: Digest32,
    ) -> TestResult<Self> {
        fs::create_dir(&root)?;
        let now = initial_now_seconds()?;
        let owner_key = SigningKey::from_bytes(&[71; 32]);
        let selector_key = SigningKey::from_bytes(&[72; 32]);
        let scope = DatasetWithdrawalScopeV1 {
            authority_domain_id: id("initial-test-authority"),
            registry_id: id("initial-test-registry"),
            scope_id: id("initial-test-scope"),
        };
        let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope);
        let scope_digest = withdrawals.scope_digest().unwrap();
        let signer = TrustedArtifactSignerV1 {
            signer_id: id("original-owner"),
            verifying_key: owner_key.verifying_key().to_bytes(),
            minimum_authority_epoch: 1,
            maximum_authority_epoch: 9,
            valid_from: now - 1,
            expires_at: now + 3600,
            revoked_at: None,
        };
        let trust = ArtifactOwnerTrustV1 {
            registry_id: id("initial-test-registry"),
            withdrawal_scope_digest: scope_digest,
            minimum_registry_generation: Generation::new(/*value*/ 1)?,
            genesis_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            writer_signers: vec![signer.clone()],
            head_signers: vec![signer],
        };
        let mut lease = SignedArtifactWriterLeaseV1 {
            lease_id: id("initial-writer-lease"),
            producer_id: id("initial-material-producer"),
            registry_id: trust.registry_id.clone(),
            withdrawal_scope_digest: scope_digest,
            signer_id: id("original-owner"),
            signing_key_digest: Digest32::of_bytes(&owner_key.verifying_key().to_bytes()),
            authority_epoch: 1,
            lease_generation: 1,
            issued_at: now,
            expires_at: now + 3600,
            signature: [0; 64],
        };
        lease.signature = owner_key.sign(&lease.signing_bytes()).to_bytes();
        let mut service =
            LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
                root: root.join("artifacts"),
                trust: trust.clone(),
                writer_lease: lease,
                required_current_head: None,
                withdrawal_registry: withdrawals.clone(),
                storage_binding: digest("initial-storage"),
                now,
            })?;
        let source = LearningArtifactManifestV2 {
            artifact_id: id("selected-initial-zero"),
            kind: ArtifactKind::Parameters,
            generation: Generation::new(/*value*/ 1)?,
            provenance_mode: ProvenanceModeV1::DatasetIndependent,
            source_dataset_digests: Vec::new(),
            lineage_digests: vec![digest("fixed-upstream-material")],
            predecessor_ids: Vec::new(),
            rollback_predecessor: None,
            bytes_digest: Digest32::of_bytes(bytes),
            encoded_size_bytes: bytes.len() as u64,
            training_code_digest: digest("initial-material-construction-not-training"),
            runtime_tuple_digest: digest("original-f32-runtime"),
            device_profile_digest: digest("cpu"),
            objective_class_digest: objective,
            compatibility_digest,
            schema_profile_digest: digest("canonical-positive-zero-v1"),
            normalization_digest: digest("positive-zero"),
            producer_id: id("initial-material-producer"),
            created_at: now,
            expires_at: now + 3600,
        };
        let admission = admit_manifest_at_withdrawal_head_v3(
            &withdrawals,
            withdrawals.head_digest(),
            source.clone(),
            now,
        )?;
        let before = service.registry().snapshot().head_digest;
        let tx = ArtifactPublicationTransactionV1::begin(
            id("publish-initial-zero"),
            admission.clone(),
            &withdrawals,
            service.registry(),
            before,
            now,
        )?;
        let mut projected = service.registry().clone();
        projected.append(ArtifactEvent::Register {
            event_id: id(&format!(
                "artifact-publication:{}",
                tx.intent().intent_digest
            )),
            manifest: ArtifactManifest {
                artifact_id: source.artifact_id,
                kind: source.kind,
                generation: source.generation,
                predecessor_id: None,
                content_digest: source.bytes_digest,
                objective_digest: source.objective_class_digest,
                support_digest: admission.validated_manifest.manifest_digest,
                producer_id: source.producer_id,
                compatibility_digest: source.compatibility_digest,
                encoded_size_bytes: source.encoded_size_bytes,
            },
        })?;
        let head = Self::sign_head(&trust, &owner_key, &projected, before, now)?;
        let publication = LearningArtifactPublishRequestV1 {
            operation_id: id("publish-initial-zero"),
            admission,
            payload: bytes.to_vec(),
            signed_current_head: head.clone(),
            expected_registry_predecessor_head: before,
            now,
        };
        let receipt = service.publish(publication.clone())?;
        assert_eq!(service.publish(publication)?, receipt);
        Ok(Self {
            root,
            service,
            trust,
            head,
            owner_key,
            selector_key,
            now,
        })
    }

    fn sign_head(
        trust: &ArtifactOwnerTrustV1,
        key: &SigningKey,
        registry: &ArtifactRegistry,
        before: Digest32,
        now: u64,
    ) -> TestResult<SignedCurrentArtifactHeadV1> {
        let snapshot = registry.snapshot();
        let mut head = SignedCurrentArtifactHeadV1 {
            withdrawal_scope_digest: trust.withdrawal_scope_digest,
            binding: digest("initial-storage"),
            witness: RegistryHeadWitnessV1 {
                registry_id: trust.registry_id.clone(),
                generation: Generation::new(snapshot.records().len() as u64)?,
                head_digest: snapshot.head_digest,
                predecessor_head_digest: before,
                authority_epoch: 1,
                signer_id: id("original-owner"),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                issued_at: now,
                expires_at: now + 3600,
            },
            signature: [0; 64],
        };
        head.signature = key.sign(&head.signing_bytes()).to_bytes();
        Ok(head)
    }

    fn selected(
        &self,
        revoked_at: Option<u64>,
    ) -> TestResult<(
        SelectedInitialSmolLmMaterialV1,
        ArtifactOwnerCurrentReaderV1,
    )> {
        self.select(
            revoked_at,
            VerifiedArtifactSelectionV1::load_initial_smollm_material,
        )
    }

    fn select<T>(
        &self,
        revoked_at: Option<u64>,
        load: impl FnOnce(
            VerifiedArtifactSelectionV1,
            File,
            File,
            VerifiedCurrentRegistryViewV1,
            u64,
        ) -> Result<T, ArtifactSelectionError>,
    ) -> TestResult<(T, ArtifactOwnerCurrentReaderV1)> {
        self.select_at(revoked_at, self.now, self.now + 300, load)
    }

    fn public_material(
        &self,
    ) -> TestResult<(
        SelectedPublicInitialSmolLmMaterialV2,
        ArtifactOwnerCurrentReaderV1,
    )> {
        // A fresh operation obtains a newly signed bounded selection. Existing
        // capsules retain their immutable original window and are never reset.
        self.select_at(
            /*revoked_at*/ None,
            initial_now_seconds()?,
            self.now + 3600,
            VerifiedArtifactSelectionV1::load_public_initial_smollm_material_v2,
        )
    }

    fn select_at<T>(
        &self,
        revoked_at: Option<u64>,
        issued_at: u64,
        selector_expires_at: u64,
        load: impl FnOnce(
            VerifiedArtifactSelectionV1,
            File,
            File,
            VerifiedCurrentRegistryViewV1,
            u64,
        ) -> Result<T, ArtifactSelectionError>,
    ) -> TestResult<(T, ArtifactOwnerCurrentReaderV1)> {
        let reader = ArtifactOwnerCurrentReaderV1::open(
            self.root.join("artifacts"),
            self.trust.clone(),
            self.head.clone(),
        )?;
        let current = reader.current_registry_view(initial_now_seconds()?)?;
        let m = self
            .service
            .registry()
            .manifest(&id("selected-initial-zero"))
            .unwrap();
        let mut signed = SignedArtifactSelectionV1 {
            selection_id: id(&format!("independent-initial-selection-{issued_at}")),
            artifact_id: m.artifact_id.clone(),
            registry_id: self.trust.registry_id.clone(),
            withdrawal_scope_digest: self.trust.withdrawal_scope_digest,
            registry_head_digest: current.receipt().head_digest,
            current_witness_digest: current.witness_digest(),
            current_trust_digest: current.trust_digest(),
            artifact_kind: m.kind,
            artifact_generation: m.generation,
            predecessor_id: m.predecessor_id.clone(),
            content_digest: m.content_digest,
            objective_digest: m.objective_digest,
            support_digest: m.support_digest,
            compatibility_digest: m.compatibility_digest,
            encoded_size_bytes: m.encoded_size_bytes,
            selector_id: id("independent-selector"),
            selector_credential_digest: digest("initial-selector-credential"),
            signing_key_digest: Digest32::of_bytes(&self.selector_key.verifying_key().to_bytes()),
            authority_epoch: 1,
            issued_at,
            expires_at: issued_at + 180,
            signature: [0; 64],
        };
        signed.signature = self.selector_key.sign(&signed.signing_bytes()).to_bytes();
        let verifier = ArtifactSelectionVerifierV1::new(
            ArtifactSelectionTrustV1 {
                registry_id: self.trust.registry_id.clone(),
                withdrawal_scope_digest: self.trust.withdrawal_scope_digest,
                minimum_authority_epoch: 1,
                selectors: vec![TrustedArtifactSelectorV1 {
                    selector_id: id("independent-selector"),
                    verifying_key: self.selector_key.verifying_key().to_bytes(),
                    minimum_authority_epoch: 1,
                    maximum_authority_epoch: 9,
                    valid_from: self.now,
                    expires_at: selector_expires_at,
                    revoked_at,
                }],
            },
            &self.trust,
        )?;
        let selected = verifier.verify(&signed, &current, initial_now_seconds()?)?;
        let r = current.receipt();
        let snapshot = self
            .root
            .join("artifacts/registries")
            .join(format!("{}-{}.snapshot", r.head_digest, r.file_digest));
        let payload = self
            .root
            .join("artifacts/payloads")
            .join(format!("{}-{}.bin", m.artifact_id, m.content_digest));
        let material = load(
            selected,
            File::open(snapshot)?,
            File::open(payload)?,
            reader.current_registry_view(initial_now_seconds()?)?,
            initial_now_seconds()?,
        )?;
        Ok((material, reader))
    }

    fn config(&self, name: &str) -> TestResult<AgentdConfig> {
        let root = self.root.join(name);
        fs::create_dir(&root)?;
        let fleet = HeptaFleetRoot::parse(root.join("fleet"))?;
        let registry = FleetRegistry::initialize(fleet.clone())?;
        let workspace = root.join("workspace");
        fs::create_dir(&workspace)?;
        let owner = codex_hepta_contracts::AgentId::parse("00000000-0000-4000-8000-000000000219")?;
        let record = registry.register(AgentManifest::new(
            owner.clone(),
            WorkspaceBinding::new(&workspace, &fleet)?,
            ResourceBudget::local_default(),
        )?)?;
        registry.compare_and_transition(
            &owner,
            /*expected_generation*/ 0,
            AgentLifecycle::Starting,
        )?;
        fs::create_dir_all(record.layout.home_root())?;
        fs::create_dir_all(record.layout.run_root())?;
        Ok(AgentdConfig::load(
            root.join("fleet"),
            owner,
            /*spawn_generation*/ 1,
            record.layout.home_root().to_path_buf(),
            record.layout.run_root().to_path_buf(),
            record.layout.home_root().to_path_buf(),
            workspace,
        )?)
    }

    fn withdraw(&mut self) -> TestResult<()> {
        let before = self.service.registry().snapshot().head_digest;
        let change = StateChange {
            event_id: id("withdraw-initial-zero"),
            artifact_id: id("selected-initial-zero"),
            evaluator_id: id("original-owner"),
            reason_digest: digest("withdrawn initial material"),
        };
        let mut projected = self.service.registry().clone();
        projected.append(ArtifactEvent::Revoke(change.clone()))?;
        let head = Self::sign_head(
            &self.trust,
            &self.owner_key,
            &projected,
            before,
            initial_now_seconds()?,
        )?;
        self.service.revoke(LearningArtifactRevokeRequestV1 {
            operation_id: id("withdraw-initial-zero"),
            change,
            signed_current_head: head,
            expected_registry_predecessor_head: before,
            now: initial_now_seconds()?,
        })?;
        Ok(())
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct NativeInput {
    schema: String,
    python: PathBuf,
    chain: PathBuf,
    materials: PathBuf,
    parent: PathBuf,
    parent_sha256: String,
    output: PathBuf,
}

fn input_and_worker(name: &str) -> TestResult<(NativeInput, SmolLmNeuralReadConfigV1, Vec<u8>)> {
    let path = std::env::var_os("HEPTA_PN3_NEURAL_NATIVE_CONFIG")
        .ok_or("explicit real-model config required")?;
    let input: NativeInput = serde_json::from_slice(&fs::read(path)?)?;
    assert_eq!(input.schema, "hepta-smollm-neural-native-check-v1");
    let raw = fs::read(&input.parent)?;
    assert_eq!(Digest32::of_bytes(&raw).to_string(), input.parent_sha256);
    let parent: serde_json::Value = serde_json::from_slice(&raw)?;
    assert_eq!(parent["generation"], 1);
    let directory = PathBuf::from(parent["directory"].as_str().ok_or("parent directory")?);
    let parameters = fs::read(directory.join("artifact.safetensors"))?;
    let target_contract = fs::read(directory.join("target-contract.json"))?;
    let c: serde_json::Value = serde_json::from_slice(&target_contract)?;
    let mut source_pins = BTreeMap::new();
    for relative in [
        "formal/pon-nakamoto-v1/llm_adapter_contract.py",
        "scripts/llm_inherited_runtime.py",
        "scripts/llm_neural_read_worker.py",
        "scripts/llm_parent_material.py",
        "scripts/llm_runtime_pilot.py",
        "config/pon/model-family-smollm2-135m-v1.json",
    ] {
        let path = input.chain.join(relative);
        source_pins.insert(path.clone(), Digest32::of_bytes(&fs::read(path)?));
    }
    fs::create_dir_all(&input.output)?;
    let run = input.output.join(name);
    fs::create_dir(&run)?;
    let worker = SmolLmNeuralReadConfigV1 {
        python: input.python.clone(),
        script: input.chain.join("scripts/llm_neural_read_worker.py"),
        materials: input.materials.clone(),
        run_directory: run.join("session"),
        source_pins,
        target_contract,
        wrapped_adapter: fs::read(directory.join("wrapped-adapter.json"))?,
        contract_digest: parent["contract"].as_str().unwrap().parse()?,
        adapter_digest: parent["adapter"].as_str().unwrap().parse()?,
        backbone_digest: c["backbone"]["index_root"].as_str().unwrap().parse()?,
        tokenizer_digest: c["tokenizer"]["files_root"].as_str().unwrap().parse()?,
        action_completions: BTreeMap::from([
            (id("native-answer-no"), "no".to_owned()),
            (id("native-answer-yes"), "yes".to_owned()),
        ]),
    };
    Ok((input, worker, parameters))
}

async fn inputs(
    worker: SmolLmNeuralReadConfigV1,
    root: &Path,
    expected_claims: u8,
) -> TestResult<(
    SmolLmInitialHostInputsV1,
    tokio::task::JoinHandle<Result<(), Box<dyn Error + Send + Sync>>>,
    tempfile::TempDir,
)> {
    fs::create_dir(root)?;
    fs::set_permissions(root, fs::Permissions::from_mode(0o700))?;
    let authority = tempfile::tempdir()?;
    let (authorizer, issuer) = crate::final_use_authorizer::tests::independent_test_authorizer(
        authority.path(),
        expected_claims,
    )
    .await
    .map_err(issuer_error)?;
    drop(authorizer);
    let key = SigningKey::from_bytes(&[79; 32]);
    let path = root.join("authority.json");
    fs::write(
        &path,
        serde_json::to_vec(&serde_json::json!({
            "issuer_socket": authority.path().join("cognitive-authority.sock"),
            "issuer_uid": rustix::process::geteuid().as_raw(),
            "signer_id": "authority-owner",
            "verifying_key": key.verifying_key().to_bytes(),
            "authority_state_dir": authority.path().join("authority-state"),
            "authority_epoch": 9,
            "revocation_revision": 1,
            "revoked_grant_ids": [],
            "issuer_timeout_ms": 2000,
        }))?,
    )?;
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600))?;
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)?
        .as_millis() as u64;
    Ok((
        SmolLmInitialHostInputsV1 {
            worker,
            worker_id: "selected-initial-native-worker".to_owned(),
            resource_grant: ResourceGrant {
                grant_id: "selected-initial-resource".to_owned(),
                authority_epoch: 9,
                generation: 1,
                expires_at_ms: now + 900000,
                revoked: false,
                maximum_models: 1,
                maximum_active_requests: 1,
                maximum_memory_bytes: 8 * 1024 * 1024 * 1024,
                semantic_digest: digest("controlled-initial-resource").to_string(),
            },
            inference_journal: root.join("inference.control"),
            inference_journal_capacity: 8,
            final_use_authorizer_config: path,
        },
        issuer,
        authority,
    ))
}

fn archive_authority(authority: &tempfile::TempDir, output: &Path) -> TestResult<()> {
    let target = output.join(authority.path().file_name().unwrap());
    fs::create_dir(&target)?;
    for item in fs::read_dir(authority.path().join("authority-state"))? {
        let item = item?;
        if item.file_type()?.is_file() {
            fs::copy(item.path(), target.join(item.file_name()))?;
        }
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires the original pinned model configuration with canonical selected gen1 zero material"]
async fn real_selected_initial_current_window_callback_and_load_binding_fail_closed()
-> TestResult<()> {
    for name in [
        "rollback",
        "expiry",
        "revocation",
        "callback",
        "panic",
        "association",
        "withdrawal",
    ] {
        let (input, worker, bytes) = input_and_worker(&format!("selected-control-{name}"))?;
        let mut fixture = Fixture::new(input.output.join(format!("control-owner-{name}")), &bytes)?;
        let revoked_at = if name == "revocation" {
            Some(fixture.now + 60)
        } else {
            None
        };
        let (material, current) = fixture.selected(revoked_at)?;
        let (inputs, issuer, authority) = inputs(
            worker,
            &input.output.join(format!("control-effects-{name}")),
            /*expected_claims*/ 1,
        )
        .await?;
        let mut owner =
            prepare_selected_initial_smollm_v1(fixture.config("body")?, material, current, inputs)
                .await?;
        let rejected = match name {
            "rollback" => {
                owner.observe(|| Ok(fixture.now + 20), |_| Ok(()))?;
                owner
                    .observe::<()>(
                        || Ok(fixture.now + 19),
                        |_| panic!("rollback consumer reached"),
                    )
                    .is_err()
            }
            "expiry" => owner
                .observe::<()>(
                    || Ok(fixture.now + 181),
                    |_| panic!("expired selection consumer reached"),
                )
                .is_err(),
            "revocation" => owner
                .observe::<()>(
                    || Ok(fixture.now + 60),
                    |_| panic!("revoked selector consumer reached"),
                )
                .is_err(),
            "callback" => owner
                .with_current_initial_load::<()>(
                    |_| Err("controlled consumer rejection".to_owned()),
                )
                .is_err(),
            "panic" => std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                owner.with_current_initial_load::<()>(|_| panic!("controlled consumer panic"))
            }))
            .is_err(),
            "association" => {
                owner.association.as_mut().unwrap().0 = digest("different original Ready");
                owner
                    .with_current_initial_load::<()>(|_| panic!("mixed load consumer reached"))
                    .is_err()
            }
            "withdrawal" => {
                fixture.withdraw()?;
                owner
                    .with_current_initial_load::<()>(|_| {
                        panic!("withdrawn material consumer reached")
                    })
                    .is_err()
            }
            _ => unreachable!(),
        };
        assert!(rejected, "{name}");
        assert!(
            owner
                .with_current_initial_load::<()>(|_| panic!("closed initial owner revived"))
                .is_err(),
            "{name}"
        );
        owner.shutdown().await?;
        issuer.await?.map_err(issuer_error)?;
        archive_authority(&authority, &input.output)?;
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires the original pinned model configuration with canonical selected gen1 zero material"]
async fn real_selected_initial_postload_rejection_keeps_same_owner_cleanup() -> TestResult<()> {
    for name in ["expiry", "revocation"] {
        let (input, worker, bytes) = input_and_worker(&format!("postload-{name}"))?;
        let fixture = Fixture::new(input.output.join(format!("postload-owner-{name}")), &bytes)?;
        let revoked_at = if name == "revocation" {
            Some(fixture.now + 60)
        } else {
            None
        };
        let (material, current) = fixture.selected(revoked_at)?;
        let (inputs, issuer, authority) = inputs(
            worker,
            &input.output.join(format!("postload-effects-{name}")),
            /*expected_claims*/ 1,
        )
        .await?;
        let config = fixture.config("body")?;
        let runtime = tokio::runtime::Handle::current();
        let now = initial_now_seconds()?;
        let late = fixture.now + if name == "expiry" { 181 } else { 60 };
        let mut clocks = [now, late, late].into_iter();
        let result = tokio::task::spawn_blocking(move || {
            prepare_initial(
                config,
                material,
                current,
                inputs,
                runtime,
                CancellationToken::new(),
                || Ok(clocks.next().unwrap_or(late)),
            )
        })
        .await?;
        let mut failure = match result {
            Err(e) => e,
            Ok(mut owner) => {
                owner.shutdown().await?;
                panic!("post-load {name} unexpectedly admitted")
            }
        };
        let retained = failure
            .retained
            .as_mut()
            .ok_or("original post-load session was lost")?;
        assert!(
            retained
                .with_current_initial_load::<()>(|_| panic!("rejected preparation exposed proof"))
                .is_err()
        );
        let load_ids = retained
            .session
            .port
            .as_ref()
            .unwrap()
            .with_measurements(|load, forward| {
                assert_eq!(load.generation(), 1);
                assert!(forward.is_none());
                load.control_load_ids()
                    .map(|v| (v.0.to_owned(), v.1.to_owned()))
            })?
            .ok_or("original load not settled")?;
        assert_eq!(load_ids.1, format!("reservation-{}", load_ids.0));
        failure.shutdown_retained().await?;
        assert!(failure.retained.is_none());
        issuer.await?.map_err(issuer_error)?;
        archive_authority(&authority, &input.output)?;
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires the original pinned model configuration with canonical selected gen1 zero material"]
async fn real_selected_initial_substituted_owner_trust_refuses_before_effects() -> TestResult<()> {
    let (input, worker, bytes) = input_and_worker("selected-trust-rejection")?;
    let fixture = Fixture::new(input.output.join("trust-owner"), &bytes)?;
    let (material, current) = fixture.selected(/*revoked_at*/ None)?;
    drop(current);
    let mut substituted = fixture.trust.clone();
    substituted.head_signers[0].expires_at += 1;
    let current = ArtifactOwnerCurrentReaderV1::open(
        fixture.root.join("artifacts"),
        substituted,
        fixture.head.clone(),
    )?;
    let (inputs, issuer, authority) = inputs(
        worker,
        &input.output.join("trust-effects"),
        /*expected_claims*/ 0,
    )
    .await?;
    let journal = inputs.inference_journal.clone();
    let result =
        prepare_selected_initial_smollm_v1(fixture.config("body")?, material, current, inputs)
            .await;
    match result {
        Err(e) => {
            assert!(e.retained.is_none());
            assert!(e.reason().contains("OwnerTrustMismatch"));
        }
        Ok(mut owner) => {
            owner.shutdown().await?;
            panic!("substituted trust was accepted")
        }
    }
    assert!(!journal.exists());
    issuer.await?.map_err(issuer_error)?;
    archive_authority(&authority, &input.output)?;
    Ok(())
}

#[path = "smollm_initial_cleanup_tests.rs"]
mod cleanup;

#[path = "smollm_initial_positive_tests.rs"]
mod positive;

#[path = "smollm_initial_query_tests.rs"]
mod initial_query;

#[path = "smollm_initial_agentd_tests.rs"]
mod agentd_tests;

#[path = "smollm_public_initial_loop_tests.rs"]
mod public_initial_loop_tests;

#[path = "smollm_neural_study_tests.rs"]
mod neural_study;
