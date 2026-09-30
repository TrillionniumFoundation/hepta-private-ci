//! Single-instance, loopback-only production embedding for `learning.artifacts`.
//!
//! The transport owns no authority. Every request is a bounded length-prefixed
//! `SignedArtifactOwnerRequestV1`; the reference host authenticates the peer,
//! action, keyring generation, freshness and exact replay identity. Requests are
//! handled sequentially under the service writer fence, so transport concurrency
//! cannot create a second publication owner.

use std::env;
use std::error::Error;
use std::fs;
use std::io;
use std::io::Read;
use std::io::Write;
use std::net::TcpListener;
use std::net::TcpStream;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_artifacts::owner::ArtifactOwnerBootstrapConfigV1;
use codex_hepta_learning_artifacts::owner::ArtifactOwnerBootstrapV1;
use codex_hepta_learning_artifacts::owner::DurableInstrumentedLearningArtifactReferenceHostV1;
use codex_hepta_learning_artifacts::owner::SignedArtifactOwnerRequestV1;
use codex_hepta_learning_artifacts::owner::owner_capability_store_profile_v1;

const FRAME_HEADER_BYTES: usize = 4;
const MAX_RESPONSE_BYTES: usize = 4 * 1024 * 1024;
const IO_TIMEOUT: Duration = Duration::from_secs(30);

fn main() {
    if let Err(error) = run() {
        eprintln!("hepta-learning-artifactd: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn Error>> {
    let config_path = parse_config_path()?;
    let profile = owner_capability_store_profile_v1();
    if !profile.production_qualified() {
        return Err(format!(
            "owner capability store profile {profile:?} is not production qualified"
        )
        .into());
    }
    validate_secure_config(&config_path)?;
    let bootstrap = ArtifactOwnerBootstrapV1::load(ArtifactOwnerBootstrapConfigV1 {
        config_path,
        now: unix_time()?,
    })?;
    let listen_address = bootstrap.runtime.listen_address;
    let maximum_request_bytes = bootstrap.runtime.maximum_request_bytes;
    if !listen_address.ip().is_loopback() {
        return Err("artifact owner transport must bind a loopback address".into());
    }
    let host = DurableInstrumentedLearningArtifactReferenceHostV1::open(bootstrap)?;
    let listener = TcpListener::bind(listen_address)?;
    for connection in listener.incoming() {
        let mut stream = connection?;
        let peer = stream.peer_addr()?;
        if !peer.ip().is_loopback() {
            write_error(&mut stream, "non_loopback_peer")?;
            continue;
        }
        stream.set_read_timeout(Some(IO_TIMEOUT))?;
        stream.set_write_timeout(Some(IO_TIMEOUT))?;
        let should_shutdown = handle_one(&host, &mut stream, maximum_request_bytes)?;
        if should_shutdown || host.shutdown_requested() {
            break;
        }
    }
    host.mark_stopped(unix_time()?)?;
    Ok(())
}

fn parse_config_path() -> Result<PathBuf, Box<dyn Error>> {
    let mut arguments = env::args_os();
    let _program = arguments.next();
    let Some(flag) = arguments.next() else {
        return Err("usage: hepta-learning-artifactd --config /absolute/path".into());
    };
    if flag != "--config" {
        return Err("usage: hepta-learning-artifactd --config /absolute/path".into());
    }
    let path = PathBuf::from(arguments.next().ok_or("missing value for --config")?);
    if arguments.next().is_some() || !path.is_absolute() {
        return Err("configuration path must be the only absolute argument".into());
    }
    Ok(path)
}

fn validate_secure_config(path: &Path) -> io::Result<()> {
    let metadata = fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "configuration must be a regular non-symlink file",
        ));
    }
    Ok(())
}

fn handle_one(
    host: &DurableInstrumentedLearningArtifactReferenceHostV1,
    stream: &mut TcpStream,
    maximum_request_bytes: usize,
) -> Result<bool, Box<dyn Error>> {
    let request_bytes = match read_frame(stream, maximum_request_bytes) {
        Ok(bytes) => bytes,
        Err(_) => {
            write_error(stream, "invalid_frame")?;
            return Ok(false);
        }
    };
    let request = match SignedArtifactOwnerRequestV1::decode(&request_bytes) {
        Ok(request) => request,
        Err(_) => {
            write_error(stream, "invalid_request")?;
            return Ok(false);
        }
    };
    let now = unix_time()?;
    match host.handle(request, now) {
        Ok(result) => {
            write_frame(stream, &result.response)?;
            Ok(result.should_shutdown)
        }
        Err(error) => {
            write_error(stream, error.code())?;
            Ok(false)
        }
    }
}

fn read_frame(stream: &mut TcpStream, maximum_bytes: usize) -> io::Result<Vec<u8>> {
    let mut header = [0_u8; FRAME_HEADER_BYTES];
    stream.read_exact(&mut header)?;
    let length = usize::try_from(u32::from_be_bytes(header)).map_err(|_| {
        io::Error::new(io::ErrorKind::InvalidData, "request frame length overflow")
    })?;
    if length == 0 || length > maximum_bytes {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "request frame outside configured bound",
        ));
    }
    let mut bytes = vec![0; length];
    stream.read_exact(&mut bytes)?;
    Ok(bytes)
}

fn write_frame(stream: &mut TcpStream, bytes: &[u8]) -> io::Result<()> {
    if bytes.len() > MAX_RESPONSE_BYTES {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "response exceeds transport bound",
        ));
    }
    let length = u32::try_from(bytes.len())
        .map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "response length overflow"))?;
    stream.write_all(&length.to_be_bytes())?;
    stream.write_all(bytes)?;
    stream.flush()
}

fn write_error(stream: &mut TcpStream, code: &str) -> io::Result<()> {
    let response = format!(
        "{{\"schema\":\"hepta.learning-artifactd.transport-error.v1\",\"code\":\"{code}\"}}\n"
    );
    write_frame(stream, response.as_bytes())
}

fn unix_time() -> Result<u64, Box<dyn Error>> {
    Ok(SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs())
}
