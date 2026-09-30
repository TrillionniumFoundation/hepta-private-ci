//! Minimal production composition for the learning-artifact owner.
//!
//! The daemon exposes no unauthenticated administrative surface. Bootstrap
//! restricts the listener to loopback; each connection carries one bounded
//! signed request and receives one bounded response.

use std::env;
use std::io::Read;
use std::io::Write;
use std::net::TcpListener;
use std::net::TcpStream;
use std::path::PathBuf;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_artifacts::owner::ArtifactOwnerActionV1;
use codex_hepta_learning_artifacts::owner::ArtifactOwnerBootstrapConfigV1;
use codex_hepta_learning_artifacts::owner::ArtifactOwnerBootstrapV1;
use codex_hepta_learning_artifacts::owner::DurableInstrumentedLearningArtifactReferenceHostV1;
use codex_hepta_learning_artifacts::owner::SignedArtifactOwnerRequestV1;

const IO_TIMEOUT: Duration = Duration::from_secs(15);

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = env::args_os();
    let program = args
        .next()
        .and_then(|value| value.into_string().ok())
        .unwrap_or_else(|| "hepta-learning-artifactd".to_owned());
    let config_path = args.next().map(PathBuf::from).ok_or_else(|| {
        format!("usage: {program} <absolute-config-path>; exactly one config is required")
    })?;
    if args.next().is_some() {
        return Err(format!("usage: {program} <absolute-config-path>").into());
    }
    if !config_path.is_absolute() {
        return Err("config path must be absolute".into());
    }

    let bootstrap = ArtifactOwnerBootstrapV1::load(ArtifactOwnerBootstrapConfigV1 {
        config_path,
        now: unix_seconds()?,
    })?;
    let listen_address = bootstrap.runtime.listen_address;
    let maximum_request_bytes = bootstrap.runtime.maximum_request_bytes;
    let host = DurableInstrumentedLearningArtifactReferenceHostV1::open(bootstrap)?;
    let listener = TcpListener::bind(listen_address)?;

    for incoming in listener.incoming() {
        let mut stream = incoming?;
        configure_stream(&stream)?;
        let request_bytes = read_bounded(&mut stream, maximum_request_bytes)?;
        let request = match SignedArtifactOwnerRequestV1::decode(&request_bytes) {
            Ok(request) => request,
            Err(error) => {
                write_response(
                    &mut stream,
                    format!(
                        "{{\"schema\":\"hepta.learning-artifactd.transport-error.v1\",\"error\":\"{error}\"}}"
                    )
                    .as_bytes(),
                )?;
                continue;
            }
        };
        let action = request.action;
        let now = unix_seconds()?;
        let result = host.handle(request, now);
        match result {
            Ok(result) => {
                if action == ArtifactOwnerActionV1::Metrics {
                    let metrics = host.operational_metrics(now)?.prometheus_text();
                    write_response(&mut stream, metrics.as_bytes())?;
                } else {
                    write_response(&mut stream, &result.response)?;
                }
                if result.should_shutdown {
                    host.mark_stopped(unix_seconds()?)?;
                    break;
                }
            }
            Err(error) => {
                write_response(
                    &mut stream,
                    format!(
                        "{{\"schema\":\"hepta.learning-artifactd.transport-error.v1\",\"error\":\"{error}\"}}"
                    )
                    .as_bytes(),
                )?;
            }
        }
    }
    Ok(())
}

fn configure_stream(stream: &TcpStream) -> std::io::Result<()> {
    stream.set_read_timeout(Some(IO_TIMEOUT))?;
    stream.set_write_timeout(Some(IO_TIMEOUT))?;
    stream.set_nodelay(true)
}

fn read_bounded(stream: &mut TcpStream, maximum: usize) -> std::io::Result<Vec<u8>> {
    let maximum_u64 = u64::try_from(maximum).unwrap_or(u64::MAX);
    let mut bytes = Vec::with_capacity(maximum.min(64 * 1024));
    stream
        .take(maximum_u64.saturating_add(1))
        .read_to_end(&mut bytes)?;
    if bytes.len() > maximum {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            "request exceeds configured maximum",
        ));
    }
    Ok(bytes)
}

fn write_response(stream: &mut TcpStream, response: &[u8]) -> std::io::Result<()> {
    stream.write_all(response)?;
    stream.flush()?;
    stream.shutdown(std::net::Shutdown::Write)
}

fn unix_seconds() -> Result<u64, std::time::SystemTimeError> {
    Ok(SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs())
}
