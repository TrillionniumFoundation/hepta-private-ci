//! Only the actual canonical neural stage asks the protected fixed encoder for
//! a Root-frozen public pair. It does not supply raw text, URLs or model names.
use super::*;
use codex_hepta_agent_components::intelligence::CanonicalPortInputV1;
use codex_hepta_agent_components::learning_ledger::RunStartRecordV1;
use codex_hepta_agentd::*;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_neuron::canonical_feature_vector_digest_v1;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::net::UnixStream;
use std::path::PathBuf;
use std::time::Duration;
use std::time::Instant;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Configuration {
    schema: String,
    encoder_socket: PathBuf,
    encoder_configuration: Source,
    pair_id: String,
    source_row_sha256: String,
    objective_digest: String,
    runtime_body_digest: String,
    model_generation: u64,
    normalization_digest: String,
    tokenizer_digest: String,
    timeout_ms: u64,
}

pub(super) struct TickProvider {
    source: Source,
    configuration: Configuration,
    goal_mode: GoalMode,
}

#[derive(Clone, Copy, PartialEq)]
pub(super) enum GoalMode {
    FixedObjective,
    ActualCompiledGoal,
}

impl TickProvider {
    pub(super) fn open_mode(
        source: Source,
        plan: &crate::CpuNeuronGenerationPlanV1,
        goal_mode: GoalMode,
    ) -> HostResult<Self> {
        let configuration: Configuration = serde_json::from_slice(&source.read(16 * 1024)?)?;
        let schema = match goal_mode {
            GoalMode::FixedObjective => "hepta.cpu-neuron.fixed-pair-tick-provider.v2",
            GoalMode::ActualCompiledGoal => "hepta.cpu-neuron.fixed-pair-tick-provider.v3",
        };
        if configuration.schema != schema
            || configuration.pair_id.is_empty()
            || configuration.pair_id.len() > 256
            || digest(&configuration.objective_digest)? != plan.scope.objective_digest
            || digest(&configuration.runtime_body_digest)? != plan.body.semantic_digest()?
            || configuration.model_generation != plan.runtime.generation.get()
            || digest(&configuration.normalization_digest)? != plan.runtime.normalization_digest
            || digest(&configuration.tokenizer_digest)? != plan.runtime.tokenizer_digest
            || !(1..=60_000).contains(&configuration.timeout_ms)
        {
            return Err("fixed physical tick provider differs from the actual plan".into());
        }
        digest(&configuration.source_row_sha256)?;
        configuration.encoder_configuration.read(2 * 1024 * 1024)?;
        Ok(Self {
            source,
            configuration,
            goal_mode,
        })
    }

    fn exchange(&self, request: &Value) -> HostResult<Value> {
        let cfg = &self.configuration;
        self.source.read(16 * 1024)?;
        cfg.encoder_configuration.read(2 * 1024 * 1024)?;
        for path in cfg.encoder_socket.ancestors().skip(1) {
            let meta = std::fs::symlink_metadata(path)?;
            if path.canonicalize()? != path
                || meta.uid() != 0
                || meta.mode() & 0o022 != 0
                || !meta.is_dir()
            {
                return Err("mutable Root encoder socket ancestor".into());
            }
        }
        use std::os::unix::fs::FileTypeExt;
        let before = std::fs::symlink_metadata(&cfg.encoder_socket)?;
        if !before.file_type().is_socket() || before.uid() != 0 || before.mode() & 0o007 != 0 {
            return Err("protected Root encoder socket required".into());
        }
        let deadline = Instant::now()
            .checked_add(Duration::from_millis(cfg.timeout_ms))
            .ok_or("fixed physical encoding deadline overflow")?;
        let socket = rustix::net::socket_with(
            rustix::net::AddressFamily::UNIX,
            rustix::net::SocketType::STREAM,
            rustix::net::SocketFlags::NONBLOCK | rustix::net::SocketFlags::CLOEXEC,
            /*protocol*/ None,
        )?;
        rustix::net::connect(
            &socket,
            &rustix::net::SocketAddrUnix::new(&cfg.encoder_socket)?,
        )?;
        let peer = rustix::net::sockopt::socket_peercred(&socket)?;
        if peer.uid.as_raw() != 0 {
            return Err("fixed encoder kernel peer is not Root".into());
        }
        let mut stream = UnixStream::from(socket);
        stream.set_nonblocking(false)?;
        let mut body = serde_json::to_vec(request)?;
        body.push(b'\n');
        if body.len() > 16 * 1024 {
            return Err("fixed encoding request budget".into());
        }
        let mut remaining_body = body.as_slice();
        while !remaining_body.is_empty() {
            stream.set_write_timeout(Some(remaining(deadline)?))?;
            match stream.write(remaining_body) {
                Ok(0) => return Err("fixed encoder closed request".into()),
                Ok(count) => remaining_body = &remaining_body[count..],
                Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
                Err(error) => return Err(error.into()),
            }
        }
        let mut response = Vec::new();
        loop {
            let mut block = [0_u8; 4096];
            stream.set_read_timeout(Some(remaining(deadline)?))?;
            let count = match stream.read(&mut block) {
                Ok(count) => count,
                Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
                Err(error) => return Err(error.into()),
            };
            if count == 0 || response.len() + count > 64 * 1024 {
                return Err("fixed encoding response budget".into());
            }
            response.extend_from_slice(&block[..count]);
            if response.contains(&b'\n') {
                break;
            }
        }
        if response.last() != Some(&b'\n')
            || response.iter().filter(|&&byte| byte == b'\n').count() != 1
        {
            return Err("single fixed encoding response frame required".into());
        }
        let after = std::fs::symlink_metadata(&cfg.encoder_socket)?;
        if before.dev() != after.dev()
            || before.ino() != after.ino()
            || before.mode() != after.mode()
            || rustix::net::sockopt::socket_peercred(&stream)? != peer
        {
            return Err("Root encoding transport changed".into());
        }
        self.source.read(16 * 1024)?;
        cfg.encoder_configuration.read(2 * 1024 * 1024)?;
        remaining(deadline)?;
        Ok(serde_json::from_slice(&response)?)
    }
}

impl AgentdNeuronTickProviderV2 for TickProvider {
    fn build_tick(
        &self,
        _: &AgentdIdentity,
        _: &RunStartRecordV1,
        _: &AgentdIntelligenceInvocationV1,
    ) -> Result<NeuronTickInputV1, AgentdError> {
        Err(AgentdError::Invalid(
            "physical input requires the actual late canonical neural stage".into(),
        ))
    }
    fn build_tick_for_stage(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        invocation: &AgentdIntelligenceInvocationV1,
        stage: &CanonicalPortInputV1,
        current: (Generation, Option<JournalAnchor>),
    ) -> Result<NeuronTickInputV1, AgentdError> {
        let run = || -> HostResult<NeuronTickInputV1> {
            let cfg = &self.configuration;
            if current.0.get() != cfg.model_generation
                || stage.run_id != record.snapshot.run_id
                || (self.goal_mode == GoalMode::FixedObjective
                    && stage.objective_digest != digest(&cfg.objective_digest)?)
                || stage.snapshot_digest != invocation.request.snapshot.digest()
                || record.runtime_body_digest != digest(&cfg.runtime_body_digest)?
                || stage.predecessor_digest.is_zero()
            {
                return Err("actual neural stage differs from fixed source/body".into());
            }
            let request = serde_json::json!({
                "pair_id":cfg.pair_id, "source_row_sha256":cfg.source_row_sha256,
                "body_digest":cfg.runtime_body_digest, "objective_digest":stage.objective_digest.to_string(),
                "model_generation":cfg.model_generation, "run_id":stage.run_id.to_string(),
                "ndu_digest":stage.predecessor_digest.to_string(),
            });
            let response = self.exchange(&request)?;
            let expected_tuple = request
                .as_object()
                .ok_or("request tuple")?
                .iter()
                .filter(|(key, _)| key.as_str() != "pair_id" && key.as_str() != "source_row_sha256")
                .map(|(key, value)| (key.clone(), value.clone()))
                .collect::<serde_json::Map<_, _>>();
            if response["schema"] != "hepta.fixed-nomic-encoded-pair.v1"
                || response["encoder_config_sha256"] != cfg.encoder_configuration.digest
                || response["pair_id"] != cfg.pair_id
                || response["source_row_sha256"] != cfg.source_row_sha256
                || response["normalization_sha256"] != cfg.normalization_digest
                || response["tokenizer_sha256"] != cfg.tokenizer_digest
                || response["run_tuple"] != Value::Object(expected_tuple)
                || response["physical_elapsed_micros"].as_u64().unwrap_or(0) == 0
            {
                return Err("original fixed physical encoding response binding".into());
            }
            let features: Vec<i64> = serde_json::from_value(response["features_q24"].clone())?;
            if features.len() != 512
                || features.iter().all(|&value| value == 0)
                || features
                    .iter()
                    .any(|value| !(-(1_i64 << 24)..=(1_i64 << 24)).contains(value))
            {
                return Err("actual centered 768-to-512 Q24 feature shape".into());
            }
            Ok(NeuronTickInputV1 {
                tick_id: stage.run_id.clone(),
                subject_id: id(identity.agent_id.as_str())?,
                logical_sequence: current.1.map_or(Ok(1), |anchor| {
                    anchor.sequence.checked_add(1).ok_or("sequence overflow")
                })?,
                monotonic_time_micros: now_ms()?.checked_mul(1000).ok_or("tick clock overflow")?,
                checkpoint_digest: current
                    .1
                    .map_or(Digest32::ZERO, |anchor| anchor.checkpoint_digest),
                input_feature_digest: canonical_feature_vector_digest_v1(&features),
                feature_vector_q24: features,
                objective_digest: stage.objective_digest,
                ndu_snapshot_digest: stage.predecessor_digest,
                body_generation: Some(current.0.get()),
                modulator_digest: None,
            })
        };
        run().map_err(|error| {
            AgentdError::Invalid(format!("fixed physical CPU input unavailable: {error}"))
        })
    }
}

fn remaining(deadline: Instant) -> HostResult<Duration> {
    deadline
        .checked_duration_since(Instant::now())
        .filter(|duration| !duration.is_zero())
        .ok_or_else(|| "fixed physical encoding total deadline elapsed".into())
}

#[cfg(test)]
#[path = "initial_cpu_tick_tests.rs"]
mod tests;
