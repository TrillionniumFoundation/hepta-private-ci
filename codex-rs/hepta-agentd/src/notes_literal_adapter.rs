//! Finite literal Notes preparation in the original Agentd process. The only
//! untrusted inputs are a navigation ID and document text. Original Root, writer,
//! observer, checkpoint and signer handles are retained from one composition.

use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_memory::ObjectiveSenderOrigin;
use codex_hepta_memory::ObjectiveSenderRequest;
use codex_hepta_memory::ObjectiveSenderTicket;
use codex_hepta_memory::ProductionDurableWriter;
use codex_hepta_memory::ProductionObjectiveSender;
use codex_hepta_memory::ProtectedCognitiveCheckpoint;
use codex_hepta_objective::LiteralNotesSourceContext;
use codex_hepta_objective::MAX_OBJECTIVE_ADMISSION_PROFILE_JSON_BYTES;
use codex_hepta_objective::decode_admission_profile_json_v1;
use codex_hepta_objective::literal_notes_admission_profile_json_v1;
use codex_hepta_objective::literal_notes_source_json_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use tokio::sync::Semaphore;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdNotesDocumentObserver;
use crate::AgentdNotesObjectiveConfig;
use crate::AgentdRootAuthoritySession;
use crate::AgentdRootProductionAttachment;
use crate::AgentdUnixCognitiveCheckpointTransport;
use crate::AgentdUnixFinalUseGrantProvider;
use crate::AuthBusObjectiveBody;
use crate::AuthBusObjectiveIngress;
use crate::notes_literal_prepare::LiteralOperationInput;
use crate::notes_literal_prepare::prepare_original_literal;
use crate::notes_literal_prepare::utc_millis;

#[path = "notes_literal_read.rs"]
mod read;
pub use read::AgentdNotesRetainedIntents;
#[path = "notes_literal_history.rs"]
mod history;
#[path = "notes_ui_runtime.rs"]
mod ui_runtime;
pub use ui_runtime::AgentdNotesUiRuntime;
#[path = "notes_ui_worker.rs"]
mod ui_worker;

type RootCheckpoint = ProtectedCognitiveCheckpoint<AgentdUnixCognitiveCheckpointTransport>;

/// Ephemeral view diagnostics only, never a permit or persistent state.
enum NotesUiCallPhase {
    ReadOnly,
    Preparing,
    Sending,
}

/// Frozen deployment data, supplied by the trusted launcher, never UI IPC.
/// The five artifact/runtime digests must name actual retained source inputs.
/// No default or fabricated model identity is supplied for this no-model action.
pub struct AgentdNotesLiteralBindings {
    pub principal_scope: String,
    pub principal_scope_digest: Digest32,
    pub issuer_id: String,
    pub policy_generation: Generation,
    pub locale: String,
    pub runtime_body_digest: Digest32,
    pub preference_state_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub prompt_registry_digest: Digest32,
    pub artifact_set_digest: Digest32,
}

/// Private host result, never a renderer message. A retained request is only
/// read/reconciled; it has no new sending permission. `Ready` already occupies
/// the original durable sender fence. `submit_once` consumes that exact sender's
/// permission before authenticated original control I/O, then retains the
/// observation. Losing this result never rearms the request.
pub enum AgentdNotesPreparedObjective {
    Retained(ObjectiveSenderRequest),
    Ready {
        sender: Arc<ProductionObjectiveSender<RootCheckpoint>>,
        ticket: ObjectiveSenderTicket,
        ingress: AuthBusObjectiveIngress,
    },
}

/// One non-cloneable preparation capability, with one bounded blocking slot.
/// The slot remains held by started observation/signing work after cancellation.
/// It owns no database, nonce, request-ID mapping or parallel admission ledger.
#[derive(Clone, Copy, PartialEq, Eq)]
pub(crate) enum NotesAdapterProfile {
    Literal,
    OriginalThread,
}

pub struct AgentdNotesLiteralAdapter {
    pub(crate) identity: AgentdIdentity,
    pub(crate) writer: Arc<ProductionDurableWriter>,
    sender: Arc<ProductionObjectiveSender<RootCheckpoint>>,
    root: Arc<AgentdRootAuthoritySession>,
    pub(crate) observer: AgentdNotesDocumentObserver,
    grants: Arc<AgentdUnixFinalUseGrantProvider>,
    pub(crate) bindings: AgentdNotesLiteralBindings,
    input_schema_digest: Digest32,
    normalization_digest: Digest32,
    pub(crate) blocking: Arc<Semaphore>,
    pub(crate) deadline: Duration,
    profile: NotesAdapterProfile,
    next_request: u64,
}

impl AgentdConfig {
    /// Register the exact existing finite profile and retain the same original
    /// writer's sender. The caller installs the adapter into the original
    /// required Notes UI runtime; another process cannot reconstruct it from
    /// files or the public target.
    pub fn with_root_notes_literal_adapter(
        self,
        attachment: &AgentdRootProductionAttachment,
        bindings: AgentdNotesLiteralBindings,
        deadline: Duration,
    ) -> Result<(Self, AgentdNotesLiteralAdapter), AgentdError> {
        self.with_root_notes_adapter(attachment, bindings, deadline, NotesAdapterProfile::Literal)
    }

    pub(crate) fn with_root_notes_adapter(
        self,
        attachment: &AgentdRootProductionAttachment,
        bindings: AgentdNotesLiteralBindings,
        deadline: Duration,
        profile: NotesAdapterProfile,
    ) -> Result<(Self, AgentdNotesLiteralAdapter), AgentdError> {
        if deadline.is_zero()
            || deadline > Duration::from_secs(10)
            || !matches!(bindings.locale.as_str(), "en-US" | "zh-CN")
            || [
                bindings.runtime_body_digest,
                bindings.preference_state_digest,
                bindings.model_tuple_digest,
                bindings.prompt_registry_digest,
                bindings.artifact_set_digest,
            ]
            .into_iter()
            .any(Digest32::is_zero)
        {
            return Err(invalid("missing or invalid frozen Notes runtime bindings"));
        }
        let observer = attachment
            .notes
            .clone()
            .ok_or_else(|| invalid("actual Session Notes observer is absent"))?;
        let host = self
            .production_writer_host()
            .ok_or(AgentdError::CognitiveWriteRuntimeUnavailable)?;
        let writer = host.writer();
        if writer.authority() != &attachment.root_session.authority()
            || writer.owner_agent_id() != &self.identity().agent_id
            || host.spawn_generation() != self.identity().spawn_generation
        {
            return Err(invalid(
                "Notes Root attachment differs from installed writer",
            ));
        }
        let encode_profile = match profile {
            NotesAdapterProfile::Literal => literal_notes_admission_profile_json_v1,
            NotesAdapterProfile::OriginalThread => {
                codex_hepta_objective::thread_notes_admission_profile_json_v1
            }
        };
        let expected = encode_profile(
            &bindings.principal_scope,
            bindings.principal_scope_digest,
            &bindings.issuer_id,
        )
        .map_err(AgentdError::Invalid)?;
        let expected = decode_admission_profile_json_v1(expected.as_bytes())
            .map_err(|error| invalid(&error.to_string()))?;
        let path = self
            .objective_profile_file()
            .ok_or_else(|| invalid("original finite Notes profile file is absent"))?;
        let bytes = crate::authbus_trust::read_private_owner_file(
            path,
            self.identity(),
            MAX_OBJECTIVE_ADMISSION_PROFILE_JSON_BYTES as u64,
        )?;
        let selected = decode_admission_profile_json_v1(&bytes)
            .map_err(|error| invalid(&error.to_string()))?;
        if selected != expected {
            return Err(invalid(
                "selected Objective profile differs from literal Notes compiler",
            ));
        }
        let profile_digest = selected
            .digest()
            .map_err(|error| invalid(&error.to_string()))?;
        let sender =
            self.original_objective_sender(Arc::clone(&attachment.checkpoint), deadline)?;
        let identity = self.identity().clone();
        let configured = self.with_notes_objective(AgentdNotesObjectiveConfig {
            profile_digest,
            target: observer.target().clone(),
        })?;
        let adapter = AgentdNotesLiteralAdapter {
            identity,
            writer,
            sender: Arc::new(sender),
            root: Arc::clone(&attachment.root_session),
            observer,
            grants: Arc::clone(&attachment.grants),
            bindings,
            input_schema_digest: selected.expected_input_schema_digest,
            normalization_digest: selected.expected_normalization_profile_digest,
            blocking: Arc::new(Semaphore::new(1)),
            deadline,
            profile,
            next_request: 1,
        };
        adapter.check_available()?;
        Ok((configured, adapter))
    }
}

impl AgentdNotesLiteralAdapter {
    /// Pure deterministic projection in this persistent original owner/scope.
    /// Reusing an ID recovers the first original request and never changes text.
    pub fn run_id(&self, client_intent_id: &str) -> Result<String, AgentdError> {
        if client_intent_id.is_empty()
            || client_intent_id.len() > 96
            || !client_intent_id
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"-_".contains(&byte))
        {
            return Err(invalid("invalid Notes client intent ID"));
        }
        let (domain, prefix) = match self.profile {
            NotesAdapterProfile::Literal => ("organ.notes.literal.run.v1", "notes.literal"),
            NotesAdapterProfile::OriginalThread => {
                ("organ.notes.thread-tool.run.v1", "notes.thread")
            }
        };
        let binding = serde_json::to_vec(&(
            domain,
            self.identity.agent_id.as_str(),
            self.bindings.principal_scope_digest.to_string(),
            client_intent_id,
        ))?;
        Ok(format!("{prefix}.{}", Digest32::of_bytes(&binding)))
    }

    pub(crate) async fn retained_thread_request_sha256(
        &self,
        client_intent_id: &str,
    ) -> Result<String, AgentdError> {
        let run_id = self.run_id(client_intent_id)?;
        let request = self
            .sender
            .retained_request_for_run(&run_id)
            .await
            .map_err(|error| invalid(&error.to_string()))?
            .ok_or_else(|| invalid("original thread request was not retained"))?;
        Ok(request.identity().original_sha256.as_str().to_owned())
    }

    pub fn check_available(&self) -> Result<(), AgentdError> {
        if self.writer.checkpoint_fenced() {
            return Err(invalid(
                "original Notes writer is permanently checkpoint-fenced",
            ));
        }
        self.root
            .verifier()
            .verify(self.writer.authority(), &self.identity.agent_id)
            .map_err(AgentdError::GenerationFenced)
    }

    /// Retain before returning any signed ingress. This never calls a device,
    /// creates a FinalUse grant, dispatches an outbox row or submits Objective.
    /// A timeout/failed sign may leave original durable preparation; retry can
    /// only observe that owner, and an already retained request is not reissued.
    pub async fn prepare(
        &mut self,
        client_intent_id: &str,
        text: &str,
    ) -> Result<AgentdNotesPreparedObjective, AgentdError> {
        let end = Instant::now() + self.deadline;
        let mut phase = NotesUiCallPhase::ReadOnly;
        tokio::time::timeout_at(
            end.into(),
            self.prepare_until(client_intent_id, text, end, &mut phase),
        )
        .await
        .map_err(|_| invalid("Notes original preparation acknowledgement unknown"))?
    }

    async fn prepare_until(
        &mut self,
        client_intent_id: &str,
        text: &str,
        end: Instant,
        phase: &mut NotesUiCallPhase,
    ) -> Result<AgentdNotesPreparedObjective, AgentdError> {
        if self.profile != NotesAdapterProfile::Literal {
            return Err(invalid("literal UI cannot prepare a model tool operation"));
        }
        self.prepare_bound(client_intent_id, text, None, end, phase)
            .await
    }

    pub(crate) async fn prepare_thread(
        &mut self,
        client_intent_id: &str,
        text: &str,
        expected_revision: u64,
    ) -> Result<AgentdNotesPreparedObjective, AgentdError> {
        if self.profile != NotesAdapterProfile::OriginalThread {
            return Err(invalid(
                "model tool cannot use the no-model literal profile",
            ));
        }
        let end = Instant::now() + self.deadline;
        let mut phase = NotesUiCallPhase::ReadOnly;
        tokio::time::timeout_at(
            end.into(),
            self.prepare_bound(
                client_intent_id,
                text,
                Some(expected_revision),
                end,
                &mut phase,
            ),
        )
        .await
        .map_err(|_| invalid("original thread preparation acknowledgement unknown"))?
    }

    async fn prepare_bound(
        &mut self,
        client_intent_id: &str,
        text: &str,
        expected_revision: Option<u64>,
        end: Instant,
        phase: &mut NotesUiCallPhase,
    ) -> Result<AgentdNotesPreparedObjective, AgentdError> {
        let run_id = self.run_id(client_intent_id)?;
        if let Some(retained) = self
            .sender
            .retained_request_for_run(&run_id)
            .await
            .map_err(|error| invalid(&error.to_string()))?
        {
            if let Some(expected_revision) = expected_revision {
                let original = self
                    .writer
                    .retained_operation(&run_id)
                    .await?
                    .ok_or_else(|| {
                        invalid("retained thread request lost its original operation")
                    })?;
                let payload: serde_json::Value = serde_json::from_str(&original.payload_json)?;
                if payload["text"].as_str() != Some(text)
                    || payload["expected_revision"].as_u64() != Some(expected_revision)
                {
                    return Err(invalid(
                        "original thread call was rebound to different arguments",
                    ));
                }
            }
            return Ok(AgentdNotesPreparedObjective::Retained(retained));
        }
        self.check_available()?;
        // Startup cannot consume a durable send opportunity while the original
        // control listener/profile is still unavailable. This is a bounded,
        // authenticated read-only query, not a delivery attempt or retry.
        self.require_objective_ready().await?;
        if text.trim().is_empty() || text.len() > 4096 {
            return Err(invalid("literal Notes text exceeds original bounds"));
        }
        let permit = Arc::clone(&self.blocking)
            .try_acquire_owned()
            .map_err(|_| invalid("previous Notes blocking work is still in progress"))?;
        let observer = self.observer.clone();
        let observed = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            if Instant::now() >= end {
                return Err(invalid("Notes observation deadline elapsed"));
            }
            observer.observe_document()
        })
        .await
        .map_err(|_| invalid("Notes observation worker failed"))??;
        self.check_available()?;
        if expected_revision.is_some_and(|revision| revision != observed.revision) {
            return Err(invalid(
                "original thread predecessor changed; no operation was prepared",
            ));
        }
        let now_ms = self
            .root
            .clock()
            .now_unix_ms()
            .map_err(|_| invalid("protected Root clock unavailable"))?;
        let source_deadline = now_ms
            .checked_add(5_000)
            .ok_or_else(|| invalid("Notes source deadline overflow"))?;
        if Instant::now() >= end {
            return Err(invalid(
                "Notes deadline elapsed before original preparation",
            ));
        }
        *phase = NotesUiCallPhase::Preparing;
        let semantic = prepare_original_literal(
            &self.writer,
            LiteralOperationInput {
                target: self.observer.target(),
                observed: &observed,
                run_id: &run_id,
                text,
                subject: self.identity.agent_id.as_str(),
                policy_generation: self.bindings.policy_generation,
            },
        )
        .await?;
        let encode_source = match self.profile {
            NotesAdapterProfile::Literal => literal_notes_source_json_v1,
            NotesAdapterProfile::OriginalThread => {
                codex_hepta_objective::thread_notes_source_json_v1
            }
        };
        let source = encode_source(LiteralNotesSourceContext {
            client_intent_id,
            source_digest: semantic,
            principal_scope_digest: self.bindings.principal_scope_digest,
            locale: &self.bindings.locale,
            observed_at: &utc_millis(now_ms)?,
            deadline: &utc_millis(source_deadline)?,
        })
        .map_err(AgentdError::Invalid)?;
        let body = AuthBusObjectiveBody {
            spawn_generation: self.identity.spawn_generation,
            run_id,
            objective_revision: 1,
            source_envelope_json: source,
            runtime_body_digest: self.bindings.runtime_body_digest.to_string(),
            preference_state_digest: self.bindings.preference_state_digest.to_string(),
            model_tuple_digest: self.bindings.model_tuple_digest.to_string(),
            prompt_registry_digest: self.bindings.prompt_registry_digest.to_string(),
            artifact_set_digest: self.bindings.artifact_set_digest.to_string(),
            authority_epoch: self.root.authority().authority_epoch,
        };
        let permit = Arc::clone(&self.blocking)
            .try_acquire_owned()
            .map_err(|_| invalid("Notes signer slot is occupied"))?;
        let grants = Arc::clone(&self.grants);
        let root = Arc::clone(&self.root);
        let signed = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            if Instant::now() >= end
                || root
                    .clock()
                    .now_unix_ms()
                    .map_err(|_| invalid("Root clock unavailable before sign"))?
                    >= source_deadline
            {
                return Err(invalid("Notes source expired before Root signing"));
            }
            grants
                .sign_objective(&body)
                .map_err(|error| invalid(&error.to_string()))
        })
        .await
        .map_err(|_| invalid("Notes Root signing worker failed"))??;
        self.check_available()?;
        if signed.issuer_id != self.bindings.issuer_id
            || self
                .root
                .clock()
                .now_unix_ms()
                .map_err(|_| invalid("Root clock unavailable after sign"))?
                >= source_deadline
        {
            return Err(invalid(
                "Notes signed ingress expired or differs from frozen issuer",
            ));
        }
        let origin = self.next_origin()?;
        let request =
            ObjectiveSenderRequest::from_original(serde_json::to_string(&signed)?, origin)
                .map_err(|error| invalid(&error.to_string()))?;
        let ticket = self
            .sender
            .retain_before_send(request)
            .await
            .map_err(|error| invalid(&error.to_string()))?;
        self.check_available()?;
        if self
            .root
            .clock()
            .now_unix_ms()
            .map_err(|_| invalid("Root clock unavailable after sender retention"))?
            >= source_deadline
        {
            return Err(invalid(
                "Notes source expired during original sender acknowledgement",
            ));
        }
        Ok(AgentdNotesPreparedObjective::Ready {
            sender: Arc::clone(&self.sender),
            ticket,
            ingress: signed,
        })
    }
}

pub(crate) fn invalid(message: &str) -> AgentdError {
    AgentdError::Invalid(format!("original literal Notes: {message}"))
}
