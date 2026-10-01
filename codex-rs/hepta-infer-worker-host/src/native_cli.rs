//! Parse the native executable's complete invocation before opening owner state
//! or waiting for stdin. Runtime contracts remain validated by their owners.

use std::error::Error as StdError;
use std::path::PathBuf;

type Result<T> = std::result::Result<T, Box<dyn StdError + Send + Sync>>;

#[derive(Debug, Eq, PartialEq)]
pub(super) enum Invocation {
    Help,
    Run(Box<NativeCliOptions>),
}

#[derive(Debug, Eq, PartialEq)]
pub(super) struct NativeCliOptions {
    pub agentd_socket: PathBuf,
    pub agent_id: String,
    pub generation: u64,
    pub model: String,
    pub journal: PathBuf,
    pub request_id: String,
    pub maximum_in_flight: usize,
    pub context_query: Option<String>,
    pub final_use_authority_config: PathBuf,
    pub intelligence: Option<IntelligenceCliOptions>,
    pub timeout_ms: u64,
}

#[derive(Debug, Eq, PartialEq)]
pub(super) struct IntelligenceCliOptions {
    pub run_id: String,
    pub expected_revision: u64,
    pub context_digest: String,
    pub envelope_digest: String,
}

pub(super) fn parse(arguments: impl IntoIterator<Item = String>) -> Result<Invocation> {
    let mut socket = None;
    let mut agent_id = None;
    let mut generation = None;
    let mut model = None;
    let mut journal = None;
    let mut request_id = None;
    let mut maximum_in_flight = None;
    let mut context_query = None;
    let mut final_use_authority_config = None;
    let mut intelligence_run_id = None;
    let mut intelligence_revision = None;
    let mut intelligence_context_digest = None;
    let mut intelligence_envelope_digest = None;
    let mut native_profile_selected = false;
    let mut timeout_ms = 120_000_u64;
    let mut args = arguments.into_iter();
    while let Some(flag) = args.next() {
        if flag == "--help" {
            return Ok(Invocation::Help);
        }
        let value = args.next().ok_or("missing argument value")?;
        match flag.as_str() {
            "--profile" if value == "native-app-server" => native_profile_selected = true,
            "--profile" => return Err(format!("unsupported worker profile: {value}").into()),
            "--agentd-socket" => socket = Some(PathBuf::from(value)),
            "--agent-id" => agent_id = Some(value),
            "--generation" => generation = Some(value.parse()?),
            "--model" => model = Some(value),
            "--journal" => journal = Some(PathBuf::from(value)),
            "--request-id" => request_id = Some(value),
            "--maximum-in-flight" => maximum_in_flight = Some(value.parse()?),
            "--context-query" => context_query = Some(value),
            "--final-use-authority-config" => {
                final_use_authority_config = Some(PathBuf::from(value));
            }
            "--intelligence-run-id" => intelligence_run_id = Some(value),
            "--intelligence-revision" => intelligence_revision = Some(value.parse()?),
            "--intelligence-context-digest" => intelligence_context_digest = Some(value),
            "--intelligence-envelope-digest" => intelligence_envelope_digest = Some(value),
            "--timeout-ms" => timeout_ms = value.parse()?,
            _ => return Err(format!("unknown argument: {flag}").into()),
        }
    }
    if !native_profile_selected {
        return Err("--profile native-app-server must be selected explicitly".into());
    }
    let intelligence = match (
        intelligence_run_id,
        intelligence_revision,
        intelligence_context_digest,
        intelligence_envelope_digest,
    ) {
        (None, None, None, None) => None,
        (Some(run_id), Some(expected_revision), Some(context_digest), Some(envelope_digest)) => {
            Some(IntelligenceCliOptions {
                run_id,
                expected_revision,
                context_digest,
                envelope_digest,
            })
        }
        _ => return Err("all four --intelligence-* arguments must be supplied together".into()),
    };
    if intelligence.is_some() && context_query.is_some() {
        return Err(
            "optional context query with intelligence requires a combined owner final-use port"
                .into(),
        );
    }
    let journal = journal.ok_or("--journal is required")?;
    if !journal.is_absolute() {
        return Err("--journal must be absolute".into());
    }
    Ok(Invocation::Run(Box::new(NativeCliOptions {
        agentd_socket: socket.ok_or("--agentd-socket is required")?,
        agent_id: agent_id.ok_or("--agent-id is required")?,
        generation: generation.ok_or("--generation is required")?,
        model: model.ok_or("--model is required")?,
        journal,
        request_id: request_id.ok_or("--request-id is required")?,
        maximum_in_flight: maximum_in_flight.ok_or("--maximum-in-flight is required")?,
        context_query,
        final_use_authority_config: final_use_authority_config
            .ok_or("--final-use-authority-config is required")?,
        intelligence,
        timeout_ms,
    })))
}

#[cfg(test)]
#[path = "native_cli_tests.rs"]
mod tests;
