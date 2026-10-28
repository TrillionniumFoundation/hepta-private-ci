//! Original selector and publisher, with actual fresh Cell consumer bytes.
use super::*;
use cognitive_process_evaluation::*;
use cognitive_process_evidence::*;
use cognitive_process_materials::*;
use pretty_assertions::assert_eq;

pub(super) struct Installed {
    pub descriptor: PathBuf,
    pub descriptor_digest: Digest32,
    pub worker: SmolLmNeuralReadConfigV1,
    pub child: Value,
    pub current_receipt: RegistrySnapshotReceipt,
    pub current: ArtifactOwnerCurrentReaderV1,
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn manifest_id(context: &Value, raw: &[u8]) -> TestResult<Digest32> {
    let family = context["family"].as_str().ok_or("Cell family")?;
    let mut bytes = b"TCM1".to_vec();
    bytes.push(u8::try_from(family.len())?);
    bytes.extend_from_slice(family.as_bytes());
    for key in ["base", "parent", "tokenizer", "layout", "runtime"] {
        let digest: Digest32 = context[key].as_str().ok_or("Cell context")?.parse()?;
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
    bytes.extend_from_slice(Digest32::of_bytes(raw).as_array());
    bytes.extend_from_slice(&1_048_576_u32.to_be_bytes());
    bytes.extend_from_slice(&u32::try_from(raw.len().div_ceil(1_048_576))?.to_be_bytes());
    for chunk in raw.chunks(1_048_576) {
        bytes.extend_from_slice(&u32::try_from(chunk.len())?.to_be_bytes());
        bytes.extend_from_slice(Digest32::of_bytes(chunk).as_array());
    }
    Ok(Digest32::of_parts(&[b"trnm.cell-manifest.v1\0", &bytes]))
}

fn current(fixture: &Fixture) -> Value {
    let signer = |value: &TrustedArtifactSignerV1| {
        json!({"signer_id":value.signer_id.as_str(),"verifying_key_hex":hex(&value.verifying_key),
        "minimum_authority_epoch":value.minimum_authority_epoch,"maximum_authority_epoch":value.maximum_authority_epoch,
        "valid_from":value.valid_from,"expires_at":value.expires_at,"revoked_at":value.revoked_at})
    };
    let trust = &fixture.trust;
    let head = &fixture.head;
    let witness = &head.witness;
    json!({"root":fixture.root.join("artifacts"),"trust":{"registry_id":trust.registry_id.as_str(),
        "withdrawal_scope_digest":trust.withdrawal_scope_digest.to_string(),"minimum_registry_generation":trust.minimum_registry_generation.get(),
        "genesis_predecessor_head_digest":trust.genesis_predecessor_head_digest.to_string(),"minimum_authority_epoch":trust.minimum_authority_epoch,
        "writer_signers":trust.writer_signers.iter().map(signer).collect::<Vec<_>>(),"head_signers":trust.head_signers.iter().map(signer).collect::<Vec<_>>()},
        "required_current_head":{"withdrawal_scope_digest":head.withdrawal_scope_digest.to_string(),"binding":head.binding.to_string(),
            "registry_id":witness.registry_id.as_str(),"generation":witness.generation.get(),"head_digest":witness.head_digest.to_string(),
            "predecessor_head_digest":witness.predecessor_head_digest.to_string(),"authority_epoch":witness.authority_epoch,
            "signer_id":witness.signer_id.as_str(),"signing_key_digest":witness.signing_key_digest.to_string(),
            "issued_at":witness.issued_at,"expires_at":witness.expires_at,"signature_hex":hex(&head.signature)}})
}

#[allow(clippy::too_many_arguments)]
pub(super) fn install(
    input: &NativeInput,
    root: &Path,
    fixture: &mut Fixture,
    config: &AgentdConfig,
    trained: &Value,
    child: &Value,
    dataset: &ledger::DatasetSnapshotReceiptV3,
    ledger: &ledger::LedgerSnapshot,
    roles: &mut roles::ControlledRoles,
    actions: BTreeMap<StableId, String>,
    qualified: evaluation::Qualified,
) -> TestResult<Installed> {
    let parent = read_pin(&trained["parent"])?;
    let training_data = read_pin(&trained["training_data"])?;
    let consumption = read_pin(&trained["training_consumption"])?;
    let receipt = read_pin(&trained["training"])?;
    if trained["source_dataset_digest"] != dataset.snapshot.dataset_digest.to_string()
        || training_data["source_dataset_digest"] != dataset.snapshot.dataset_digest.to_string()
        || training_data["dataset_receipt"]
            != serde_json::to_value(DatasetSnapshotReceiptV3Raw::from(dataset.clone()))?
        || consumption["training_data"] != trained["training_data"]
        || consumption["actual_receipt"] != trained["training"]
        || receipt["candidate"]["file_sha256"] != child["file_sha256"]
        || fixture.service.withdrawal_registry().head_digest() != qualified.withdrawal_head
    {
        return Err("actual consumed dataset, trained candidate or withdrawal frontier changed before selection".into());
    }
    let payload_digest: Digest32 = child["file_sha256"]
        .as_str()
        .ok_or("child payload")?
        .parse()?;
    let parent_digest: Digest32 = parent["file_sha256"]
        .as_str()
        .ok_or("parent payload")?
        .parse()?;
    let request = eval::SelfEvolutionSelectionRequestV1 {
        selection_id: id("real-neural-study-gen2-selection"),
        predecessor_id: id("selected-initial-zero"),
        predecessor_generation: Generation::new(/*value*/ 1)?,
        predecessor_artifact_digest: parent_digest,
        candidate_id: id("real-trained-generation-two"),
        candidate_generation: Generation::new(/*value*/ 2)?,
        candidate_artifact_digest: payload_digest,
    };
    let policy = eval::SelfEvolutionSelectionPolicyV1 {
        no_change_baseline_id: request.predecessor_id.clone(),
        no_change_baseline_digest: parent_digest,
        minimum_dataset_records: 16,
        minimum_future_window_micros: 1_000_000,
    };
    let binding = roles.sign(
        /*index*/ 1,
        &eval::product_candidate_binding_payload_v1(&request, &qualified.receipt)?,
    );
    let prepared = eval::prepare_self_evolution_product_selection_v1(
        &qualified.receipt,
        &binding,
        &policy,
        request.clone(),
        qualified.bundle.clone(),
        qualified.metric_roles.clone(),
        &qualified.evidence,
        &qualified.timing,
        dataset,
        ledger,
        &roles.verifier,
        now(),
    )?;
    let selector = roles.sign(
        /*index*/ 3,
        &eval::selection_signing_payload_v1(prepared.receipt())?,
    );
    let admitted =
        eval::admit_self_evolution_selection_v1(prepared, &selector, &roles.verifier, now())?;
    admitted.require_product_qualification()?;
    let before = fixture
        .service
        .current_registry_view(initial_now_seconds()?)?
        .receipt();
    let child_directory = PathBuf::from(child["directory"].as_str().ok_or("child directory")?);
    let contract: Value =
        serde_json::from_slice(&fs::read(child_directory.join("target-contract.json"))?)?;
    let runtime = pin(&input.chain.join("scripts/llm_neural_read_worker.py"))?;
    let context = json!({"family":"smollm2-135m-cpu-dev-v1","base":contract["backbone"]["index_root"],
        "parent":payload_digest.to_string(),"tokenizer":contract["tokenizer"]["files_root"],"layout":child["contract"],"runtime":runtime["sha256"]});
    let mut members = serde_json::Map::new();
    for name in [
        "artifact.safetensors",
        "target-contract.json",
        "wrapped-adapter.json",
    ] {
        let path = child_directory.join(name);
        let raw = fs::read(&path)?;
        if !(1..=2 * 1024 * 1024).contains(&raw.len()) {
            return Err("narrow child member size".into());
        }
        members.insert(
            name.to_owned(),
            json!({"path":path,"sha256":Digest32::of_bytes(&raw).to_string(),
            "bytes":raw.len(),"manifest_id":manifest_id(&context,&raw)?.to_string()}),
        );
    }
    let binary = PathBuf::from(
        std::env::var_os("HEPTA_NEURAL_STUDY_CELL").ok_or("real Cell executable required")?,
    )
    .canonicalize()?;
    let transport = save(
        &root.join("cell-input.json"),
        &json!({"schema":"hepta-neural-candidate-transport-input-v1","binary":pin(&binary)?,
        "training":trained["training"],"completion":trained["completion"],"parent":trained["parent"],"child":trained["child"],
        "runtime":runtime,"observation_execution":trained["observation_execution"],"context":context,"members":members}),
    )?;
    let output = root.join("cell");
    let script =
        PathBuf::from(std::env::var_os("HEPTA_NEURAL_STUDY_RUNNER").ok_or("study runner")?);
    helper(
        input,
        &script,
        &json!({"schema":"hepta-neural-study-v1","operation":"transport","request":transport,"output":output}),
        &root.join("cell-launch"),
        /*seconds*/ 45,
    )?;
    let received = read_pin(&pin(&output.join("transport-result.json"))?)?;
    if received["outcome"] != "success"
        || received["independent_nodes"] != 2
        || received["child"] != *child
        || fixture
            .service
            .current_registry_view(initial_now_seconds()?)?
            .receipt()
            != before
    {
        return Err("actual fresh Cell acquisition or unchanged CURRENT required".into());
    }
    let downloaded = PathBuf::from(
        received["downloaded_directory"]
            .as_str()
            .ok_or("downloaded directory")?,
    );
    for name in [
        "artifact.safetensors",
        "target-contract.json",
        "wrapped-adapter.json",
    ] {
        if fs::read(downloaded.join(name))? != fs::read(child_directory.join(name))? {
            return Err("downloaded candidate bytes changed".into());
        }
    }
    let (_, mut worker, _) = input_and_worker("positive-child")?;
    worker.target_contract = fs::read(downloaded.join("target-contract.json"))?;
    worker.wrapped_adapter = fs::read(downloaded.join("wrapped-adapter.json"))?;
    worker.contract_digest = child["contract"]
        .as_str()
        .ok_or("child contract")?
        .parse()?;
    worker.adapter_digest = child["adapter"].as_str().ok_or("child adapter")?.parse()?;
    worker.action_completions = actions;
    let model = codex_hepta_agentd::NeuralCognitivePinV1 {
        payload_digest,
        objective_digest: dataset.snapshot.objective_digest,
        dataset_digest: dataset.snapshot.dataset_digest,
        generation: Generation::new(/*value*/ 2)?,
        family_digest: worker.source_identities()?["model-family-smollm2-135m-v1.json"].parse()?,
        execution_profile_digest: worker.execution_profile_digest()?,
    };
    let trained_receipt = read_pin(&trained["training"])?;
    let seconds = initial_now_seconds()?;
    let source = LearningArtifactManifestV2 {
        artifact_id: request.candidate_id.clone(),
        kind: ArtifactKind::Parameters,
        generation: model.generation,
        provenance_mode: ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![model.dataset_digest],
        lineage_digests: vec![parent_digest],
        predecessor_ids: vec![request.predecessor_id.clone()],
        rollback_predecessor: Some(request.predecessor_id.clone()),
        bytes_digest: payload_digest,
        encoded_size_bytes: fs::metadata(downloaded.join("artifact.safetensors"))?.len(),
        training_code_digest: trained_receipt["source"]["parent_step_v2"]
            .as_str()
            .ok_or("actual training source")?
            .parse()?,
        runtime_tuple_digest: model.execution_profile_digest,
        device_profile_digest: digest("actual observed CPU float32 SmolLM2 study"),
        objective_class_digest: model.objective_digest,
        compatibility_digest: model.compatibility_digest(),
        schema_profile_digest: digest("original canonical safetensors LoRA parameters"),
        normalization_digest: digest("original float32 normalization"),
        producer_id: qualified.bundle.generator.principal_id.clone(),
        created_at: seconds,
        expires_at: fixture.now + 3600,
    };
    // The original writer lease is producer-bound. This controlled study uses
    // that exact producer; the independent generator remains evaluation provenance.
    let source = LearningArtifactManifestV2 {
        producer_id: id("initial-material-producer"),
        ..source
    };
    let withdrawals = fixture.service.withdrawal_registry();
    let admission = admit_manifest_at_withdrawal_head_v3(
        withdrawals,
        withdrawals.head_digest(),
        source.clone(),
        seconds,
    )?;
    let transaction = ArtifactPublicationTransactionV1::begin(
        id("publish-real-trained-child"),
        admission.clone(),
        withdrawals,
        fixture.service.registry(),
        before.head_digest,
        seconds,
    )?;
    let manifest = ArtifactManifest {
        artifact_id: source.artifact_id.clone(),
        kind: source.kind,
        generation: source.generation,
        predecessor_id: source.rollback_predecessor.clone(),
        content_digest: source.bytes_digest,
        objective_digest: source.objective_class_digest,
        support_digest: admission.validated_manifest.manifest_digest,
        producer_id: source.producer_id.clone(),
        compatibility_digest: source.compatibility_digest,
        encoded_size_bytes: source.encoded_size_bytes,
    };
    let mut projected = fixture.service.registry().clone();
    projected.append(ArtifactEvent::Register {
        event_id: id(&format!(
            "artifact-publication:{}",
            transaction.intent().intent_digest
        )),
        manifest: manifest.clone(),
    })?;
    let head = Fixture::sign_head(
        &fixture.trust,
        &fixture.owner_key,
        &projected,
        before.head_digest,
        seconds,
    )?;
    let publication = LearningArtifactPublishRequestV1 {
        operation_id: id("publish-real-trained-child"),
        admission,
        payload: fs::read(downloaded.join("artifact.safetensors"))?,
        signed_current_head: head.clone(),
        expected_registry_predecessor_head: before.head_digest,
        now: seconds,
    };
    let first = fixture.service.publish(publication.clone())?;
    assert_eq!(fixture.service.publish(publication)?, first);
    fixture.head = head;
    let receipt = fixture
        .service
        .current_registry_view(initial_now_seconds()?)?
        .receipt();
    if receipt.records != before.records + 1
        || fixture.service.registry().manifest(&request.candidate_id) != Some(&manifest)
    {
        return Err("ordinary publication did not preserve exact gen2 predecessor".into());
    }
    let snapshot = fixture.root.join("artifacts/registries").join(format!(
        "{}-{}.snapshot",
        receipt.head_digest, receipt.file_digest
    ));
    let payload = fixture.root.join("artifacts/payloads").join(format!(
        "{}-{}.bin",
        manifest.artifact_id, manifest.content_digest
    ));
    if fs::read(&payload)? != fs::read(downloaded.join("artifact.safetensors"))? {
        return Err("published bytes differ from Cell consumer".into());
    }
    let last = ledger
        .records()
        .last()
        .ok_or("nonempty actual training history")?;
    let descriptor = root.join("child-bootstrap.json");
    let descriptor_pin = save(
        &descriptor,
        &json!({"schema":"hepta.agentd.cognitive-bootstrap.v3","profile":"published_neural_product_qualification_v1",
        "agent_id":config.identity().agent_id.as_str(),"spawn_generation":config.identity().spawn_generation,
        "snapshot_path":snapshot,"payload_path":payload,"selected":PinnedCandidateSpecRaw::from(PinnedCandidateSpec { manifest,registry_receipt:receipt }),
        "model_pin":{"payload_digest":model.payload_digest.to_string(),"objective_digest":model.objective_digest.to_string(),"dataset_digest":model.dataset_digest.to_string(),
            "generation":2,"family_digest":model.family_digest.to_string(),"execution_profile_digest":model.execution_profile_digest.to_string()},
        "source_manifest":LearningArtifactManifestV2Raw::from(source),"current":current(fixture),"policy":SelfEvolutionSelectionPolicyV1Raw::from(policy),
        "selection_request":SelfEvolutionSelectionRequestV1Raw::from(request),"frozen_plan":CrossFoldPlanV1Raw::from(qualified.raw_plan),
        "product":qualified.product,"product_candidate_binding_evidence":SignedLearningEvidenceV1Raw::from(binding),
        "metric_roles":qualified.metric_roles.into_iter().map(MetricRoleContractV2Raw::from).collect::<Vec<_>>(),
        "evaluation_evidence":SignedEvaluationEvidenceV1Raw::from(qualified.evidence),"longitudinal_time":LongitudinalTimeEvidenceV1Raw::from(qualified.timing),
        "dataset_receipt":DatasetSnapshotReceiptV3Raw::from(dataset.clone()),"ledger":{"path":root.join("training-ledger/ledger"),
            "binding":digest("controlled-neural-actual-training-ledger").to_string(),"max_records":512,"anchor_sequence":last.sequence.get(),"anchor_chain_digest":last.chain_digest.to_string()},
        "holdout":qualified.holdout,"trust":LearningEvidenceTrustV1Raw::from(roles.trust.clone()),"selector_evidence":SignedLearningEvidenceV1Raw::from(selector)}),
    )?;
    save(
        &root.join("actual-child-publication.json"),
        &json!({"schema":"hepta-neural-study-publication-v1","transport":pin(&output.join("transport-result.json"))?,
        "descriptor":descriptor_pin,"parent_file_sha256":parent_digest.to_string(),"child_file_sha256":payload_digest.to_string(),
        "same_owner_root":fixture.root,"before":before.head_digest.to_string(),"after":receipt.head_digest.to_string(),
        "same_writer_lease":true,"exact_retry_equal":true,"generation":2,"ordinary_child_read":false}),
    )?;
    Ok(Installed {
        descriptor,
        descriptor_digest: descriptor_pin["sha256"]
            .as_str()
            .ok_or("descriptor digest")?
            .parse()?,
        worker,
        child: child.clone(),
        current_receipt: receipt,
        current: ArtifactOwnerCurrentReaderV1::open(
            fixture.root.join("artifacts"),
            fixture.trust.clone(),
            fixture.head.clone(),
        )?,
    })
}
