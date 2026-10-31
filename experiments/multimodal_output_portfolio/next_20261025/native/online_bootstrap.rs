//! Qualified bootstrap with unchanged original owner and native resource ceilings.
use super::*;

impl Controller {
    pub(super) fn open(spec_path: &str, expected: &str, root: &Path, resume: bool) -> Result<Self> {
        let raw = checked(spec_path, expected)?;
        let spec: Spec = serde_json::from_slice(&raw)?;
        if spec.schema != "hepta.next.native-ndu-online.v1"
            || !["ndu", "correctness"].contains(&spec.selection.as_str())
            || spec.max_native_ticks > 2864
            || spec.max_native_ticks < 2
            || !spec.registration.is_object()
        {
            return Err("Invalid online registration".into());
        }
        let weights = checked(&spec.weights_path, &spec.pins.weights)?;
        let calibration = checked(&spec.calibration_path, &spec.pins.calibration)?;
        let predictor = checked(&spec.predictor_path, &spec.predictor_sha256)?;
        let verification: Value =
            serde_json::from_slice(&checked(&spec.verification_path, &spec.pins.verification)?)?;
        checked(&spec.observer_path, &spec.observer_sha256)?;
        if verification["study_qualified"] != true
            || verification["native_measured_ece_ppm"].as_u64()
                != Some(u64::from(spec.pins.measured_ece_ppm))
            || verification["native_measured_false_acceptance_ppm"].as_u64()
                != Some(u64::from(spec.pins.measured_false_acceptance_ppm))
            || verification["gates"]
                .as_object()
                .is_none_or(|g| g.len() != 4 || g.values().any(|v| v != true))
        {
            return Err("Frozen complete study qualification rejected".into());
        }
        let bundled: Value = serde_json::from_slice(&weights)?;
        let predictor_json: Value = serde_json::from_slice(&predictor)?;
        let calibration_json: Value = serde_json::from_slice(&calibration)?;
        if verification["calibration_sha256"] != spec.pins.calibration
            || calibration_json["predictor_sha256"] != spec.predictor_sha256
            || bundled["admission"]["predictor"]["weight"] != predictor_json["weight"]
            || bundled["admission"]["predictor"]["bias"] != predictor_json["bias"]
            || bundled["admission"]["cuts"] != calibration_json["cuts"]
            || bundled["admission"]["probabilities"] != calibration_json["probabilities"]
            || bundled["admission"]["absent_probability"] != calibration_json["absent_probability"]
        {
            return Err("Qualified model/calibrator does not match actual native layers".into());
        }
        let binary = Digest32::of_bytes(&std::fs::read(std::env::current_exe()?)?);
        let identity = json!({"descriptor": expected, "binary": binary.to_string(), "owner": "original AgentdNeuronOwner"});
        if resume {
            if serde_json::from_slice::<Value>(&std::fs::read(root.join("identity.json"))?)?
                != identity
            {
                return Err("Resume descriptor or executable identity mismatch".into());
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
            b"next.preaction.correctness-carrier.v1;zeros-not-latent-forecasts;moments-separate",
        );
        config.config_id = StableId::new("next.online.ndu-forecast-carrier.v1")?;
        config.model_id = StableId::new("next.qualified-five-action-and-moment-head.v1")?;
        config.model_manifest_digest = Digest32::of_bytes(&raw);
        config.normalization_digest = native.normalization_digest;
        config.input_feature_dimension = 511;

        config.state_width = 33;
        config.calibration.expires_after_sequence = spec.max_native_ticks;
        dynamics_profile::bind(
            &mut native,
            &mut config,
            dynamics_profile::DynamicsProfile::BoundedBalanced,
            dynamics_profile::DriveDomain::FutureEmittedState,
        )?;
        let baseline = measure::live_bytes();
        let values = serde_json::from_slice(&weights)?;
        let resident = measure::live_bytes() - baseline;
        let control = online_port::Control {
            config: config.clone(),
            measured_resident_heap_bytes: resident,
            values,
            forwards: 0,
            last_receipt: None,
            last_moments: None,
            last_raw_probabilities: None,
        };
        let subject = StableId::new("next.online.research-subject")?;
        let scope = JournalScope {
            scope_digest: runtime_profile::subject_scope(&subject),
            objective_digest: expected.parse()?,
        };
        let mut history = online_log::History::open(&root.join("control.jsonl"), resume)?;
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
            return Err("Native/controller frontier mismatch; reconciliation required".into());
        }
        if !resume {
            let prior = plasticity_modulator_digest_v1(
                scope.objective_digest,
                scope.scope_digest,
                &[FixedQ32::from_raw(0)],
            )?;
            ndu.append_projection(
                NduProjectionKindV1::Utility,
                Digest32::of_bytes(b"registered-zero-prior-not-outcome"),
                scope.objective_digest,
                scope.scope_digest,
                prior,
            )?;
            ndu.select_projection(
                Digest32::of_bytes(b"select-registered-zero-prior"),
                scope.objective_digest,
                scope.scope_digest,
                prior,
            )?;
            history.append(json!({"kind": "bootstrap", "native_sequence": 0,
                "monotonic_micros": 0, "modulator": prior.to_string(), "prior_is_observed_outcome": false}))?;
        }
        if ndu.selected_projection_digest(scope.objective_digest, scope.scope_digest)?
            != Some(history.modulator)
        {
            return Err("NDU/controller frontier mismatch; reconciliation required".into());
        }
        let time_base = history.monotonic_micros;
        Ok(Self {
            owner: AgentdNeuronOwner::new(runtime, control),
            config,
            root: root.to_path_buf(),
            scope,
            subject,
            history,
            ndu,
            observer: spec.observer_sha256,
            maximum: spec.max_native_ticks,
            started: Instant::now(),
            time_base,
            last_time: time_base,
            process_ticks: 0,
            process_peak: 0,
            tick_samples: Vec::new(),
            transition_started: false,
            selection: spec.selection,
        })
    }
}
