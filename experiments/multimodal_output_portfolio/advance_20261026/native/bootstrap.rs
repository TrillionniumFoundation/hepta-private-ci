//! Bootstrap unchanged original AgentdNeuronOwner, with per-source stream identity.
use super::*;
impl Controller {
    pub(super) fn open(path: &str, expected: &str, root: &Path, resume: bool) -> Result<Self> {
        let raw = checked(path, expected)?;
        let spec: Spec = serde_json::from_slice(&raw)?;
        if spec.schema != "hepta.advance.semantic-owner.v1"
            || spec.max_native_ticks > 2864
            || spec.max_native_ticks < 2
            || !["dynamic", "fixed_initial", "fixed_late"].contains(&spec.policy.as_str())
        {
            return Err("Invalid new semantic-owner descriptor".into());
        }
        StableId::new(spec.stream_id.clone())?;
        StableId::new(spec.source_group_id.clone())?;
        let weights = checked(&spec.weights_path, &spec.pins.weights)?;
        let calibration = checked(&spec.calibration_path, &spec.pins.calibration)?;
        let verification: Value =
            serde_json::from_slice(&checked(&spec.verification_path, &spec.pins.verification)?)?;
        qualification::validate(&spec, &verification, &serde_json::from_slice(&calibration)?)?;
        let likelihood = checked(&spec.likelihood_path, &spec.likelihood_sha256)?;
        checked(&spec.observer_path, &spec.observer_sha256)?;
        let binary = Digest32::of_bytes(&std::fs::read(std::env::current_exe()?)?);
        let identity = json!({"descriptor":expected,"binary":binary.to_string(),"stream_id":spec.stream_id,
            "source_group_id":spec.source_group_id,"owner":"original AgentdNeuronOwner"});
        if resume {
            if serde_json::from_slice::<Value>(&std::fs::read(root.join("identity.json"))?)?
                != identity
            {
                return Err("Resume stream/model/binary identity mismatch".into());
            }
        } else {
            std::fs::create_dir(root)?;
            std::fs::write(
                root.join("identity.json"),
                serde_json::to_vec_pretty(&identity)?,
            )?;
        }
        let (mut native, mut config) = runtime_profile::configuration(&spec.pins, binary)?;
        native.width = 33;
        native.normalization_digest = Digest32::of_bytes(
            b"advance.semantic-confidence+known-context.v1;unscaled-correctness-residual",
        );
        config.config_id = StableId::new("advance.semantic-owner.config.v1")?;
        config.model_id =
            StableId::new("advance.actual-semantic-adapter-and-external-audio-bellman.v1")?;
        config.model_manifest_digest = Digest32::of_bytes(&raw);
        config.normalization_digest = native.normalization_digest;
        config.input_feature_dimension = control::WIDTH;
        config.state_width = 33;
        config.calibration.expires_after_sequence = spec.max_native_ticks;
        dynamics_profile::bind(
            &mut native,
            &mut config,
            dynamics_profile::DynamicsProfile::BoundedBalanced,
            dynamics_profile::DriveDomain::FutureEmittedState,
        )?;
        let baseline = measure::live_bytes();
        let kernel = control::Kernel::new(
            serde_json::from_slice(&weights)?,
            serde_json::from_slice(&calibration)?,
            serde_json::from_slice(&likelihood)?,
            spec.emit_cost,
            spec.acquire_cost,
        )?;
        let resident = measure::live_bytes() - baseline;
        let port = online_port::Control {
            config: config.clone(),
            kernel,
            measured_resident_heap_bytes: resident,
            forwards: 0,
            last_receipt: None,
            last_forecast: None,
            cached: None,
            numeric_modulation: spec.numeric_modulation,
        };
        let subject = StableId::new(spec.stream_id.clone())?;
        let scope = JournalScope {
            scope_digest: runtime_profile::subject_scope(&subject),
            objective_digest: expected.parse()?,
        };
        let mut history = history::History::open(&root.join("control.jsonl"), resume)?;
        let ndu_root = root.join("ndu");
        if !resume {
            std::fs::create_dir(&ndu_root)?;
        }
        let mut ndu = NduProjectionStoreV1::open(&ndu_root)?;
        let runtime = if resume {
            stream_io::recover(
                root,
                native,
                scope,
                config.clone(),
                history.native_sequence as usize,
            )?
        } else {
            let witness = FileAnchorWitnessStore::open(
                file(&root.join("neuron.witness"))?,
                scope,
                native.generation,
                4096,
            )?;
            NeuronRuntime::bootstrap(
                file(&root.join("neuron-0000.journal"))?,
                native,
                scope,
                SEGMENT,
                config.clone(),
                witness,
            )?
        };
        if runtime.current_anchor()?.map_or(0, |a| a.sequence) != history.native_sequence {
            return Err(
                "Native/controller frontier mismatch; explicit reconciliation required".into(),
            );
        }
        if !resume {
            let prior = plasticity_modulator_digest_v1(
                scope.objective_digest,
                scope.scope_digest,
                &[FixedQ32::from_raw(0)],
            )?;
            ndu.append_projection(
                NduProjectionKindV1::Utility,
                Digest32::of_bytes(b"registered-zero-not-observation"),
                scope.objective_digest,
                scope.scope_digest,
                prior,
            )?;
            ndu.select_projection(
                Digest32::of_bytes(b"select-registered-zero"),
                scope.objective_digest,
                scope.scope_digest,
                prior,
            )?;
            history.append(json!({"kind":"bootstrap","native_sequence":0,"monotonic_micros":0,"modulator":prior.to_string(),
                "utility_q32":0,"prior_is_observed_outcome":false,"stream_id":spec.stream_id,"source_group_id":spec.source_group_id}))?;
        }
        if ndu.selected_projection_digest(scope.objective_digest, scope.scope_digest)?
            != Some(history.modulator)
        {
            return Err("NDU/controller frontier mismatch".into());
        }
        let time_base = history.monotonic_micros;
        Ok(Self {
            owner: AgentdNeuronOwner::new(runtime, port),
            config,
            root: root.to_path_buf(),
            scope,
            subject,
            history,
            ndu,
            spec,
            started: Instant::now(),
            time_base,
            last_time: time_base,
            transition_started: false,
            process_peak: 0,
            tick_samples: Vec::new(),
        })
    }
}
