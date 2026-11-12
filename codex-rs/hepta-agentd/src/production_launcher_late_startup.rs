//! Explicit CLI selection for an already dedicated non-Root recipient.
//! Parsing takes the real inherited rights in single-thread arg0 preflight;
//! the first runtime only consumes that same pending receive and its deadline.

use super::late_writer::OriginalLateWriterInputs;
use super::*;

const ENTRY_FLAG: &str = "--root-production-entry";

#[derive(Debug, Eq, PartialEq)]
pub(super) enum OriginalStartupSelection {
    Existing(Vec<OsString>),
    LateWriter(Vec<OsString>),
}

/// Select only an explicit pair. An absent selector leaves all original bytes
/// and the original parser's refusal behavior unchanged.
pub(super) fn select_original_startup_entry(
    mut arguments: Vec<OsString>,
) -> Result<OriginalStartupSelection, AgentdError> {
    let mut selected = None;
    for index in (0..arguments.len()).step_by(2) {
        if arguments[index] != ENTRY_FLAG {
            continue;
        }
        if selected.is_some() {
            return Err(AgentdError::Invalid(
                "duplicate --root-production-entry".into(),
            ));
        }
        if arguments.get(index + 1).and_then(|value| value.to_str()) != Some("late-writer") {
            return Err(AgentdError::Invalid(
                "--root-production-entry requires late-writer".into(),
            ));
        }
        selected = Some(index);
    }
    let Some(index) = selected else {
        return Ok(OriginalStartupSelection::Existing(arguments));
    };
    let _ = arguments.drain(index..index + 2);
    Ok(OriginalStartupSelection::LateWriter(arguments))
}

/// Expected identity is comparison data from the original Starting registry.
/// Original authority is obtained only when the retained receive succeeds.
pub(super) struct OriginalLateWriterStartup {
    pub(super) identity: AgentdIdentity,
    original: OriginalLateWriterInputs,
    cognitive_mode: crate::config::CognitiveRetrievalMode,
}

impl OriginalLateWriterStartup {
    pub(super) fn prepare_original_late_writer_startup(
        arguments: Vec<OsString>,
    ) -> Result<(Self, Vec<OsString>), AgentdError> {
        let (original, ordinary) =
            OriginalLateWriterInputs::prepare_original_late_writer_inputs(arguments)?;
        let (identity, cognitive_mode) =
            crate::config::read_original_late_writer_starting_identity()?;
        Ok((
            Self {
                identity,
                original,
                cognitive_mode,
            },
            ordinary,
        ))
    }

    pub(super) async fn receive_original_late_writer_startup(
        self,
    ) -> Result<(AgentdConfig, AgentdProductionLaunch), AgentdError> {
        let Self {
            identity,
            original,
            cognitive_mode,
        } = self;
        let original: OriginalLateWriterInputs = original;
        let (config, launch) = original
            .consume_original_late_writer_inputs(&identity)
            .await?;
        Ok((config.with_cognitive_retrieval_mode(cognitive_mode), launch))
    }
}
