//! Explicit engineering input authorities. Root supplies these before either
//! production process starts. The Observer key is never installed in A and no
//! input object represents an admitted run, a Decision or a terminal Outcome.

use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_objective::ObjectiveAdmissionContextV1;
use codex_hepta_objective::ObjectiveSourceAuthenticationV1;
use codex_hepta_objective::admit_and_compile_objective_v1;
use codex_hepta_objective::canonical_objective_intent_digest_v1;
use codex_hepta_objective::decode_admission_profile_json_v1;
use codex_hepta_objective::decode_source_envelope_json_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::Value;
use serde_json::json;

use super::deployment::OriginalAFilePaths;
use super::deployment::digest;
use crate::AgentdIdentity;
use crate::AuthBusObjectiveBody;
use crate::AuthBusObjectiveIngress;
use crate::root_initial_learning_trust_data::LearningTrustPayloadV1;

pub(super) const OBJECTIVE_ISSUER: &str = "ordinary-original-objective-issuer";
pub(super) const RUN: &str = "ordinary-original-a";
pub(super) const C_RUN: &str = "ordinary-original-c";

enum OriginalRequest {
    A,
    C,
}

pub(super) struct ObjectiveInputs {
    pub(super) request: AuthBusObjectiveIngress,
    pub(super) trust: Value,
    pub(super) profile: Value,
    pub(super) objective: Digest32,
}

impl ObjectiveInputs {
    pub(super) fn new(
        identity: &AgentdIdentity,
        bundle: &CellCompatibilityBundleV1,
        now: u64,
    ) -> anyhow::Result<Self> {
        Self::for_original_request(identity, bundle, now, OriginalRequest::A)
    }

    pub(super) fn successor(
        identity: &AgentdIdentity,
        bundle: &CellCompatibilityBundleV1,
        now: u64,
    ) -> anyhow::Result<Self> {
        Self::for_original_request(identity, bundle, now, OriginalRequest::C)
    }

    fn for_original_request(
        identity: &AgentdIdentity,
        bundle: &CellCompatibilityBundleV1,
        now: u64,
        original: OriginalRequest,
    ) -> anyhow::Result<Self> {
        let (run_id, message_id, sequence) = match original {
            OriginalRequest::A => (RUN, "ordinary-original-a-message", 1),
            OriginalRequest::C => (C_RUN, "ordinary-original-c-message", 2),
        };
        // This fixture is already a declared compile_data file in both Agentd
        // Bazel test targets. Only public structured admission data is reused.
        let mut document: Value = serde_json::from_str(
            &include_str!("../tests/fixtures/notes-objective-literal-v1.json")
                .replace("notes.replace", "circuit.compute")
                .replace("notes", "circuit"),
        )?;
        // The reused grammar does not enroll its old Notes/Circuit issuer.
        // Pin the one actual AuthBus issuer before computing either digest.
        document["profile"]["allowedTrustedSourceIdentities"] = json!([OBJECTIVE_ISSUER]);
        let profile = document["profile"].clone();
        let admitted_profile = decode_admission_profile_json_v1(&serde_json::to_vec(&profile)?)?;
        let source = &mut document["source"];
        source["requestId"] = json!(run_id);
        source["observedAt"] = json!(crate::notes_literal_prepare::utc_millis(now)?);
        source["deadline"] = json!(crate::notes_literal_prepare::utc_millis(
            now.checked_add(120_000)
                .ok_or_else(|| anyhow::anyhow!("objective deadline overflow"))?
        )?);
        source["structuredIntent"]["resources"]["externalEffectCount"] = json!(0);
        source["structuredIntent"]["provenance"]["sourceDigest"] =
            json!(Digest32::of_bytes(b"original ordinary fixture business request").to_string());
        let decoded = decode_source_envelope_json_v1(&serde_json::to_vec(source)?)?;
        source["intentDigest"] = json!(canonical_objective_intent_digest_v1(&decoded)?.to_string());
        let decoded = decode_source_envelope_json_v1(&serde_json::to_vec(source)?)?;
        let context = ObjectiveAdmissionContextV1 {
            revision: Revision::new(1)?,
            now_unix_micros: now
                .checked_mul(1_000)
                .ok_or_else(|| anyhow::anyhow!("objective clock overflow"))?,
            selected_profile_digest: admitted_profile.digest()?,
            source_authentication: ObjectiveSourceAuthenticationV1::AuthorizedAdapter {
                source_identity: StableId::new(OBJECTIVE_ISSUER)?,
                source_digest: decoded.structured_intent.provenance.source_digest,
            },
        };
        // The real daemon must later authenticate, append+sync and publish this
        // same request. Compilation here determines only its fixed semantic ID.
        let compiled = admit_and_compile_objective_v1(&decoded, &admitted_profile, &context)?
            .compile_result
            .map_err(|error| anyhow::anyhow!("explicit objective input conflicts: {error:?}"))?;
        let key = SigningKey::from_bytes(&[91; 32]);
        let trust = json!({
            "schema_version": 1, "agent_id": identity.agent_id.as_str(),
            "issuer_id": OBJECTIVE_ISSUER, "key_epoch": 1,
            "public_key_hex": hex(key.verifying_key().as_bytes()),
            "revoked": false, "thread_ids": []
        });
        let mut request = AuthBusObjectiveIngress {
            issuer_id: OBJECTIVE_ISSUER.into(),
            key_epoch: 1,
            message_id: message_id.into(),
            sequence,
            expires_at_ms: now
                .checked_add(180_000)
                .ok_or_else(|| anyhow::anyhow!("AuthBus expiry overflow"))?,
            signature_hex: String::new(),
            body: AuthBusObjectiveBody {
                spawn_generation: identity.spawn_generation,
                run_id: run_id.into(),
                objective_revision: 1,
                source_envelope_json: serde_json::to_string(source)?,
                runtime_body_digest: crate::CellQ24FeatureWorkerV1::runtime_profile_digest()
                    .to_string(),
                preference_state_digest: admitted_profile.digest()?.to_string(),
                model_tuple_digest: bundle.digest()?.to_string(),
                prompt_registry_digest: Digest32::of_bytes(
                    b"ordinary finite circuit: no prompt dispatch",
                )
                .to_string(),
                artifact_set_digest: bundle.digest()?.to_string(),
                authority_epoch: 1,
            },
        };
        request.signature_hex = hex(&key
            .sign(&crate::authbus_objective_claims(identity, &request)?.signing_bytes())
            .to_bytes());
        Ok(Self {
            request,
            trust,
            profile,
            objective: compiled.objective.semantic_digest,
        })
    }
}

pub(super) fn original_learning_payload(
    objective: Digest32,
    now_seconds: u64,
) -> anyhow::Result<LearningTrustPayloadV1> {
    let mut payload = crate::root_initial_learning_trust_data::tests::payload();
    payload.root.valid_from_seconds = now_seconds
        .checked_sub(1)
        .ok_or_else(|| anyhow::anyhow!("original clock absent"))?;
    payload.root.expires_at_seconds = now_seconds
        .checked_add(600)
        .ok_or_else(|| anyhow::anyhow!("original trust expiry overflow"))?;
    payload.distribution.objective_digest = objective.into_array();
    payload.distribution.effective_at_seconds = now_seconds;
    payload.distribution.issued_at_seconds = now_seconds;
    payload.distribution.expires_at_seconds = payload.root.expires_at_seconds;
    for signer in &mut payload.distribution.signers {
        signer.authenticated_at_seconds = now_seconds;
        signer.expires_at_seconds = payload.root.expires_at_seconds;
    }
    crate::root_initial_learning_trust_data::tests::sign(&mut payload)
        .map_err(|error| anyhow::anyhow!("explicit original Root signature: {error}"))?;
    payload.activate_pinned_genesis(now_seconds)?;
    Ok(payload)
}

pub(super) fn ledger_data(paths: &OriginalAFilePaths, now_seconds: u64) -> anyhow::Result<Value> {
    Ok(json!({
        "schema": "hepta.agentd.original_initial_q24_ledger.v1", "mode": "create",
        "ledger": paths.ledger, "ledger_witness": paths.ledger_witness,
        "binding": digest("ordinary-original-a-ledger"), "maximum_records": 128,
        "generator_key": paths.generator_key, "signature_journal": paths.signatures,
        "signature_witness": {
            "path": paths.signature_witness, "scope": digest("ordinary-original-a-signatures"),
            "generation": 1, "maximum_records": 128
        },
        "contract": {
            "episode_id": "ordinary-original-a-episode", "candidate_set_id": "ordinary-original-a-candidates",
            "generator_code_digest": crate::CellQ24FeatureWorkerV1::runtime_profile_digest().into_array(),
            "grammar_digest": digest("ordinary-original-finite-q24-grammar"),
            "hard_filter_digest": digest("ordinary-original-all-declared-candidates"),
            "truncation_digest": digest("ordinary-original-no-candidate-truncation"),
            "outcome_record_id": "ordinary-original-a-outcome-record", "outcome_id": "ordinary-original-a-outcome",
            "unit_profile_digest": digest("ordinary-observed-scalar-q24"),
            "expected_delay_profile_digest": digest("ordinary-immediate-external-observation"),
            "claim_deadline_unix_seconds": now_seconds.checked_add(300).ok_or_else(|| anyhow::anyhow!("original claim deadline overflow"))?,
            "maximum_signature_lifetime_seconds": 300
        }
    }))
}

pub(super) fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

#[test]
fn ordinary_q24_input_authorities_bind_actual_objective_without_supplying_a_receipt()
-> anyhow::Result<()> {
    let objective = Digest32::of_bytes(b"explicit ordinary business objective");
    let now = crate::authbus_ingress::now_ms()? / 1_000;
    let payload = original_learning_payload(objective, now)?;
    let (activated, generator, observer) = payload.activate_pinned_genesis(now)?;
    pretty_assertions::assert_eq!(activated.verifier().objective_digest(), objective);
    assert_ne!(
        generator.principal.principal_id,
        observer.principal.principal_id
    );
    assert_ne!(generator.controller_id, observer.controller_id);
    let root = tempfile::tempdir()?;
    let paths = OriginalAFilePaths::new(root.path(), root.path());
    let ledger: crate::production_launcher::LedgerDeploymentData =
        serde_json::from_value(ledger_data(&paths, now)?)?;
    let configured = ledger.configuration(generator.clone(), observer.clone(), now)?;
    pretty_assertions::assert_eq!(
        (configured.generator, configured.observer),
        (generator, observer)
    );
    assert!(std::fs::read(paths.ledger).is_err());
    Ok(())
}

#[test]
fn ordinary_q24_objective_inputs_admit_only_the_actual_authbus_issuer() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let fleet = directory.path().join("fleet");
    std::fs::create_dir(&fleet)?;
    let identity = crate::HostAuthorityRegisteredIdentity {
        agent_id: codex_hepta_contracts::AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?,
        spawn_generation: 1,
        fleet_root: fleet,
        workspace: directory.path().into(),
        resources: codex_hepta_fleet::ResourceBudget::local_default(),
    }
    .identity()?;
    let (_, bundle, _) = super::super::material::model(directory.path())?;
    let now = crate::authbus_ingress::now_ms()?;
    for input in [
        ObjectiveInputs::new(&identity, &bundle, now)?,
        ObjectiveInputs::successor(&identity, &bundle, now)?,
    ] {
        let profile = decode_admission_profile_json_v1(&serde_json::to_vec(&input.profile)?)?;
        let source =
            decode_source_envelope_json_v1(input.request.body.source_envelope_json.as_bytes())?;
        pretty_assertions::assert_eq!(
            profile.allowed_trusted_source_identities,
            vec![StableId::new(&input.request.issuer_id)?]
        );
        let mut context = ObjectiveAdmissionContextV1 {
            revision: Revision::new(input.request.body.objective_revision)?,
            now_unix_micros: now
                .checked_mul(1_000)
                .ok_or_else(|| anyhow::anyhow!("clock overflow"))?,
            selected_profile_digest: profile.digest()?,
            source_authentication: ObjectiveSourceAuthenticationV1::AuthorizedAdapter {
                source_identity: StableId::new(&input.request.issuer_id)?,
                source_digest: source.structured_intent.provenance.source_digest,
            },
        };
        let admitted = admit_and_compile_objective_v1(&source, &profile, &context)?;
        let compiled = admitted
            .compile_result
            .map_err(|error| anyhow::anyhow!("unexpected conflict: {error:?}"))?;
        pretty_assertions::assert_eq!(compiled.objective.semantic_digest, input.objective);
        context.source_authentication = ObjectiveSourceAuthenticationV1::AuthorizedAdapter {
            source_identity: StableId::new("circuit-objective-test-issuer")?,
            source_digest: source.structured_intent.provenance.source_digest,
        };
        assert!(matches!(
            admit_and_compile_objective_v1(&source, &profile, &context),
            Err(codex_hepta_objective::ObjectiveAdmissionError::SourceAuthenticationMismatch)
        ));
    }
    Ok(())
}
