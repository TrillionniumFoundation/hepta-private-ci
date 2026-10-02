//! The closed, public measurement route. The actual G MainPID connects itself;
//! no numeric child, arbitrary text, old Goal grant or caller clock is accepted.
use codex_hepta_learning_ledger::read_root_review_input;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::FileTypeExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::net::UnixStream;
use std::path::PathBuf;
use std::time::Duration;
use std::time::Instant;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
pub(super) const PURPOSE: &str = "PublicDevelopmentMeasurementOnlyV1";
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Source {
    pub(super) path: PathBuf,
    pub(super) digest: String,
}
impl Source {
    pub(super) fn read(&self, maximum: u64) -> Result<Vec<u8>> {
        let bytes = read_root_review_input(&self.path, maximum)?;
        if Digest32::of_bytes(&bytes) != self.digest.parse::<Digest32>()? {
            return Err("original protected paired source changed".into());
        }
        Ok(bytes)
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Encoder {
    socket: PathBuf,
    config: Source,
    normalization: String,
    tokenizer: String,
    weights: String,
    manifest: String,
}
#[derive(Deserialize, Serialize, Clone, Debug, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
struct Accounting {
    unit: String,
    pid: u32,
    start_ticks: u64,
    uid: u32,
    cgroup: String,
    cpu_usage_usec: u64,
    memory_current_bytes: u64,
    memory_peak_bytes: u64,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Cost {
    accounting: String,
    producer_before: Accounting,
    producer_after: Accounting,
    services_before: Vec<Accounting>,
    services_after: Vec<Accounting>,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Response {
    schema: String,
    purpose: String,
    batch_id: String,
    pair_id: String,
    source_row_sha256: String,
    encoder_config_sha256: String,
    normalization_sha256: String,
    tokenizer_sha256: String,
    weights_sha256: String,
    encoder_manifest_sha256: String,
    physical_elapsed_micros: u64,
    measurement_elapsed_micros: u64,
    pub(super) features_q24: Vec<i64>,
    cost_context: Cost,
}
fn lifetime(before: &Accounting, after: &Accounting) -> Result<()> {
    if before.unit.is_empty()
        || before.pid == 0
        || before.start_ticks == 0
        || !before.cgroup.starts_with("/system.slice/")
        || (
            before.unit.as_str(),
            before.pid,
            before.start_ticks,
            before.uid,
            before.cgroup.as_str(),
        ) != (
            after.unit.as_str(),
            after.pid,
            after.start_ticks,
            after.uid,
            after.cgroup.as_str(),
        )
        || before.cpu_usage_usec > after.cpu_usage_usec
        || before.memory_peak_bytes > after.memory_peak_bytes
        || before.memory_current_bytes > before.memory_peak_bytes
        || after.memory_current_bytes > after.memory_peak_bytes
    {
        return Err("original physical service lifetime/accounting changed".into());
    }
    Ok(())
}
impl Response {
    pub(super) fn validate(
        &self,
        encoder: &Encoder,
        batch: &str,
        pair: &str,
        row: &str,
        uid: u32,
    ) -> Result<()> {
        if self.schema != "hepta.fixed-nomic-public-development-pair.v1"
            || self.purpose != PURPOSE
            || self.batch_id != batch
            || self.pair_id != pair
            || self.source_row_sha256 != row
            || self.encoder_config_sha256 != encoder.config.digest
            || self.normalization_sha256 != encoder.normalization
            || self.tokenizer_sha256 != encoder.tokenizer
            || self.weights_sha256 != encoder.weights
            || self.encoder_manifest_sha256 != encoder.manifest
            || self.physical_elapsed_micros == 0
            || self.measurement_elapsed_micros < self.physical_elapsed_micros
            || self.features_q24.len() != 512
            || self.features_q24.iter().all(|v| *v == 0)
            || self
                .features_q24
                .iter()
                .any(|v| !(-(1_i64 << 24)..=(1_i64 << 24)).contains(v))
            || self.cost_context.accounting != "entire-encoder-and-backend-service-conservative"
            || self.cost_context.services_before.len() != 2
            || self.cost_context.services_after.len() != 2
            || self.cost_context.producer_before.pid != std::process::id()
            || self.cost_context.producer_before.uid != uid
        {
            return Err(
                "closed physical development response differs from original Root batch".into(),
            );
        }
        lifetime(
            &self.cost_context.producer_before,
            &self.cost_context.producer_after,
        )?;
        for (before, after) in self
            .cost_context
            .services_before
            .iter()
            .zip(&self.cost_context.services_after)
        {
            lifetime(before, after)?;
        }
        if self.cost_context.services_before[0].uid != 0
            || self.cost_context.services_before[0].pid == self.cost_context.services_before[1].pid
        {
            return Err("independent actual encoder/backend services required".into());
        }
        Ok(())
    }
}
fn remaining(deadline: Instant) -> Result<Duration> {
    deadline
        .checked_duration_since(Instant::now())
        .filter(|value| !value.is_zero())
        .ok_or_else(|| "original public measurement deadline elapsed".into())
}
pub(super) fn measure(
    encoder: &Encoder,
    batch: &str,
    pair: &str,
    row: &str,
    uid: u32,
    deadline: Instant,
) -> Result<Response> {
    encoder.config.read(2 * 1024 * 1024)?;
    for path in encoder.socket.ancestors().skip(1) {
        let meta = std::fs::symlink_metadata(path)?;
        if path.canonicalize()? != path
            || !meta.is_dir()
            || meta.uid() != 0
            || meta.mode() & 0o022 != 0
        {
            return Err("mutable Root public encoder ancestor".into());
        }
    }
    let before = std::fs::symlink_metadata(&encoder.socket)?;
    if !before.file_type().is_socket() || before.uid() != 0 || before.mode() & 0o007 != 0 {
        return Err("protected Root public encoder socket required".into());
    }
    remaining(deadline)?;
    let socket = rustix::net::socket_with(
        rustix::net::AddressFamily::UNIX,
        rustix::net::SocketType::STREAM,
        rustix::net::SocketFlags::NONBLOCK | rustix::net::SocketFlags::CLOEXEC,
        /*protocol*/ None,
    )?;
    rustix::net::connect(&socket, &rustix::net::SocketAddrUnix::new(&encoder.socket)?)?;
    let peer = rustix::net::sockopt::socket_peercred(&socket)?;
    if peer.uid.as_raw() != 0 {
        return Err("public encoder actual peer is not Root".into());
    }
    let mut stream = UnixStream::from(socket);
    stream.set_nonblocking(false)?;
    let mut body = serde_json::to_vec(
        &serde_json::json!({"purpose":PURPOSE,"batch_id":batch,"pair_id":pair,"source_row_sha256":row}),
    )?;
    body.push(b'\n');
    if body.len() > 16 * 1024 {
        return Err("public encoder request bound".into());
    }
    let mut rest = body.as_slice();
    while !rest.is_empty() {
        stream.set_write_timeout(Some(remaining(deadline)?))?;
        match stream.write(rest) {
            Ok(0) => return Err("public encoder closed request".into()),
            Ok(count) => rest = &rest[count..],
            Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e.into()),
        }
    }
    let mut bytes = Vec::new();
    while !bytes.contains(&b'\n') {
        stream.set_read_timeout(Some(remaining(deadline)?))?;
        let mut block = [0; 4096];
        let count = match stream.read(&mut block) {
            Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
            value => value?,
        };
        if count == 0 || bytes.len() + count > 64 * 1024 {
            return Err("public encoder response bound".into());
        }
        bytes.extend_from_slice(&block[..count]);
    }
    if bytes.last() != Some(&b'\n') || bytes.iter().filter(|&&b| b == b'\n').count() != 1 {
        return Err("one public encoder frame required".into());
    }
    let after = std::fs::symlink_metadata(&encoder.socket)?;
    if (before.dev(), before.ino(), before.mode()) != (after.dev(), after.ino(), after.mode())
        || rustix::net::sockopt::socket_peercred(&stream)? != peer
    {
        return Err("original public encoder transport changed".into());
    }
    encoder.config.read(2 * 1024 * 1024)?;
    remaining(deadline)?;
    let response: Response = serde_json::from_slice(&bytes)?;
    response.validate(encoder, batch, pair, row, uid)?;
    Ok(response)
}

#[cfg(test)]
#[path = "paired_development_transport_tests.rs"]
mod tests;
