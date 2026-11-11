//! Real loaded Q24 material with synthetic learning-role receipts and fixture
//! CURRENT/FinalUse files. Only the pure, production-used publication preflight
//! runs here; these cases do not publish or claim an ordinary C execution.

use codex_hepta_neuron::CellCandidateMaskV1;
use codex_hepta_neuron::CellScopeV1;
use pretty_assertions::assert_eq;

use super::*;

struct Preflight {
    files: Fixture,
    model: Arc<LoadedCellQ24ModelV1>,
    decision: Decision,
    target: AgentdGenerationUpdateTargetV1<FileAnchorWitnessStore>,
    definition: CellDefinitionV1,
    source: CircuitTaskSourceInputV1,
}

impl Preflight {
    fn new() -> anyhow::Result<Self> {
        let model = Arc::new(model(/*output_width*/ 5)?);
        let mut bundle = learning_test_baseline()?;
        bundle.components = model.components().clone();
        let mut definition = crate::circuit_cell::tests::support::definition();
        let c = model.components();
        definition.bundle_digest = bundle.digest()?;
        definition.state_schema_digest = c.state_schema;
        definition.native.model_digest = c.heads;
        definition.native.normalization_digest = c.normalizer;
        definition.native.generation = bundle.generation;
        definition.runtime.generation = bundle.generation;
        definition.runtime.model_id = bundle.artifact_id.clone();
        definition.runtime.model_manifest_digest = bundle.digest()?;
        definition.runtime.encoder_digest = c.encoder;
        definition.runtime.head_digest = c.heads;
        definition.runtime.weights_digest = model.effective_weights_digest();
        definition.runtime.tokenizer_digest = c.tokenizer;
        definition.runtime.preprocessor_digest = c.normalizer;
        definition.runtime.normalization_digest = c.normalizer;
        definition.runtime.quantization_digest = c.numeric_profile;
        definition.runtime.runtime_digest = crate::CellQ24FeatureWorkerV1::runtime_profile_digest();
        definition.runtime.native_config_digest = definition.native.digest()?;
        definition.runtime.input_feature_dimension = model.input_width();
        definition.runtime.calibration.generation = bundle.generation;
        definition.semantic_digest()?;

        let mut old = config()?;
        old.manifest.bundle_digest = bundle.digest()?.into_array();
        old.initial.manifest_digest = old.manifest.digest()?;
        let scope = &old.initial.scope;
        let mut observation = b"HQ24I001".to_vec();
        observation.extend(1_u16.to_le_bytes());
        observation.extend((1_i64 << 22).to_le_bytes());
        let source = CircuitTaskSourceInputV1 {
            scope: CellScopeV1 {
                principal_digest: Digest32::from_array(scope.principal_digest),
                agent_id: StableId::new(&scope.agent_id)?,
                cell_id: StableId::new(&scope.cell_id)?,
                run_id: StableId::new("ordinary-C-preflight-fixture")?,
            },
            source_frontier: digest("original-C-source"),
            objective_digest: digest("original-C-objective"),
            ndu_snapshot_digest: digest("original-C-ndu"),
            monotonic_micros: 10,
            deadline_micros: 100,
            observation,
            candidates: definition
                .candidates
                .iter()
                .map(|candidate| CellCandidateMaskV1 {
                    candidate_id: candidate.candidate_id.clone(),
                    allowed: true,
                })
                .collect(),
            lease_duration_ms: 1,
        };
        let mut next = old.clone();
        let m = &mut next.manifest;
        m.profile = crate::CellQ24GenerationWorkerV1::PROFILE.into();
        m.encoder = Some(c.encoder.into_array());
        m.head = Some(c.heads.into_array());
        m.input_schema = crate::CellQ24GenerationWorkerV1::input_schema_digest();
        m.state_schema = c.state_schema.into_array();
        m.output_schema = c.output_schema.into_array();
        m.runtime_digest = definition.runtime.runtime_digest.into_array();
        m.device_digest = definition.runtime.device_digest.into_array();
        m.learning = CellLearningBindingV2::Frozen {
            weights: model.effective_weights_digest().into_array(),
        };
        m.max_input_bytes = 18;
        m.max_state_bytes = 1;
        m.max_delta_bytes = 90;
        m.max_prefix_bytes = 90;
        next.initial.manifest_digest = m.digest()?;
        next.initial.scope.run_id = source.scope.run_id.to_string();
        next.initial.generation += 1;
        next.initial.writer_epoch += 1;
        next.initial.state.clear();
        next.source_frontier = source.source_frontier.into_array();
        next.task_digest =
            crate::circuit_feature_task_digest_v1(&definition, &source)?.into_array();
        let files = Fixture::new_with_target(old, next)?;
        let decision = Decision::new(
            learning_test_decision(&files, bundle, "none")?
                .snapshot()
                .clone(),
        )?;
        let target = files.target_create()?;
        Ok(Self {
            files,
            model,
            decision,
            target,
            definition,
            source,
        })
    }

    fn validate(&self) -> Result<(), Error> {
        validation::feature_target(
            &self.decision,
            &self.target,
            &self.definition,
            &self.source,
            &self.model,
        )
    }

    fn rehash(&mut self) -> anyhow::Result<()> {
        // Rebind all public hashes so rejection cannot be an old task digest.
        self.target.config.task_digest =
            crate::circuit_feature_task_digest_v1(&self.definition, &self.source)?.into_array();
        self.target.config.initial.manifest_digest = self.target.config.manifest.digest()?;
        Ok(())
    }

    fn bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        [
            "current.json",
            "final-use-frontier.json",
            "target-journal",
            "target-witness",
        ]
        .iter()
        .map(|name| self.files.bytes(name))
        .collect()
    }
}

#[test]
fn prepublication_rejects_actual_model_and_worker_mismatch_with_rehashed_tasks()
-> anyhow::Result<()> {
    let mut p = Preflight::new()?;
    p.validate()?;
    let original = p.definition.clone();
    let manifest = p.target.config.manifest.clone();
    let bytes = p.bytes()?;
    for field in ["weights", "runtime", "input-width", "state-width"] {
        p.definition = original.clone();
        p.target.config.manifest = manifest.clone();
        match field {
            "weights" => p.definition.runtime.weights_digest = digest("different-weights"),
            "runtime" => {
                p.definition.runtime.runtime_digest = digest("unsupported-runtime");
                p.target.config.manifest.runtime_digest =
                    p.definition.runtime.runtime_digest.into_array();
            }
            "input-width" => p.definition.runtime.input_feature_dimension += 1,
            "state-width" => {
                p.definition.native.width += 1;
                p.definition.runtime.state_width += 1;
                p.definition.runtime.native_config_digest = p.definition.native.digest()?;
            }
            _ => unreachable!(),
        }
        p.rehash()?;
        assert!(
            matches!(
                p.validate(),
                Err(Error::Binding("C loaded model or worker definition"))
            ),
            "{field}"
        );
        assert_eq!(p.bytes()?, bytes);
    }
    p.definition = original;
    p.target.config.manifest = manifest;
    p.model = Arc::new(model(/*output_width*/ 6)?);
    p.rehash()?;
    assert!(matches!(
        p.validate(),
        Err(Error::Binding("C loaded model or worker definition"))
    ));
    assert_eq!(p.bytes()?, bytes);
    Ok(())
}

#[test]
fn prepublication_pins_worker_runtime_and_device_to_full_selected_manifest() -> anyhow::Result<()> {
    let mut p = Preflight::new()?;
    p.validate()?;
    let original = p.definition.clone();
    let bytes = p.bytes()?;
    for field in ["runtime", "device"] {
        p.definition = original.clone();
        match field {
            "runtime" => p.definition.runtime.runtime_digest = digest("other-runtime"),
            "device" => p.definition.runtime.device_digest = digest("other-device"),
            _ => unreachable!(),
        }
        p.rehash()?;
        assert!(
            matches!(
                p.validate(),
                Err(Error::Binding("C runtime differs from selected manifest"))
            ),
            "{field}"
        );
        assert_eq!(p.bytes()?, bytes);
    }
    Ok(())
}

#[test]
fn prepublication_rejects_candidate_mask_truncation_injection_and_reordering() -> anyhow::Result<()>
{
    let mut p = Preflight::new()?;
    p.validate()?;
    let original = p.source.clone();
    assert!(original.candidates.len() >= 2);
    let bytes = p.bytes()?;
    for field in ["missing", "extra", "reordered", "relabeled"] {
        p.source = original.clone();
        match field {
            "missing" => {
                p.source.candidates.pop();
            }
            "extra" => p.source.candidates.push(original.candidates[0].clone()),
            "reordered" => p.source.candidates.swap(0, 1),
            "relabeled" => {
                p.source.candidates[0].candidate_id = StableId::new("unrecognized-q24-candidate")?;
            }
            _ => unreachable!(),
        }
        // Full task-ingress binding already rejects malformed masks. The
        // late, directly callable worker preflight must reject independently.
        assert!(
            crate::circuit_feature_task_digest_v1(&p.definition, &p.source).is_err(),
            "{field}"
        );
        assert!(
            matches!(
                validation::require_executable_feature(
                    &p.decision.bundle,
                    &p.target.config.manifest,
                    &p.model,
                    &p.definition,
                    &p.source,
                ),
                Err(Error::Binding("C candidate mask differs from definition"))
            ),
            "{field}"
        );
        assert_eq!(p.bytes()?, bytes);
    }
    Ok(())
}

#[test]
fn prepublication_decodes_exact_input_and_rejects_static_cell_input_failures() -> anyhow::Result<()>
{
    let mut p = Preflight::new()?;
    p.validate()?;
    let original = p.source.clone();
    let definition = p.definition.clone();
    let bytes = p.bytes()?;
    for field in ["width", "trailing", "range", "capacity", "abstain"] {
        p.source = original.clone();
        p.definition = definition.clone();
        match field {
            "width" => {
                p.source.observation[8..10].copy_from_slice(&2_u16.to_le_bytes());
                p.source.observation.extend(0_i64.to_le_bytes());
            }
            "trailing" => p.source.observation.push(0),
            "range" => {
                p.source.observation[10..18].copy_from_slice(&(8 * (1_i64 << 24) + 1).to_le_bytes())
            }
            "capacity" => p.definition.max_input_bytes = p.source.observation.len() - 1,
            "abstain" => p.source.candidates.last_mut().unwrap().allowed = false,
            _ => unreachable!(),
        }
        p.rehash()?;
        let expected = if matches!(field, "capacity" | "abstain") {
            "C ordinary input capacity or abstention"
        } else {
            "C canonical Q24 input"
        };
        assert!(
            matches!(p.validate(), Err(Error::Binding(actual)) if actual == expected),
            "{field}"
        );
        assert_eq!(p.bytes()?, bytes);
    }
    Ok(())
}
