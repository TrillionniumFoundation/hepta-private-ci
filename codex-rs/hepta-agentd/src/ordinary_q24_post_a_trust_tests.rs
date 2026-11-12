//! Explicit administrator-signed current-recipient inputs. These bytes do not
//! create a historical receipt, activated runtime capsule or completed stage.

use std::collections::BTreeMap;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_learning_artifacts::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;

use super::RetainedOriginalAPhase;
use super::observer::read_private;
use super::recovery::OriginalSuccessorAdministration;
use super::root::write_bytes;
use super::root::write_json;
use crate::root_initial_learning_trust_data::*;

pub(super) const TRAINER: &str = "ordinary-trainer";
pub(super) const FREEZER: &str = "ordinary-freeze-evaluator";
pub(super) const B_EVALUATOR: &str = "ordinary-independent-b-evaluator";
pub(super) const B_OBSERVER: &str = "ordinary-independent-b-observer";

pub(super) struct OriginalPostATrust {
    pub(super) payload: LearningTrustPayloadV1,
    pub(super) payload_file: PathBuf,
    pub(super) keys: BTreeMap<String, PathBuf>,
    pub(super) trust_digest: Digest32,
    pub(super) freezer: LearningTrustRoleSelectionV1,
}

impl OriginalPostATrust {
    pub(super) fn prepare(original: &RetainedOriginalAPhase, data: &Path) -> anyhow::Result<Self> {
        let mut payload: LearningTrustPayloadV1 =
            serde_json::from_slice(&read_private(&original.plan.observer_payload, 16 * 1024)?)?;
        let now = crate::authbus_ingress::now_ms()? / 1_000;
        payload.activate_pinned_genesis(now)?;
        anyhow::ensure!(
            payload.root.verifying_key
                == SigningKey::from_bytes(&[71; 32]).verifying_key().to_bytes(),
            "same initially provisioned learning Root key"
        );
        // Keep the initially provisioned Root, scope, objective and its expiry.
        // This is the separate fixed recipient distribution, not a recovered
        // old activation or a rotation inferred from an absent previous value.
        payload.distribution.distribution_id = "ordinary-current-recipient-genesis".into();
        payload.distribution.effective_at_seconds = now;
        payload.distribution.issued_at_seconds = now;
        payload.distribution.signers.clear();
        let mut keys = BTreeMap::new();
        for (name, seed, role, held_by_root) in [
            (TRAINER, 74, LearningTrustRoleV1::Generator, false),
            (
                "ordinary-experience-observer",
                75,
                LearningTrustRoleV1::Observer,
                false,
            ),
            (
                "ordinary-dataset-observer",
                76,
                LearningTrustRoleV1::Observer,
                false,
            ),
            (
                "ordinary-local-selector",
                77,
                LearningTrustRoleV1::Selector,
                false,
            ),
            (
                "ordinary-next-use-observer",
                78,
                LearningTrustRoleV1::Observer,
                false,
            ),
            (FREEZER, 79, LearningTrustRoleV1::Evaluator, false),
            (B_EVALUATOR, 80, LearningTrustRoleV1::Evaluator, true),
            (B_OBSERVER, 81, LearningTrustRoleV1::Observer, true),
        ] {
            let key = SigningKey::from_bytes(&[seed; 32]);
            let public = key.verifying_key().to_bytes();
            payload
                .distribution
                .signers
                .push(LearningTrustSignerDataV1 {
                    principal_id: name.into(),
                    credential_chain_digest: Digest32::of_parts(&[
                        b"ordinary.original.root.provisioned-role.v1\0",
                        name.as_bytes(),
                        &public,
                    ])
                    .into_array(),
                    signing_key_digest: Digest32::of_bytes(&public).into_array(),
                    scope_digest: payload.distribution.scope_digest,
                    authority_epoch: payload.distribution.authority_epoch,
                    authenticated_at_seconds: now,
                    expires_at_seconds: payload.distribution.expires_at_seconds,
                    controller_id: format!("{name}-controller"),
                    verifying_key: public,
                    roles: vec![role],
                    revoked_at_seconds: None,
                });
            let path = if held_by_root {
                original.plan.protected.path()
            } else {
                data
            }
            .join(format!("{name}.key"));
            write_bytes(&path, &key.to_bytes())?;
            if !held_by_root {
                super::super::owned_mode(&path, 60001, 60001, 0o600)?;
            }
            keys.insert(name.into(), path);
        }
        payload.generator = role(TRAINER);
        payload.observer = role(B_OBSERVER);
        crate::root_initial_learning_trust_data::tests::sign(&mut payload)
            .map_err(|error| anyhow::anyhow!("original Root recipient signature: {error}"))?;
        let (trust, _, _) = payload.activate_pinned_genesis(now)?;
        let payload_file = original
            .plan
            .protected
            .path()
            .join("post-a-signed-trust.json");
        write_json(&payload_file, &payload)?;
        Ok(Self {
            payload,
            payload_file,
            keys,
            trust_digest: trust.verifier().trust_digest(),
            freezer: role(FREEZER),
        })
    }

    pub(super) fn key(&self, name: &str) -> anyhow::Result<&Path> {
        self.keys
            .get(name)
            .map(PathBuf::as_path)
            .ok_or_else(|| anyhow::anyhow!("original configured role is absent: {name}"))
    }

    pub(super) fn original_profile(
        &self,
        original: &RetainedOriginalAPhase,
        successor: &OriginalSuccessorAdministration,
        evaluation_profile: Digest32,
    ) -> anyhow::Result<crate::HostAuthorityLearningProfileV1> {
        let source = crate::OriginalSingleQ24SourceConfigurationV1::from_original_deployment_bytes(
            &read_private(&original.plan.root.source, 65_536)?,
            &original.plan.identity,
        )?;
        let (_, bundle, _) =
            super::super::material::load(&original.plan.runtime.path().join("model"))?;
        let initial: serde_json::Value =
            serde_json::from_slice(&read_private(&original.plan.root.initial, 65_536)?)?;
        let selected: crate::authority_host_runtime::publication_data::SelectionData =
            serde_json::from_value(initial["selection"].clone())?;
        let now = crate::authbus_ingress::now_ms()? / 1_000;
        let owners = LearningIterationOwnersV1 {
            evidence_trust_digest: self.trust_digest,
            experience: StableId::new("ordinary-experience-observer")?,
            dataset: StableId::new("ordinary-dataset-observer")?,
            trainer: StableId::new(TRAINER)?,
            evaluator: StableId::new(B_EVALUATOR)?,
            proposal: StableId::new("ordinary-root-model-proposal")?,
            selector: StableId::new("ordinary-local-selector")?,
            next_use_observer: StableId::new("ordinary-next-use-observer")?,
        };
        let request = LearningIterationRequestV1 {
            operation_id: StableId::new("ordinary-original-post-a-learning")?,
            principal_id: StableId::new(source.source.scope.principal_digest.to_string())?,
            agent_id: source.source.scope.agent_id.clone(),
            cell_id: source.source.scope.cell_id.clone(),
            source_run_id: source.source.scope.run_id,
            completed_task_receipt: original.outcome.observed.source_history_digest.parse()?,
            selected_artifact_digest: Digest32::from_array(selected.content_digest),
            evaluation_profile,
            selected_bundle: bundle,
            envelope: IterationEnvelopeV1 {
                envelope_id: StableId::new("ordinary-post-a-original-envelope")?,
                base_commit: original_build_pin("HEPTA_ORDINARY_SOURCE_COMMIT")?,
                base_tree: original_build_pin("HEPTA_ORDINARY_SOURCE_TREE")?,
                objective_digest: original.plan.objective.objective,
                grammar_digest: Digest32::of_bytes(b"ordinary-original-finite-q24-grammar"),
                maximum_files: 4,
                maximum_diff_bytes: 65_536,
                maximum_candidates: 1,
                maximum_parallel_sandboxes: 1,
                expiry_unix_seconds: now
                    .checked_add(240)
                    .ok_or_else(|| anyhow::anyhow!("original envelope expiry overflow"))?,
            },
            budget: LearningIterationBudgetV1 {
                maximum_dataset_rows: 8,
                maximum_dataset_bytes: 65_536,
                maximum_training_steps: 8,
                maximum_training_milliseconds: 2_000,
                maximum_artifact_bytes: 1_048_576,
            },
        };
        let proof: Digest32 = successor.writer_proof.sha256()?.as_str().parse()?;
        let profile = crate::HostAuthorityLearningProfileV1::new(
            &successor.identity,
            proof.into_array(),
            request,
            owners,
        )?;
        let initial = profile.original_initial_data()?;
        crate::root_historical_learning_trust_data::HistoricalLearningTrustPayloadV1 {
            signed: self.payload.clone(),
            freeze_evaluator: self.freezer.clone(),
        }
        .activate_for_recipient(&initial, now)?;
        Ok(profile)
    }
}

fn role(name: &str) -> LearningTrustRoleSelectionV1 {
    LearningTrustRoleSelectionV1 {
        principal_id: name.into(),
        controller_id: format!("{name}-controller"),
    }
}

fn original_build_pin(name: &str) -> anyhow::Result<Digest32> {
    let value = std::env::var(name)?;
    anyhow::ensure!(
        value.len() == 40
            && value
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)),
        "exact qualified Git source identity required: {name}"
    );
    Ok(Digest32::of_bytes(value.as_bytes()))
}
