//! Correlation-only readiness on the original Initial socket. The request
//! carries no deployment, owner, path, grant or task-completion assertion.

use super::InitialBootstrap;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use std::io;

const PURPOSE: &str = "runtime.cell-generation.initial-peer-ready.v1";

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ReadyRequest {
    schema: u8,
    purpose: String,
    request_id: u64,
    bootstrap: String,
    command: ReadyCommand,
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum ReadyCommand {
    Ready {},
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ReadyResponse {
    schema: u8,
    purpose: String,
    request_id: u64,
    bootstrap: String,
    profile: String,
}

pub(crate) fn bootstrap_binding(bootstrap: &InitialBootstrap) -> io::Result<String> {
    Ok(Digest32::of_parts(&[
        b"hepta.root.generation-initial.peer-ready-bootstrap.v1\0",
        &serde_json::to_vec(bootstrap).map_err(io::Error::other)?,
    ])
    .to_string())
}

pub(crate) fn request(binding: &str) -> io::Result<Vec<u8>> {
    require_digest(binding)?;
    serde_json::to_vec(&ReadyRequest {
        schema: 1,
        purpose: PURPOSE.into(),
        request_id: 1,
        bootstrap: binding.to_owned(),
        command: ReadyCommand::Ready {},
    })
    .map_err(io::Error::other)
}

pub(crate) fn require_request(bytes: &[u8], binding: &str) -> io::Result<()> {
    let request: ReadyRequest = serde_json::from_slice(bytes).map_err(io::Error::other)?;
    require_digest(binding)?;
    if request.schema != 1
        || request.purpose != PURPOSE
        || request.request_id != 1
        || request.bootstrap != binding
    {
        return Err(io::Error::other(
            "original Initial readiness binding differs",
        ));
    }
    Ok(())
}

pub(crate) fn response(binding: &str, profile: &str) -> io::Result<Vec<u8>> {
    require_digest(binding)?;
    require_digest(profile)?;
    serde_json::to_vec(&ReadyResponse {
        schema: 1,
        purpose: PURPOSE.into(),
        request_id: 1,
        bootstrap: binding.to_owned(),
        profile: profile.to_owned(),
    })
    .map_err(io::Error::other)
}

pub(crate) fn require_response(bytes: &[u8], binding: &str) -> io::Result<String> {
    let response: ReadyResponse = serde_json::from_slice(bytes).map_err(io::Error::other)?;
    require_digest(binding)?;
    require_digest(&response.profile)?;
    if response.schema != 1
        || response.purpose != PURPOSE
        || response.request_id != 1
        || response.bootstrap != binding
    {
        return Err(io::Error::other(
            "original Initial readiness acknowledgement differs",
        ));
    }
    Ok(response.profile)
}

fn require_digest(value: &str) -> io::Result<()> {
    if !value
        .parse::<Digest32>()
        .is_ok_and(|digest| !digest.is_zero() && digest.to_string() == value)
    {
        return Err(io::Error::other(
            "canonical Initial readiness digest required",
        ));
    }
    Ok(())
}
