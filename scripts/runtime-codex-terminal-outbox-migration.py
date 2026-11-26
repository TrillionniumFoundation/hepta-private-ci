#!/usr/bin/env python3
"""Materialize runtime.codex terminal publication as a durable outbox.

The migration is intentionally idempotent.  It runs after the existing
runtime.codex convergence migrations and makes the local terminal observation
and the pending Agentd publication one journal transition.  Publication then
reconciles from that durable intent and records either a failed attempt or an
acknowledged owner revision.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rewrite(path: str, transform) -> None:
    target = ROOT / path
    original = target.read_text(encoding="utf-8")
    updated = transform(original)
    if updated != original:
        target.write_text(updated, encoding="utf-8")


def replace_once(text: str, old: str, new: str, *, marker: str) -> str:
    if old in text:
        if text.count(old) != 1:
            raise RuntimeError(f"{marker}: expected exactly one legacy block")
        return text.replace(old, new)
    if marker in text:
        return text
    raise RuntimeError(f"{marker}: neither legacy block nor migrated marker found")


def insert_before_once(text: str, needle: str, insertion: str, *, marker: str) -> str:
    if marker in text:
        return text
    if text.count(needle) != 1:
        raise RuntimeError(f"{marker}: expected exactly one insertion point")
    return text.replace(needle, insertion + needle, 1)


def migrate_native_control(text: str) -> str:
    boundary = '''#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeBoundaryStatus {
    Succeeded,
    Failed,
    Interrupted,
    Cancelled,
    TimedOut,
    Quarantined,
    #[default]
    Indeterminate,
}
'''
    types = boundary + '''
/// Logical Agentd terminal state derived from the runtime boundary, never from
/// provider completion alone.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeTerminalPublicationPhase {
    Succeeded,
    Failed,
    Cancelled,
    Indeterminate,
}

/// Agentd owner identity pinned into the same local dispatch transition that
/// issues the one-shot pre-effect proof.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeTerminalOwnerBinding {
    pub run_id: String,
    pub owner_dispatch_revision: u64,
    pub context_digest: String,
    pub envelope_digest: String,
}

/// Durable outbox entry produced atomically with a local observation.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeTerminalPublication {
    pub owner: NativeTerminalOwnerBinding,
    pub phase: NativeTerminalPublicationPhase,
    pub terminal_observed: bool,
    pub publication_digest: String,
    pub attempts: u32,
    pub last_error_digest: Option<String>,
    pub acknowledged_revision: Option<u64>,
}

impl NativeTerminalPublication {
    #[must_use]
    pub fn pending(&self) -> bool {
        self.acknowledged_revision.is_none()
    }
}
'''
    text = replace_once(
        text,
        boundary,
        types,
        marker="pub enum NativeTerminalPublicationPhase",
    )

    old_record = '''    #[serde(default)]
    pub pre_effect_abort: Option<NativePreEffectAbortRecord>,
    #[serde(default)]
    pub dispatch_rejection: Option<NativeDispatchRejection>,
    pub observation: Option<NativeRunOutput>,
'''
    new_record = '''    #[serde(default)]
    pub pre_effect_abort: Option<NativePreEffectAbortRecord>,
    #[serde(default)]
    pub dispatch_rejection: Option<NativeDispatchRejection>,
    #[serde(default)]
    pub terminal_owner: Option<NativeTerminalOwnerBinding>,
    #[serde(default)]
    pub terminal_publication: Option<NativeTerminalPublication>,
    pub observation: Option<NativeRunOutput>,
'''
    text = replace_once(
        text,
        old_record,
        new_record,
        marker="pub terminal_publication: Option<NativeTerminalPublication>",
    )

    old_dispatch_event = '''    Dispatch {
        request_id: String,
        dispatch: NativeDispatch,
    },
'''
    new_dispatch_event = '''    Dispatch {
        request_id: String,
        dispatch: NativeDispatch,
        #[serde(default)]
        terminal_owner: Option<NativeTerminalOwnerBinding>,
    },
'''
    text = replace_once(
        text,
        old_dispatch_event,
        new_dispatch_event,
        marker="terminal_owner: Option<NativeTerminalOwnerBinding>",
    )

    old_observe_event = '''    Observe {
        request_id: String,
        output: NativeRunOutput,
    },
'''
    new_observe_event = '''    Observe {
        request_id: String,
        output: NativeRunOutput,
    },
    TerminalPublicationFailed {
        request_id: String,
        publication_digest: String,
        error_digest: String,
    },
    TerminalPublicationAcknowledged {
        request_id: String,
        publication_digest: String,
        owner_revision: u64,
    },
'''
    text = replace_once(
        text,
        old_observe_event,
        new_observe_event,
        marker="TerminalPublicationAcknowledged",
    )

    old_dispatch_call = '''            Event::Dispatch {
                request_id: request_id.to_string(),
                dispatch,
            },
'''
    new_dispatch_call = '''            Event::Dispatch {
                request_id: request_id.to_string(),
                dispatch,
                terminal_owner: None,
            },
'''
    text = replace_once(
        text,
        old_dispatch_call,
        new_dispatch_call,
        marker="terminal_owner: None",
    )

    old_pre_effect = '''    pub fn dispatch_native_with_pre_effect_abort(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
    ) -> Result<(NativeRunRecord, NativePreEffectAbortToken), Error> {
        let record = self.dispatch_native(request_id, dispatch)?;
        let mut abort_nonce = [0_u8; 32];
        rand::rng().fill_bytes(&mut abort_nonce);
        Ok((
            record.clone(),
            NativePreEffectAbortToken {
                request_id: request_id.to_string(),
                dispatch_revision: record.revision,
                abort_nonce,
            },
        ))
    }
'''
    new_pre_effect = '''    pub fn dispatch_native_with_pre_effect_abort(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
    ) -> Result<(NativeRunRecord, NativePreEffectAbortToken), Error> {
        self.dispatch_native_with_optional_terminal_owner(request_id, dispatch, None)
    }

    /// Atomically persists the local physical dispatch and the exact Agentd
    /// owner that must receive every later logical terminal publication.
    pub fn dispatch_native_with_pre_effect_abort_bound(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
        terminal_owner: NativeTerminalOwnerBinding,
    ) -> Result<(NativeRunRecord, NativePreEffectAbortToken), Error> {
        validate_terminal_owner_binding(&terminal_owner)?;
        self.dispatch_native_with_optional_terminal_owner(
            request_id,
            dispatch,
            Some(terminal_owner),
        )
    }

    fn dispatch_native_with_optional_terminal_owner(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
        terminal_owner: Option<NativeTerminalOwnerBinding>,
    ) -> Result<(NativeRunRecord, NativePreEffectAbortToken), Error> {
        self.ensure_native_dispatch_space()?;
        let record = self.commit_native(
            request_id,
            Event::Dispatch {
                request_id: request_id.to_string(),
                dispatch,
                terminal_owner,
            },
        )?;
        let mut abort_nonce = [0_u8; 32];
        rand::rng().fill_bytes(&mut abort_nonce);
        Ok((
            record.clone(),
            NativePreEffectAbortToken {
                request_id: request_id.to_string(),
                dispatch_revision: record.revision,
                abort_nonce,
            },
        ))
    }
'''
    text = replace_once(
        text,
        old_pre_effect,
        new_pre_effect,
        marker="dispatch_native_with_optional_terminal_owner",
    )

    settle_marker = '''    pub fn native_record(&self, request_id: &str) -> Option<&NativeRunRecord> {
'''
    publication_methods = '''    /// Record one failed Agentd publication attempt without changing the
    /// logical terminal intent. The pending entry remains recoverable.
    pub fn record_native_terminal_publication_failure(
        &mut self,
        request_id: &str,
        publication_digest: &str,
        error_digest: &str,
    ) -> Result<NativeRunRecord, Error> {
        validate_digest(publication_digest, "native terminal publication")?;
        validate_digest(error_digest, "native terminal publication error")?;
        self.commit_native(
            request_id,
            Event::TerminalPublicationFailed {
                request_id: request_id.to_string(),
                publication_digest: publication_digest.to_string(),
                error_digest: error_digest.to_string(),
            },
        )
    }

    /// Acknowledge only the exact pending publication and exact owner revision.
    pub fn acknowledge_native_terminal_publication(
        &mut self,
        request_id: &str,
        publication_digest: &str,
        owner_revision: u64,
    ) -> Result<NativeRunRecord, Error> {
        validate_digest(publication_digest, "native terminal publication")?;
        let record = self
            .native
            .records
            .get(request_id)
            .ok_or(Error::RequestNotFound)?;
        let publication = record
            .terminal_publication
            .as_ref()
            .ok_or(Error::InvalidTransition)?;
        if publication.publication_digest != publication_digest {
            return Err(Error::Conflict);
        }
        if publication.acknowledged_revision == Some(owner_revision) {
            return Ok(record.clone());
        }
        self.commit_native(
            request_id,
            Event::TerminalPublicationAcknowledged {
                request_id: request_id.to_string(),
                publication_digest: publication_digest.to_string(),
                owner_revision,
            },
        )
    }

'''
    text = insert_before_once(
        text,
        settle_marker,
        publication_methods,
        marker="record_native_terminal_publication_failure",
    )

    old_reserve_fields = '''                    pre_effect_abort: None,
                    dispatch_rejection: None,
                    observation: None,
'''
    new_reserve_fields = '''                    pre_effect_abort: None,
                    dispatch_rejection: None,
                    terminal_owner: None,
                    terminal_publication: None,
                    observation: None,
'''
    text = replace_once(
        text,
        old_reserve_fields,
        new_reserve_fields,
        marker="terminal_publication: None",
    )

    old_id_match = '''            | Event::ConfirmAbortBeforeEffect { request_id, .. }
            | Event::Observe { request_id, .. } => request_id,
'''
    new_id_match = '''            | Event::ConfirmAbortBeforeEffect { request_id, .. }
            | Event::Observe { request_id, .. }
            | Event::TerminalPublicationFailed { request_id, .. }
            | Event::TerminalPublicationAcknowledged { request_id, .. } => request_id,
'''
    text = replace_once(
        text,
        old_id_match,
        new_id_match,
        marker="Event::TerminalPublicationAcknowledged { request_id, .. }",
    )

    old_dispatch_arm = '''            Event::Dispatch { dispatch, .. } => {
'''
    new_dispatch_arm = '''            Event::Dispatch {
                dispatch,
                terminal_owner,
                ..
            } => {
'''
    text = replace_once(
        text,
        old_dispatch_arm,
        new_dispatch_arm,
        marker="terminal_owner,\n                ..",
    )

    old_dispatch_commit = '''                record.dispatch = Some(dispatch);
                record.state = NativeReservationState::Dispatching;
'''
    new_dispatch_commit = '''                if let Some(owner) = terminal_owner.as_ref() {
                    validate_terminal_owner_binding(owner)?;
                }
                record.dispatch = Some(dispatch);
                record.terminal_owner = terminal_owner;
                record.state = NativeReservationState::Dispatching;
'''
    text = replace_once(
        text,
        old_dispatch_commit,
        new_dispatch_commit,
        marker="record.terminal_owner = terminal_owner",
    )

    old_observe_arm = '''            Event::Observe { output, .. } => {
                if record.dispatch_rejection.is_some() || record.pre_effect_abort.is_some() {
                    return Err(Error::InvalidTransition);
                }
                apply_observation(record, output)?;
            }
'''
    new_observe_arm = '''            Event::Observe { output, .. } => {
                if record.dispatch_rejection.is_some() || record.pre_effect_abort.is_some() {
                    return Err(Error::InvalidTransition);
                }
                apply_observation(record, output)?;
            }
            Event::TerminalPublicationFailed {
                publication_digest,
                error_digest,
                ..
            } => {
                validate_digest(&publication_digest, "native terminal publication")?;
                validate_digest(&error_digest, "native terminal publication error")?;
                let publication = record
                    .terminal_publication
                    .as_mut()
                    .ok_or(Error::InvalidTransition)?;
                if publication.publication_digest != publication_digest
                    || publication.acknowledged_revision.is_some()
                {
                    return Err(Error::Conflict);
                }
                publication.attempts = publication
                    .attempts
                    .checked_add(1)
                    .ok_or(Error::ArithmeticOverflow)?;
                publication.last_error_digest = Some(error_digest);
            }
            Event::TerminalPublicationAcknowledged {
                publication_digest,
                owner_revision,
                ..
            } => {
                validate_digest(&publication_digest, "native terminal publication")?;
                let publication = record
                    .terminal_publication
                    .as_mut()
                    .ok_or(Error::InvalidTransition)?;
                if publication.publication_digest != publication_digest
                    || publication.acknowledged_revision.is_some()
                    || owner_revision < publication.owner.owner_dispatch_revision
                {
                    return Err(Error::Conflict);
                }
                publication.attempts = publication
                    .attempts
                    .checked_add(1)
                    .ok_or(Error::ArithmeticOverflow)?;
                publication.last_error_digest = None;
                publication.acknowledged_revision = Some(owner_revision);
            }
'''
    text = replace_once(
        text,
        old_observe_arm,
        new_observe_arm,
        marker="publication.last_error_digest = Some(error_digest)",
    )

    old_observation_tail = '''    record.state = if output.terminal_observed {
        NativeReservationState::Released
    } else {
        NativeReservationState::Indeterminate
    };
    record.observation = Some(output);
    Ok(())
}
'''
    new_observation_tail = '''    let publication = derive_terminal_publication(record.terminal_owner.as_ref(), &output)?;
    record.state = if output.terminal_observed {
        NativeReservationState::Released
    } else {
        NativeReservationState::Indeterminate
    };
    record.observation = Some(output);
    record.terminal_publication = publication;
    Ok(())
}

fn validate_terminal_owner_binding(owner: &NativeTerminalOwnerBinding) -> Result<(), Error> {
    validate_identity(&owner.run_id, "native terminal owner run")?;
    validate_digest(&owner.context_digest, "native terminal owner context")?;
    validate_digest(&owner.envelope_digest, "native terminal owner envelope")?;
    if owner.owner_dispatch_revision == 0 {
        return Err(Error::InvalidIdentity("native terminal owner revision"));
    }
    Ok(())
}

fn derive_terminal_publication(
    owner: Option<&NativeTerminalOwnerBinding>,
    output: &NativeRunOutput,
) -> Result<Option<NativeTerminalPublication>, Error> {
    let Some(owner) = owner else {
        return Ok(None);
    };
    validate_terminal_owner_binding(owner)?;
    let (phase, terminal_observed) = if output.succeeded() {
        (NativeTerminalPublicationPhase::Succeeded, true)
    } else {
        match output.boundary_status {
            NativeBoundaryStatus::Failed if output.terminal_observed => {
                (NativeTerminalPublicationPhase::Failed, true)
            }
            NativeBoundaryStatus::Interrupted | NativeBoundaryStatus::Cancelled
                if output.terminal_observed =>
            {
                (NativeTerminalPublicationPhase::Cancelled, true)
            }
            NativeBoundaryStatus::Succeeded
            | NativeBoundaryStatus::Failed
            | NativeBoundaryStatus::Interrupted
            | NativeBoundaryStatus::Cancelled
            | NativeBoundaryStatus::TimedOut
            | NativeBoundaryStatus::Quarantined
            | NativeBoundaryStatus::Indeterminate => {
                (NativeTerminalPublicationPhase::Indeterminate, false)
            }
        }
    };
    let bytes = serde_json::to_vec(&(
        "hepta.runtime.codex.terminal-publication.v1",
        owner,
        phase,
        terminal_observed,
        output,
    ))
    .map_err(|_| Error::CorruptJournal("native terminal publication encode"))?;
    Ok(Some(NativeTerminalPublication {
        owner: owner.clone(),
        phase,
        terminal_observed,
        publication_digest: Digest32::of_bytes(&bytes).to_string(),
        attempts: 0,
        last_error_digest: None,
        acknowledged_revision: None,
    }))
}
'''
    text = replace_once(
        text,
        old_observation_tail,
        new_observation_tail,
        marker="fn derive_terminal_publication(",
    )
    return text


def migrate_native_imports(text: str) -> str:
    old = '''use codex_hepta_infer_core::durable_control::native::NativePreEffectAbortToken;
pub use codex_hepta_infer_core::durable_control::native::NativeRunOutput;
'''
    new = '''use codex_hepta_infer_core::durable_control::native::NativePreEffectAbortToken;
use codex_hepta_infer_core::durable_control::native::NativeTerminalOwnerBinding;
use codex_hepta_infer_core::durable_control::native::NativeTerminalPublication;
use codex_hepta_infer_core::durable_control::native::NativeTerminalPublicationPhase;
pub use codex_hepta_infer_core::durable_control::native::NativeRunOutput;
'''
    text = replace_once(
        text,
        old,
        new,
        marker="NativeTerminalPublicationPhase",
    )
    return text


def migrate_native_execution(text: str) -> str:
    old_dispatch = '''        let (_, pre_effect_abort) =
            control.dispatch_native_with_pre_effect_abort(request_id, dispatch)?;
        let prepared_revision = control
'''
    new_dispatch = '''        let terminal_owner = if let Some(binding) = intelligence {
            Some(NativeTerminalOwnerBinding {
                run_id: binding.run_id.clone(),
                owner_dispatch_revision: binding
                    .expected_revision
                    .checked_add(1)
                    .ok_or("Agentd dispatch revision overflow")?,
                context_digest: binding.context_digest.clone(),
                envelope_digest: binding.envelope_digest.clone(),
            })
        } else {
            None
        };
        let (_, pre_effect_abort) = match terminal_owner {
            Some(owner_binding) => control.dispatch_native_with_pre_effect_abort_bound(
                request_id,
                dispatch,
                owner_binding,
            )?,
            None => control.dispatch_native_with_pre_effect_abort(request_id, dispatch)?,
        };
        let prepared_revision = control
'''
    text = replace_once(
        text,
        old_dispatch,
        new_dispatch,
        marker="let terminal_owner = if let Some(binding) = intelligence",
    )

    old_indeterminate = '''            if !output.terminal_observed
                && let (Some(binding), Some(revision)) = (intelligence, intelligence_revision)
                && let Err(error) = owner
                    .run_observe_terminal(
                        binding.run_id.clone(),
                        revision,
                        AgentRunPhase::Indeterminate,
                        /*terminal_observed*/ false,
                    )
                    .await
            {
                let note = format!("Agentd indeterminate reconciliation required: {error}");
                output.stop_reason = Some(match output.stop_reason.take() {
                    Some(existing) => format!("{existing}; {note}"),
                    None => note,
                });
            }
'''
    new_indeterminate = '''            // Agentd terminal publication is never performed from volatile
            // execution state. The outer durable settlement creates the exact
            // pending outbox entry and recovery publishes that entry.
'''
    text = replace_once(
        text,
        old_indeterminate,
        new_indeterminate,
        marker="Agentd terminal publication is never performed from volatile",
    )

    old_terminal = '''            if let (Some(binding), Some(revision)) = (intelligence, intelligence_revision)
                && let Err(error) =
                    commit_intelligence_terminal(&owner, binding, revision, &output).await
            {
                let note = format!("Agentd terminal reconciliation required: {error}");
                output.stop_reason = Some(
                    match output.stop_reason.take() {
                        Some(existing) => format!("{existing}; {note}"),
                        None => note,
                    }
                    .chars()
                    .take(1024)
                    .collect(),
                );
            }
'''
    new_terminal = '''            // Local settlement below atomically creates the durable Agentd
            // terminal-publication outbox. No direct cross-owner write occurs
            // before that journal transition.
'''
    text = replace_once(
        text,
        old_terminal,
        new_terminal,
        marker="terminal-publication outbox",
    )
    return text


def migrate_native_app_server(text: str) -> str:
    old_unknown = '''async fn reconcile_intelligence_start_unknown(
    owner: &AgentdClient,
    binding: Option<&NativeIntelligenceRunBinding>,
    revision: Option<u64>,
    mut output: NativeRunOutput,
) -> NativeRunOutput {
    if let (Some(binding), Some(revision)) = (binding, revision)
        && let Err(error) = owner
            .run_observe_terminal(
                binding.run_id.clone(),
                revision,
                AgentRunPhase::Indeterminate,
                false,
            )
            .await
    {
        let reason = output.stop_reason.take().unwrap_or_default();
        output.stop_reason = Some(
            format!("{reason}; Agentd reconciliation remains required: {error}")
                .chars()
                .take(1024)
                .collect(),
        );
    }
    output
}
'''
    new_unknown = '''async fn reconcile_intelligence_start_unknown(
    _owner: &AgentdClient,
    _binding: Option<&NativeIntelligenceRunBinding>,
    _revision: Option<u64>,
    output: NativeRunOutput,
) -> NativeRunOutput {
    // The outer local settlement writes the durable Indeterminate publication.
    // Publishing here would recreate the cross-journal crash window.
    output
}
'''
    text = replace_once(
        text,
        old_unknown,
        new_unknown,
        marker="outer local settlement writes the durable Indeterminate publication",
    )

    start = text.find("async fn commit_intelligence_terminal(")
    end_marker = "\nasync fn verify_owner_health("
    if start >= 0:
        end = text.find(end_marker, start)
        if end < 0:
            raise RuntimeError("terminal outbox: missing verify_owner_health boundary")
        replacement = '''fn agentd_terminal_phase(
    phase: NativeTerminalPublicationPhase,
) -> AgentRunPhase {
    match phase {
        NativeTerminalPublicationPhase::Succeeded => AgentRunPhase::Succeeded,
        NativeTerminalPublicationPhase::Failed => AgentRunPhase::Failed,
        NativeTerminalPublicationPhase::Cancelled => AgentRunPhase::Cancelled,
        NativeTerminalPublicationPhase::Indeterminate => AgentRunPhase::Indeterminate,
    }
}

impl AppServerModelDriver {
    /// Publish only the durable outbox entry. A crash after Agentd commits but
    /// before local acknowledgement is reconciled by run_status on restart.
    pub(super) async fn publish_pending_intelligence_terminal(
        &self,
        control: &mut DurableInferenceControl,
        request_id: &str,
    ) -> Result<()> {
        let Some(publication) = control
            .native_record(request_id)
            .and_then(|record| record.terminal_publication.clone())
        else {
            return Ok(());
        };
        if !publication.pending() {
            return Ok(());
        }
        let owner = AgentdClient::new(
            self.config.agentd_socket.clone(),
            self.config.agent_id.clone(),
            self.config.generation,
        )?;
        match publish_terminal_outbox_once(&owner, &publication).await {
            Ok(owner_revision) => {
                control.acknowledge_native_terminal_publication(
                    request_id,
                    &publication.publication_digest,
                    owner_revision,
                )?;
                Ok(())
            }
            Err(error) => {
                let error_digest = Digest32::of_bytes(error.to_string().as_bytes()).to_string();
                control.record_native_terminal_publication_failure(
                    request_id,
                    &publication.publication_digest,
                    &error_digest,
                )?;
                Err(error)
            }
        }
    }
}

async fn publish_terminal_outbox_once(
    owner: &AgentdClient,
    publication: &NativeTerminalPublication,
) -> Result<u64> {
    let desired_phase = agentd_terminal_phase(publication.phase);
    let current = owner
        .run_status(publication.owner.run_id.clone())
        .await?
        .ok_or("Agentd terminal owner disappeared")?;
    if current.run_id != publication.owner.run_id
        || current.generation == 0
        || current.context_digest.as_deref()
            != Some(publication.owner.context_digest.as_str())
        || current.compilation_receipt_digest.as_deref()
            != Some(publication.owner.envelope_digest.as_str())
        || current.revision < publication.owner.owner_dispatch_revision
    {
        return Err("Agentd terminal owner binding drifted".into());
    }
    let exact_current = current.phase == desired_phase
        && current.terminal_observed == publication.terminal_observed;
    if exact_current {
        return Ok(current.revision);
    }
    if !matches!(
        current.phase,
        AgentRunPhase::Dispatched
            | AgentRunPhase::Cancelling
            | AgentRunPhase::Indeterminate
    ) {
        return Err("Agentd terminal owner already has a conflicting terminal state".into());
    }
    let receipt = owner
        .run_observe_terminal(
            publication.owner.run_id.clone(),
            current.revision,
            desired_phase,
            publication.terminal_observed,
        )
        .await?;
    if receipt.run_id != publication.owner.run_id
        || receipt.phase != desired_phase
        || receipt.terminal_observed != publication.terminal_observed
        || receipt.context_digest.as_deref()
            != Some(publication.owner.context_digest.as_str())
        || receipt.compilation_receipt_digest.as_deref()
            != Some(publication.owner.envelope_digest.as_str())
    {
        return Err("Agentd terminal acknowledgement lost its durable binding".into());
    }
    Ok(receipt.revision)
}
'''
        text = text[:start] + replacement + text[end:]
    elif "publish_pending_intelligence_terminal" not in text:
        raise RuntimeError("terminal outbox: missing legacy publisher and migrated marker")
    return text


def migrate_native_run_control(text: str) -> str:
    old_terminal_reopen = '''            if let Some(output) = record
                .observation
                .as_ref()
                .filter(|output| output.terminal_observed)
            {
                return Ok(output.clone());
            }
'''
    new_terminal_reopen = '''            if let Some(output) = record
                .observation
                .as_ref()
                .filter(|output| output.terminal_observed)
                .cloned()
            {
                self.publish_pending_intelligence_terminal(
                    control,
                    &record.request.request_id,
                )
                .await?;
                return Ok(output);
            }
'''
    text = replace_once(
        text,
        old_terminal_reopen,
        new_terminal_reopen,
        marker="publish_pending_intelligence_terminal(\n                    control,\n                    &record.request.request_id",
    )

    old_reconciled = '''            if let Some(reconciled) = self.reconcile_existing(&record, &prompt).await? {
                let settled = control.settle_native(&record.request.request_id, reconciled)?;
                return settled.observation.ok_or_else(|| {
                    "durable reconciliation omitted its normalized observation".into()
                });
            }
'''
    new_reconciled = '''            if let Some(reconciled) = self.reconcile_existing(&record, &prompt).await? {
                let request_id = record.request.request_id.clone();
                let settled = control.settle_native(&request_id, reconciled)?;
                let output = settled.observation.ok_or_else(|| {
                    "durable reconciliation omitted its normalized observation".into()
                })?;
                self.publish_pending_intelligence_terminal(control, &request_id)
                    .await?;
                return Ok(output);
            }
'''
    text = replace_once(
        text,
        old_reconciled,
        new_reconciled,
        marker="let request_id = record.request.request_id.clone();",
    )

    old_existing = '''            if let Some(output) = record.observation {
                return Ok(output);
            }
'''
    new_existing = '''            if let Some(output) = record.observation {
                self.publish_pending_intelligence_terminal(
                    control,
                    &record.request.request_id,
                )
                .await?;
                return Ok(output);
            }
'''
    text = replace_once(
        text,
        old_existing,
        new_existing,
        marker="if let Some(output) = record.observation {\n                self.publish_pending",
    )

    old_unknown = '''            control.settle_native(&record.request.request_id, output.clone())?;
            return Ok(output);
'''
    new_unknown = '''            control.settle_native(&record.request.request_id, output.clone())?;
            self.publish_pending_intelligence_terminal(
                control,
                &record.request.request_id,
            )
            .await?;
            return Ok(output);
'''
    text = replace_once(
        text,
        old_unknown,
        new_unknown,
        marker="control.settle_native(&record.request.request_id, output.clone())?;\n            self.publish_pending",
    )

    old_fresh = '''                let settled = control.settle_native(&request_id, output)?;
                settled.observation.ok_or_else(|| {
                    "durable execution settlement omitted its normalized observation".into()
                })
'''
    new_fresh = '''                let settled = control.settle_native(&request_id, output)?;
                let output = settled.observation.ok_or_else(|| {
                    "durable execution settlement omitted its normalized observation".into()
                })?;
                self.publish_pending_intelligence_terminal(control, &request_id)
                    .await?;
                Ok(output)
'''
    text = replace_once(
        text,
        old_fresh,
        new_fresh,
        marker="durable execution settlement omitted its normalized observation\".into()\n                })?;",
    )
    return text


def migrate_tests(text: str) -> str:
    if "terminal_outbox_is_atomic_with_observation_and_replayable" in text:
        return text
    addition = r'''

fn terminal_owner() -> NativeTerminalOwnerBinding {
    NativeTerminalOwnerBinding {
        run_id: "agent-run-1".to_string(),
        owner_dispatch_revision: 3,
        context_digest: "8".repeat(64),
        envelope_digest: "9".repeat(64),
    }
}

fn start_bound(control: &mut DurableInferenceControl, id: &str) {
    control.reserve_native(request(id), 1).unwrap();
    let (_, token) = control
        .dispatch_native_with_pre_effect_abort_bound(id, dispatch(), terminal_owner())
        .unwrap();
    drop(token);
    control.native_started(id, "turn-1".to_string()).unwrap();
}

#[test]
fn terminal_outbox_is_atomic_with_observation_and_replayable() {
    let path = path("terminal-outbox");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    start_bound(&mut control, "r1");
    let mut observed = output(NativeRunStatus::Completed, Some(5));
    observed.owner_authority = NativeOwnerAuthority::ObservedReady;
    let settled = control.settle_native("r1", observed).unwrap();
    let publication = settled.terminal_publication.clone().unwrap();
    assert_eq!(publication.phase, NativeTerminalPublicationPhase::Succeeded);
    assert!(publication.terminal_observed);
    assert!(publication.pending());
    drop(control);

    let mut reopened = DurableInferenceControl::open(&path, 8).unwrap();
    let replayed = reopened
        .native_record("r1")
        .unwrap()
        .terminal_publication
        .clone()
        .unwrap();
    assert_eq!(replayed, publication);
    reopened
        .record_native_terminal_publication_failure(
            "r1",
            &publication.publication_digest,
            &"7".repeat(64),
        )
        .unwrap();
    let acknowledged = reopened
        .acknowledge_native_terminal_publication(
            "r1",
            &publication.publication_digest,
            4,
        )
        .unwrap();
    let publication = acknowledged.terminal_publication.unwrap();
    assert_eq!(publication.attempts, 2);
    assert_eq!(publication.acknowledged_revision, Some(4));
    assert!(!publication.pending());
    drop(reopened);

    let reopened = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(
        reopened
            .native_record("r1")
            .unwrap()
            .terminal_publication
            .as_ref()
            .unwrap()
            .acknowledged_revision,
        Some(4)
    );
    drop(reopened);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn late_completed_under_non_success_boundaries_never_publishes_success() {
    for (label, boundary) in [
        ("cancelled", NativeBoundaryStatus::Cancelled),
        ("timed-out", NativeBoundaryStatus::TimedOut),
        ("quarantined", NativeBoundaryStatus::Quarantined),
    ] {
        let path = path(label);
        let mut control = DurableInferenceControl::open(&path, 8).unwrap();
        start_bound(&mut control, "r1");
        let mut observed = output(NativeRunStatus::Completed, Some(1));
        observed.boundary_status = boundary;
        observed.stop_reason = Some(label.to_string());
        observed.owner_authority = if boundary == NativeBoundaryStatus::Quarantined {
            NativeOwnerAuthority::Lost {
                reason: "owner lost".to_string(),
            }
        } else {
            NativeOwnerAuthority::ObservedReady
        };
        let settled = control.settle_native("r1", observed).unwrap();
        let publication = settled.terminal_publication.unwrap();
        assert_ne!(publication.phase, NativeTerminalPublicationPhase::Succeeded);
        assert_eq!(publication.phase, NativeTerminalPublicationPhase::Indeterminate);
        assert!(!publication.terminal_observed);
        drop(control);
        std::fs::remove_file(path).unwrap();
    }
}
'''
    return text.rstrip() + addition + "\n"


def main() -> None:
    rewrite("codex-rs/hepta-infer-core/src/native_control.rs", migrate_native_control)
    rewrite("codex-rs/hepta-infer-core/src/native_control_tests.rs", migrate_tests)
    rewrite("codex-rs/hepta-infer-worker-host/src/native_app_server.rs", migrate_native_imports)
    rewrite("codex-rs/hepta-infer-worker-host/src/native_app_server.rs", migrate_native_app_server)
    rewrite("codex-rs/hepta-infer-worker-host/src/native_execution.rs", migrate_native_execution)
    rewrite("codex-rs/hepta-infer-worker-host/src/native_run_control.rs", migrate_native_run_control)


if __name__ == "__main__":
    main()
