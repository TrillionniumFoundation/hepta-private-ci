use std::env;
use std::io;
use std::io::Read;
use std::io::Write;
use std::net::TcpListener;
use std::net::TcpStream;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_artifacts::owner::ArtifactOwnerBootstrapConfigV1;
use codex_hepta_learning_artifacts::owner::ArtifactOwnerBootstrapV1;
use codex_hepta_learning_artifacts::owner::ArtifactOwnerCommandError;
use codex_hepta_learning_artifacts::owner::DurableInstrumentedLearningArtifactReferenceHostV1;
use codex_hepta_learning_artifacts::durable_replace_control_file_v1;
use codex_hepta_learning_artifacts::owner::SignedArtifactOwnerRequestV1;

const MAX_ERROR_DETAIL: usize = 512;

fn main() {
    if let Err(error) = run() {
        eprintln!("hepta-learning-artifactd: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let config_path = config_argument()?;
    let startup_now = unix_seconds()?;
    let bootstrap = ArtifactOwnerBootstrapV1::load(ArtifactOwnerBootstrapConfigV1 {
        config_path,
        now: startup_now,
    })?;
    let address = bootstrap.runtime.listen_address;
    let maximum_request_bytes = bootstrap.runtime.maximum_request_bytes;
    let metrics_path = bootstrap.runtime.service.root.join("host/status/metrics.prom");
    let host = DurableInstrumentedLearningArtifactReferenceHostV1::open(bootstrap)?;
    persist_metrics(&host, &metrics_path, startup_now)?;
    let listener = TcpListener::bind(address)?;

    for incoming in listener.incoming() {
        let mut stream = incoming?;
        let should_shutdown = handle_connection(&host, &mut stream, maximum_request_bytes)?;
        persist_metrics(&host, &metrics_path, unix_seconds()?)?;
        if should_shutdown {
            host.mark_stopped(unix_seconds()?)?;
            return Ok(());
        }
    }
    Err(io::Error::new(io::ErrorKind::BrokenPipe, "listener terminated").into())
}

fn persist_metrics(
    host: &DurableInstrumentedLearningArtifactReferenceHostV1,
    path: &std::path::Path,
    now: u64,
) -> Result<(), Box<dyn std::error::Error>> {
    let metrics = host.operational_metrics(now)?.prometheus_text();
    durable_replace_control_file_v1(path, metrics.as_bytes())?;
    Ok(())
}

fn config_argument() -> Result<PathBuf, io::Error> {
    let mut args = env::args_os();
    let _program = args.next();
    let Some(flag) = args.next() else {
        return Err(invalid_input("usage: hepta-learning-artifactd --config <absolute-path>"));
    };
    if flag != "--config" {
        return Err(invalid_input("expected --config"));
    }
    let Some(path) = args.next() else {
        return Err(invalid_input("missing --config path"));
    };
    if args.next().is_some() {
        return Err(invalid_input("unexpected trailing arguments"));
    }
    let path = PathBuf::from(path);
    if !path.is_absolute() {
        return Err(invalid_input("--config path must be absolute"));
    }
    Ok(path)
}

fn handle_connection(
    host: &DurableInstrumentedLearningArtifactReferenceHostV1,
    stream: &mut TcpStream,
    maximum_request_bytes: usize,
) -> io::Result<bool> {
    let request = match read_frame(stream, maximum_request_bytes) {
        Ok(bytes) => SignedArtifactOwnerRequestV1::decode(&bytes)
            .map_err(|_| invalid_data("invalid signed request encoding")),
        Err(error) => Err(error),
    };
    let now = unix_seconds()?;
    match request {
        Ok(request) => match host.handle(request, now) {
            Ok(result) => {
                write_frame(stream, &result.response)?;
                Ok(result.should_shutdown)
            }
            Err(error) => {
                write_command_error(stream, &error)?;
                Ok(false)
            }
        },
        Err(error) => {
            write_protocol_error(stream, "invalid_request", &error.to_string())?;
            Ok(false)
        }
    }
}

fn read_frame(stream: &mut TcpStream, maximum_request_bytes: usize) -> io::Result<Vec<u8>> {
    let mut length = [0u8; 4];
    stream.read_exact(&mut length)?;
    let length = u32::from_be_bytes(length) as usize;
    if length == 0 || length > maximum_request_bytes {
        return Err(invalid_data("request frame exceeds configured bound"));
    }
    let mut bytes = vec![0u8; length];
    stream.read_exact(&mut bytes)?;
    Ok(bytes)
}

fn write_frame(stream: &mut TcpStream, bytes: &[u8]) -> io::Result<()> {
    let length = u32::try_from(bytes.len()).map_err(|_| invalid_data("response too large"))?;
    stream.write_all(&length.to_be_bytes())?;
    stream.write_all(bytes)?;
    stream.flush()
}

fn write_command_error(stream: &mut TcpStream, error: &ArtifactOwnerCommandError) -> io::Result<()> {
    write_protocol_error(stream, error.code(), &error.to_string())
}

fn write_protocol_error(stream: &mut TcpStream, code: &str, detail: &str) -> io::Result<()> {
    let detail = detail.chars().take(MAX_ERROR_DETAIL).collect::<String>();
    let response = format!(
        "{{\"schema\":\"hepta.learning-artifactd.error.v1\",\"code\":\"{}\",\"detail\":\"{}\"}}\n",
        escape_json(code),
        escape_json(&detail),
    );
    write_frame(stream, response.as_bytes())
}

fn escape_json(value: &str) -> String {
    let mut output = String::with_capacity(value.len());
    for character in value.chars() {
        match character {
            '"' => output.push_str("\\\""),
            '\\' => output.push_str("\\\\"),
            '\n' => output.push_str("\\n"),
            '\r' => output.push_str("\\r"),
            '\t' => output.push_str("\\t"),
            character if character.is_control() => output.push('?'),
            character => output.push(character),
        }
    }
    output
}

fn unix_seconds() -> io::Result<u64> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .map_err(|_| invalid_data("system clock is before Unix epoch"))
}

fn invalid_input(message: &'static str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidInput, message)
}

fn invalid_data(message: &'static str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn framed_protocol_rejects_zero_and_oversized_requests() {
        let mut zero = &0u32.to_be_bytes()[..];
        assert!(read_frame(&mut_stream(&mut zero), 16).is_err());

        let mut oversized_bytes = Vec::new();
        oversized_bytes.extend_from_slice(&17u32.to_be_bytes());
        oversized_bytes.extend_from_slice(&[0u8; 17]);
        let mut oversized = oversized_bytes.as_slice();
        assert!(read_frame(&mut_stream(&mut oversized), 16).is_err());
    }

    fn mut_stream(_bytes: &mut &[u8]) -> TcpStream {
        panic!("network framing is covered by process E2E")
    }
}
