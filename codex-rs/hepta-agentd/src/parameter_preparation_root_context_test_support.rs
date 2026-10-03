//! Complete fixture inputs published by the original signed file owner.
use super::*;

pub(super) struct PublishedArtifacts {
    pub(super) registry: ArtifactRegistry,
    pub(super) profile: ParameterGeneratorProfileV3,
    receipt: RegistrySnapshotReceipt,
    snapshot: PathBuf,
    withdrawals: PathBuf,
    withdrawal_receipt: DatasetWithdrawalSnapshotReceiptV1,
    trust: ArtifactOwnerTrustV1,
    owner_root: PathBuf,
    service: LearningArtifactOwnerService,
}
impl PublishedArtifacts {
    pub(super) fn new(
        root: &Path,
        material: &NeuronGenerationMaterialV2,
        now: u64,
        expires: u64,
    ) -> Self {
        let binding = PlasticityDynamicSignalBindingV1 {
            layer_id: id("neuron.sparse.rates.q24.v1"),
            parameter_id: id("threshold_rate_q24"),
            eligibility_index: 0,
            modulator_weights: vec![FixedQ32::ONE],
        };
        let window = ProposalWindowV2 {
            window_id: id("window.actual.prepare"),
            window_digest: digest("window.actual.prepare"),
        };
        let policy = build_parameter_mutation_policy_v1(
            id("policy:mutation"),
            digest("grammar.actual.prepare"),
            material.native.model_digest,
            window.clone(),
            vec![ParameterMutationRuleV1 {
                parameter_id: binding.parameter_id.clone(),
                layer_id: binding.layer_id.clone(),
                surface: ParameterMutationSurfaceV1::LearnableParameter,
                minimum_delta: FixedQ32::from_raw(-FixedQ32::ONE.raw()),
                maximum_delta: FixedQ32::ONE,
            }],
        )
        .expect("original mutation policy");
        let mutation_payload = mutation_payload(&policy);
        assert_eq!(Digest32::of_bytes(&mutation_payload), policy.policy_digest);
        let broadcast_payload = broadcast_payload(&binding);
        assert_eq!(
            Digest32::of_bytes(&broadcast_payload),
            plasticity_modulator_broadcast_digest_v1([&binding]).expect("original broadcast owner")
        );
        let profile = ParameterGeneratorProfileV3 {
            selected_artifact_digest: material.native.model_digest,
            window,
            norm_layers: vec![LayerNormDenominatorV2 {
                layer_id: binding.layer_id.clone(),
                baseline_squared_l2_raw_q64: sparse_parameter_norm_denominator_v1(&material.native)
                    .expect("original norm"),
            }],
            mutation_policy: policy,
            update_scales: vec![FixedQ32::ONE],
            signals: vec![ParameterPlasticitySignalV3 {
                layer_id: binding.layer_id,
                parameter_id: binding.parameter_id,
                eligibility: FixedQ32::ZERO,
                modulator: FixedQ32::ZERO,
                learning_rate: FixedQ32::ONE,
                lower_bound: FixedQ32::from_raw(-FixedQ32::ONE.raw()),
                upper_bound: FixedQ32::ONE,
                evidence_digest: digest("unsigned shape placeholder"),
            }],
        };
        let withdrawal_registry = DatasetWithdrawalRegistry::new_scoped(DatasetWithdrawalScopeV1 {
            authority_domain_id: id("fixture.dataset.authority"),
            registry_id: id("fixture.withdrawals"),
            scope_id: id("fixture.withdrawal.scope"),
        });
        let scope = withdrawal_registry
            .scope_digest()
            .expect("original withdrawal scope");
        let key = SigningKey::from_bytes(&[9; 32]);
        let signer = TrustedArtifactSignerV1 {
            signer_id: id("fixture.artifact.authority"),
            verifying_key: key.verifying_key().to_bytes(),
            minimum_authority_epoch: 1,
            maximum_authority_epoch: 1,
            valid_from: now - 1,
            expires_at: expires,
            revoked_at: None,
        };
        let trust = ArtifactOwnerTrustV1 {
            registry_id: id("fixture.artifacts"),
            withdrawal_scope_digest: scope,
            minimum_registry_generation: generation(1),
            genesis_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            writer_signers: vec![signer.clone()],
            head_signers: vec![signer],
        };
        let mut lease = SignedArtifactWriterLeaseV1 {
            lease_id: id("fixture.artifact.writer"),
            producer_id: id("owner:fixture-policy"),
            registry_id: trust.registry_id.clone(),
            withdrawal_scope_digest: scope,
            signer_id: id("fixture.artifact.authority"),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            authority_epoch: 1,
            lease_generation: 1,
            issued_at: now - 1,
            expires_at: expires,
            signature: [0; 64],
        };
        lease.signature = key.sign(&lease.signing_bytes()).to_bytes();
        let owner_root = root.join("artifact-owner");
        let mut service =
            LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
                root: owner_root.clone(),
                trust: trust.clone(),
                writer_lease: lease,
                required_current_head: None,
                withdrawal_registry: withdrawal_registry.clone(),
                storage_binding: digest("fixture.current.binding"),
                now,
            })
            .expect("original physical artifact writer");
        for (name, kind, payload) in [
            (
                "artifact.parameters.actual-head",
                ArtifactKind::Parameters,
                b"lock-metrics-head".to_vec(),
            ),
            (
                "policy:update-rule",
                ArtifactKind::Policy,
                b"fixture original update rule".to_vec(),
            ),
            ("policy:mutation", ArtifactKind::Policy, mutation_payload),
            ("policy:broadcast", ArtifactKind::Policy, broadcast_payload),
        ] {
            let manifest = LearningArtifactManifestV2 {
                artifact_id: id(name),
                kind,
                generation: material.runtime.generation,
                provenance_mode: ProvenanceModeV1::DatasetDerived,
                source_dataset_digests: vec![digest("fixture artifact source dataset")],
                lineage_digests: vec![digest("fixture artifact lineage")],
                predecessor_ids: vec![],
                rollback_predecessor: None,
                bytes_digest: Digest32::of_bytes(&payload),
                encoded_size_bytes: payload.len() as u64,
                training_code_digest: digest("fixture original code"),
                runtime_tuple_digest: material.runtime.semantic_digest().expect("runtime"),
                device_profile_digest: material.runtime.device_digest,
                objective_class_digest: material.scope.objective_digest,
                compatibility_digest: digest("fixture original compatibility"),
                schema_profile_digest: digest("fixture schema"),
                normalization_digest: material.native.normalization_digest,
                producer_id: id("owner:fixture-policy"),
                created_at: now - 1,
                expires_at: expires,
            };
            let admission = admit_manifest_at_withdrawal_head_v3(
                &withdrawal_registry,
                withdrawal_registry.head_digest(),
                manifest,
                now,
            )
            .expect("original full artifact admission");
            let operation = id(&format!("publication.{name}"));
            let preview = service
                .preview_registered_head(operation.clone(), admission.clone(), now)
                .expect("original fenced preview");
            let mut signed = SignedCurrentArtifactHeadV1 {
                withdrawal_scope_digest: scope,
                binding: digest("fixture.current.binding"),
                witness: RegistryHeadWitnessV1 {
                    registry_id: trust.registry_id.clone(),
                    generation: preview.generation,
                    head_digest: preview.head_digest,
                    predecessor_head_digest: preview.predecessor,
                    authority_epoch: 1,
                    signer_id: id("fixture.artifact.authority"),
                    signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                    issued_at: now,
                    expires_at: expires,
                },
                signature: [0; 64],
            };
            signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
            service
                .publish(LearningArtifactPublishRequestV1 {
                    operation_id: operation,
                    admission,
                    payload,
                    signed_current_head: signed,
                    expected_registry_predecessor_head: preview.predecessor,
                    now,
                })
                .expect("real original publication and CURRENT ACK");
        }
        let registry = service.registry().clone();
        let snapshot = root.join("artifacts.hpta");
        let receipt = write_registry_snapshot(
            CreateOnlyArtifactFile::create(&snapshot).expect("snapshot file"),
            &registry,
            digest("fixture.snapshot.binding"),
        )
        .expect("sole original snapshot codec");
        let withdrawals = root.join("withdrawals.hpta");
        let withdrawal_receipt = write_dataset_withdrawal_snapshot(
            CreateOnlyArtifactFile::create(&withdrawals).expect("withdrawal file"),
            &withdrawal_registry,
            digest("fixture.withdrawal.binding"),
        )
        .expect("original withdrawal codec");
        let verified = service
            .current_registry_view(now)
            .expect("genuine signed CURRENT");
        assert_eq!(verified.receipt().head_digest, registry.head_digest());
        assert!(
            ReadOnlyArtifactCurrentOwnerV1::open(
                &owner_root,
                trust.clone(),
                withdrawal_registry.clone(),
                now,
            )
            .is_err(),
            "writer CURRENT alone does not publish the independent Root read frontier"
        );
        service
            .publish_root_read_frontier(now)
            .expect("actual Root publishes the original acknowledged read frontier");
        let (current, opened_view) =
            ReadOnlyArtifactCurrentOwnerV1::open_with_current_registry_view(
                &owner_root,
                trust.clone(),
                withdrawal_registry,
                now,
            )
            .expect("same original protected CURRENT reader");
        assert_eq!(opened_view.receipt().head_digest, registry.head_digest());
        assert!(
            opened_view
                .eligible_manifest(&id("artifact.parameters.actual-head"))
                .is_some()
        );
        assert_eq!(
            current
                .current_registry_view(now)
                .expect("full authenticated protected CURRENT")
                .receipt()
                .head_digest,
            registry.head_digest()
        );
        Self {
            registry,
            profile,
            receipt,
            snapshot,
            withdrawals,
            withdrawal_receipt,
            trust,
            owner_root,
            service,
        }
    }
    pub(super) fn source_bytes(&self) -> Vec<(PathBuf, Vec<u8>)> {
        // The genuine owner exposes the exact live signed CURRENT and full
        // registry; neither publication is replaced by an in-memory fixture.
        self.service
            .current_registry_view(crate::authbus_ingress::now_ms().expect("clock"))
            .expect("still genuine CURRENT");
        let mut files = vec![self.snapshot.clone(), self.withdrawals.clone()];
        let mut directories = vec![self.owner_root.clone()];
        while let Some(directory) = directories.pop() {
            for entry in fs::read_dir(directory).expect("fixture owner directory") {
                let entry = entry.expect("fixture owner entry");
                let kind = entry.file_type().expect("fixture type");
                assert!(
                    !kind.is_symlink(),
                    "fixture original owner never follows links"
                );
                if kind.is_dir() {
                    directories.push(entry.path());
                } else {
                    assert!(kind.is_file());
                    files.push(entry.path());
                }
                assert!(
                    files.len() + directories.len() <= 128,
                    "bounded fixture file set"
                );
            }
        }
        files.sort();
        files
            .into_iter()
            .map(|path| {
                let bytes = fs::read(&path).expect("whole fixture owner bytes");
                assert!(
                    bytes.len() <= 4 * 1024 * 1024,
                    "bounded fixture publication"
                );
                (path, bytes)
            })
            .collect()
    }
    fn descriptor(&self, now: u64, expires: u64) -> Value {
        let signer = &self.trust.head_signers[0];
        let actor = json!({"signer_id":signer.signer_id.as_str(),"verifying_key_hex":crate::client::encode_hex(&signer.verifying_key),"minimum_authority_epoch":signer.minimum_authority_epoch,"maximum_authority_epoch":signer.maximum_authority_epoch,"valid_from":signer.valid_from,"expires_at":signer.expires_at,"revoked_at":null});
        let r = &self.withdrawal_receipt;
        json!({"path":self.snapshot,"receipt":{"binding":self.receipt.binding.to_string(),"head_digest":self.receipt.head_digest.to_string(),"file_digest":self.receipt.file_digest.to_string(),"records":self.receipt.records,"encoded_bytes":self.receipt.encoded_bytes},"observed_at":now,"expires_at":expires,
            "update_rule_artifact_id":"policy:update-rule","mutation_policy_artifact_id":"policy:mutation","broadcast_artifact_id":"policy:broadcast",
            "current_owner":{"owner_root":self.owner_root,"registry_id":self.trust.registry_id.as_str(),"withdrawal_scope_digest":self.trust.withdrawal_scope_digest.to_string(),"minimum_registry_generation":1,"genesis_predecessor_head_digest":Digest32::ZERO.to_string(),"minimum_authority_epoch":1,"writer_signers":[actor],"head_signers":[actor],
            "withdrawals":{"path":self.withdrawals,"binding":r.binding.to_string(),"scope_digest":r.scope_digest.to_string(),"head_digest":r.head_digest.to_string(),"file_digest":r.file_digest.to_string(),"records":r.records,"encoded_bytes":r.encoded_bytes}}})
    }
}

pub(super) fn write_search(
    root: &Path,
    profile: &ParameterGeneratorProfileV3,
) -> (PathBuf, Digest32) {
    write_source(
        root.join("unsigned-search.bin"),
        encode_untrusted_parameter_generator_profile_v3(profile).expect("original shape codec"),
    )
}
fn write_source(path: PathBuf, bytes: Vec<u8>) -> (PathBuf, Digest32) {
    fs::write(&path, &bytes).expect("independent complete fixture source");
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).expect("protected mode");
    (path, Digest32::of_bytes(&bytes))
}

pub(super) struct RootContextInputs<'a> {
    pub(super) fixture: &'a ClockFixture,
    pub(super) material: &'a NeuronGenerationMaterialV2,
    pub(super) anchor: JournalAnchor,
    pub(super) round: &'a crate::AgentdSelfIterationRoundV1,
    pub(super) artifacts: &'a PublishedArtifacts,
    pub(super) trust: Value,
    pub(super) now: u64,
    pub(super) expires: u64,
}
pub(super) fn write_context(root: &Path, input: RootContextInputs<'_>) -> (PathBuf, Digest32) {
    let RootContextInputs {
        fixture,
        material,
        anchor,
        round,
        artifacts,
        trust,
        now,
        expires,
    } = input;
    let baseline = write_source(
        root.join("baseline-material.bin"),
        encode_neuron_generation_material_v2(material).expect("whole original material"),
    );
    let subject = digest("agent:plasticity-subject");
    let values = vec![FixedQ32::from_raw(FixedQ32::ONE.raw() / 2)];
    let modulator =
        plasticity_modulator_digest_v1(material.scope.objective_digest, subject, &values)
            .expect("original modulator");
    let mut ndu = NduProjectionJournalV1::new();
    ndu.append_projection(
        NduProjectionKindV1::Utility,
        digest("actual root fixture projection"),
        material.scope.objective_digest,
        subject,
        modulator,
    )
    .expect("actual original NDU append");
    ndu.select_projection(
        digest("actual root fixture selection"),
        material.scope.objective_digest,
        subject,
        modulator,
    )
    .expect("actual original NDU selection");
    let ndu = write_source(root.join("actual-ndu.bin"), ndu.export_bytes());
    let ledger = fixture.owner.ledger.snapshot().expect("same actual Ledger");
    let dataset = freeze_dataset_receipt_v3(
        DatasetFreezeRequestV1 {
            snapshot_id: id("dataset.actual.root.prepare"),
            producer: AuthenticatedPrincipalV1 {
                principal_id: id("owner:dataset"),
                credential_chain_digest: digest("actual dataset chain"),
                signing_key_digest: digest("actual dataset key"),
                scope_digest: material.scope.scope_digest,
                authority_epoch: 1,
                authenticated_at: now - 1,
                expires_at: expires,
            },
            ledger_head_digest: ledger.head_digest,
            objective_digest: material.scope.objective_digest,
            eligible_frontier: 1,
            outcome_watermark: 1,
            correction_cut_digest: digest("actual dataset correction"),
            revocation_cut_digest: digest("actual dataset revocation"),
            inclusion_policy_digest: digest("actual dataset inclusion"),
            source_record_digests: vec![ledger.head_digest],
            pending_outcomes: 0,
            censored_outcomes: 0,
        },
        now,
    )
    .expect("whole actual original DatasetReceiptV3");
    let n = &material.native;
    let value = json!({"schema":"hepta.agentd.plasticity-input-context.v2","agent_id":fixture.state.identity().agent_id.as_str(),"spawn_generation":fixture.state.identity().spawn_generation,
        "round_hex":crate::client::encode_hex(&round.canonical_bytes().expect("actual sealed Round")),"predecessor_registry_head_digest":fixture.owner.artifacts.head_digest().to_string(),
        "baseline_id":"artifact.parameters.actual-head","objective_digest":material.scope.objective_digest.to_string(),"baseline_material":{"path":baseline.0,"digest":baseline.1.to_string()},
        "artifacts":artifacts.descriptor(now,expires),
        "dataset":{"snapshot":{"snapshot_id":dataset.snapshot.snapshot_id.as_str(),"ledger_head_digest":dataset.snapshot.ledger_head_digest.to_string(),"objective_digest":dataset.snapshot.objective_digest.to_string(),"eligible_frontier":dataset.snapshot.eligible_frontier,"outcome_watermark":dataset.snapshot.outcome_watermark,"source_record_digests":dataset.snapshot.source_record_digests.iter().map(ToString::to_string).collect::<Vec<_>>(),"pending_outcomes":dataset.snapshot.pending_outcomes,"censored_outcomes":dataset.snapshot.censored_outcomes,"dataset_digest":dataset.snapshot.dataset_digest.to_string()},"producer":principal_json(&dataset.producer),"correction_cut_digest":dataset.correction_cut_digest.to_string(),"revocation_cut_digest":dataset.revocation_cut_digest.to_string(),"inclusion_policy_digest":dataset.inclusion_policy_digest.to_string()},
        "ndu":{"journal_path":ndu.0,"subject_digest":subject.to_string(),"owner_id":"owner:utility.ndu","modulator_values_raw_q32":values.iter().map(|v|v.raw()).collect::<Vec<_>>()},"ndu_journal_digest":ndu.1.to_string(),
        "neuron":{"journal_path":material.generation_store,"owner_id":"owner:neuron.runtime","scope_digest":material.scope.scope_digest.to_string(),"objective_digest":material.scope.objective_digest.to_string(),"max_records":material.store_context.max_records,"anchor_sequence":anchor.sequence,"anchor_checkpoint_digest":anchor.checkpoint_digest.to_string(),
            "config":{"model_digest":n.model_digest.to_string(),"normalization_digest":n.normalization_digest.to_string(),"generation":n.generation.get(),"width":n.width,"top_k":n.top_k,"temporal_decay_q24":n.temporal_decay_q24,"inhibition_gain_q24":n.inhibition_gain_q24,"inhibition":[],"activity_decay_q24":n.activity_decay_q24,"target_activity_q24":n.target_activity_q24,"threshold_rate_q24":n.threshold_rate_q24,"threshold_min_q24":n.threshold_min_q24,"threshold_max_q24":n.threshold_max_q24,"eligibility_decay_q24":n.eligibility_decay_q24}},
        "signal_bindings":[{"layer_id":"neuron.sparse.rates.q24.v1","parameter_id":"threshold_rate_q24","eligibility_index":0,"modulator_weights_raw_q32":[FixedQ32::ONE.raw()]}],"trust":trust,
        "owner_policy":{"dataset_owner_id":"owner:dataset","update_rule_owner_id":"owner:fixture-policy","mutation_policy_owner_id":"owner:fixture-policy","modulator_owner_id":"owner:utility.ndu","modulator_broadcast_owner_id":"owner:fixture-policy","eligibility_owner_id":"owner:neuron.runtime","parameter_signal_owner_id":"owner:neuron.runtime"}});
    write_source(
        root.join("complete-context.json"),
        serde_json::to_vec(&value).expect("full protected descriptor"),
    )
}

// Fixture payloads are independently checked against the original public digest
// functions before the actual publication owner accepts them. No production
// signing/authority API is added for these deterministic test vectors.
fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    bytes.extend_from_slice(
        &u32::try_from(value.as_str().len())
            .expect("fixture ID bound")
            .to_be_bytes(),
    );
    bytes.extend_from_slice(value.as_str().as_bytes());
}
fn mutation_payload(policy: &ParameterMutationPolicyV1) -> Vec<u8> {
    let mut bytes = b"hepta.plasticity.parameter-mutation-policy.v1\0".to_vec();
    push_id(&mut bytes, &policy.policy_id);
    bytes.extend_from_slice(policy.mutation_grammar_digest.as_array());
    bytes.extend_from_slice(policy.selected_artifact_digest.as_array());
    push_id(&mut bytes, &policy.window.window_id);
    bytes.extend_from_slice(policy.window.window_digest.as_array());
    bytes.extend_from_slice(
        &u32::try_from(policy.rules.len())
            .expect("fixture rules")
            .to_be_bytes(),
    );
    for r in &policy.rules {
        assert_eq!(r.surface, ParameterMutationSurfaceV1::LearnableParameter);
        push_id(&mut bytes, &r.parameter_id);
        push_id(&mut bytes, &r.layer_id);
        bytes.push(0);
        bytes.extend_from_slice(&r.minimum_delta.raw().to_be_bytes());
        bytes.extend_from_slice(&r.maximum_delta.raw().to_be_bytes());
    }
    bytes
}
fn broadcast_payload(binding: &PlasticityDynamicSignalBindingV1) -> Vec<u8> {
    let mut bytes = b"hepta.neuron.modulator-broadcast.v1\0".to_vec();
    push_id(&mut bytes, &binding.layer_id);
    push_id(&mut bytes, &binding.parameter_id);
    bytes.extend_from_slice(&binding.eligibility_index.to_be_bytes());
    bytes.extend_from_slice(
        &u32::try_from(binding.modulator_weights.len())
            .expect("fixture weights")
            .to_be_bytes(),
    );
    for weight in &binding.modulator_weights {
        bytes.extend_from_slice(&weight.raw().to_be_bytes());
    }
    bytes
}
