//! Qualification-only host-bound turn writer.
//!
//! This is the narrow bridge between the host's explicit turn binding and the
//! Agent-local SQLite lease/event/outbox journal.  It is intentionally a
//! lifecycle contributor, but it never invents a binding: the host must attach
//! a [`QualificationTurnWriterInput`] to the turn store before the callback is
//! invoked.  Missing, malformed, stale, or cross-store inputs are ignored by
//! the callback (the extension API has no error channel) and are exposed as
//! errors by the input constructor/host helpers.
//!
//! The contributor is not installed by `install`.  A qualification embedding
//! may register it explicitly after it has supplied the host-bound input.  The
//! default and production extension profiles therefore cannot acquire a lease
//! or append an outbox row accidentally.

use std::fmt;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::PoisonError;
use std::time::Duration;

use codex_extension_api::ExtensionData;
use codex_extension_api::ExtensionDataInit;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::QualificationTurnAdmissionIdentity;
use codex_extension_api::ThreadLifecycleContributor;
use codex_extension_api::ThreadStartInput;
use codex_extension_api::TurnAbortInput;
use codex_extension_api::TurnErrorInput;
use codex_extension_api::TurnLifecycleContributor;
use codex_extension_api::TurnStartGate;
use codex_extension_api::TurnStartInput;
use codex_extension_api::TurnStartOrigin;
use codex_extension_api::TurnStopInput;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::H7TrajectoryEventKind;
use codex_hepta_memory::H7TrajectoryRecord;
use codex_hepta_memory::LocalAdmission;
use codex_hepta_memory::LocalCompactExecutor;
use codex_hepta_memory::LocalCompactExecutorError;
use codex_hepta_memory::LocalLeaseOutbox;
use codex_hepta_memory::LocalLeaseOutboxError;
use codex_hepta_memory::LocalReplayFinalization;
use codex_hepta_memory::LocalTurnLifecycleBinding;
use codex_hepta_memory::LocalTurnLifecycleBindingError;
use codex_hepta_memory::QueuedReceipt;
use codex_hepta_memory::append_h7_trajectory_event_bound;
use codex_hepta_memory::h7_trajectory_local_receipt_digest;
use codex_hepta_memory::read_h7_trajectory_bound_for_recovery;

/// Schema version for the qualification-only turn writer payload.
pub const QUALIFICATION_TURN_WRITER_SCHEMA_VERSION: u32 = 1;
/// This writer never dispatches its local outbox.
pub const QUALIFICATION_TURN_WRITER_EXTERNAL_EFFECTS: bool = false;
/// The writer records lifecycle metadata only; it does not mutate the KG.
pub const QUALIFICATION_TURN_WRITER_KG_WRITE_AUTHORITY: bool = false;
/// The contributor is opt-in and is not automatically registered.
pub const QUALIFICATION_TURN_WRITER_LIFECYCLE_REGISTERED: bool = false;
/// The writer is never a production caller.
pub const QUALIFICATION_TURN_WRITER_PRODUCTION_CALLER: bool = false;

const TURN_START_TOPIC: &str = "codex.turn.qualification.start.v1";
const IO_TIMEOUT: Duration = Duration::from_millis(750);
const MAX_OCCURRENCE_KEY_BYTES: usize = 512;

fn bounded_terminal_reason(reason: &str) -> String {
    if reason.len() <= 512 && !reason.as_bytes().contains(&0) {
        return reason.to_string();
    }
    format!(
        "reason_sha256:{}",
        Sha256Digest::for_bytes(reason.as_bytes()).as_str()
    )
}

fn bounded_terminal_occurrence_key(occurrence_key: &str) -> String {
    const SUFFIX: &str = ":terminal";
    if occurrence_key.len() + SUFFIX.len() <= MAX_OCCURRENCE_KEY_BYTES {
        return format!("{occurrence_key}{SUFFIX}");
    }
    format!(
        "qualification:terminal-occurrence:{}",
        Sha256Digest::for_bytes(occurrence_key.as_bytes()).as_str()
    )
}

/// Errors found while constructing the immutable host attachment.
#[derive(Debug)]
pub enum QualificationTurnWriterInputError {
    Binding(LocalTurnLifecycleBindingError),
    Lease(LocalLeaseOutboxError),
    Executor(LocalCompactExecutorError),
    Invalid(String),
}

impl fmt::Display for QualificationTurnWriterInputError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Binding(error) => write!(formatter, "turn binding rejected: {error}"),
            Self::Lease(error) => write!(formatter, "turn lease rejected: {error}"),
            Self::Executor(error) => write!(formatter, "turn executor rejected: {error}"),
            Self::Invalid(error) => write!(formatter, "invalid turn writer input: {error}"),
        }
    }
}

impl std::error::Error for QualificationTurnWriterInputError {}

impl From<LocalTurnLifecycleBindingError> for QualificationTurnWriterInputError {
    fn from(error: LocalTurnLifecycleBindingError) -> Self {
        Self::Binding(error)
    }
}

impl From<LocalLeaseOutboxError> for QualificationTurnWriterInputError {
    fn from(error: LocalLeaseOutboxError) -> Self {
        Self::Lease(error)
    }
}

impl From<LocalCompactExecutorError> for QualificationTurnWriterInputError {
    fn from(error: LocalCompactExecutorError) -> Self {
        Self::Executor(error)
    }
}

/// Future returned by an embedding-owned qualification writer factory.
pub type QualificationTurnWriterPrepareFuture = Pin<
    Box<
        dyn Future<Output = Result<QualificationTurnWriterInput, QualificationTurnWriterInputError>>
            + Send
            + 'static,
    >,
>;

type QualificationTurnWriterPrepareFn = dyn Fn(QualificationTurnWriterPrepareRequest) -> QualificationTurnWriterPrepareFuture
    + Send
    + Sync
    + 'static;

/// Stable host-supplied identity material for one qualification turn.
///
/// `turn_id` is the physical callback key.  The other fields are deliberately
/// supplied by the embedding so a future spawn can present the same logical
/// identity while minting fresh attempt-scoped lease/journal/trajectory IDs.
/// The default constructor is only a compatibility bridge for older
/// embeddings; the Agentd qualification host replaces these values with its
/// canonical local contract before reserving the registry entry.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QualificationTurnWriterPrepareRequest {
    pub turn_id: String,
    pub logical_turn_id: String,
    pub logical_scope_key: String,
    pub logical_binding_sha256: Sha256Digest,
    /// `true` only when Core supplied a durable client/input admission
    /// identity.  Legacy direct/recovery callers may still use `for_turn`,
    /// but Agentd's runtime host refuses to treat that fallback as a
    /// cross-spawn identity.
    pub durable_admission: bool,
}

impl QualificationTurnWriterPrepareRequest {
    pub fn for_turn(turn_id: impl Into<String>) -> Self {
        let turn_id = turn_id.into();
        Self {
            logical_turn_id: format!("qualification:logical:{turn_id}"),
            logical_scope_key: "qualification:local".to_string(),
            logical_binding_sha256: Sha256Digest::for_bytes(
                format!("qualification:logical-binding:v1:{turn_id}").as_bytes(),
            ),
            turn_id,
            durable_admission: false,
        }
    }

    pub fn from_admission(
        turn_id: impl Into<String>,
        identity: &QualificationTurnAdmissionIdentity,
    ) -> Self {
        let turn_id = turn_id.into();
        // Length-frame each component so caller-controlled scope/message IDs
        // cannot alias one another through delimiter ambiguity (for example,
        // `a:b` + `c` versus `a` + `b:c`).  The payload digest remains in the
        // immutable binding, while the stable logical ID is intentionally
        // content-independent so a retry with a changed payload is a durable
        // conflict rather than a new logical turn.
        let stable_suffix = qualification_identity_digest(
            b"hepta-agentd:qualification-logical:v3",
            &[
                identity.thread_scope_key.as_str(),
                identity.client_user_message_id.as_str(),
            ],
        );
        let binding = qualification_identity_digest(
            b"hepta-agentd:qualification-binding:v3",
            &[
                identity.thread_scope_key.as_str(),
                identity.client_user_message_id.as_str(),
                identity.payload_sha256.as_str(),
            ],
        );
        let scope_suffix = qualification_identity_digest(
            b"hepta-agentd:qualification-scope:v3",
            &[identity.thread_scope_key.as_str()],
        );
        Self {
            logical_turn_id: format!("qualification:logical:{}", stable_suffix.as_str()),
            logical_scope_key: format!("qualification:thread:{}", scope_suffix.as_str()),
            logical_binding_sha256: binding,
            turn_id,
            durable_admission: true,
        }
    }
}

fn qualification_identity_digest(domain: &[u8], parts: &[&str]) -> Sha256Digest {
    let mut bytes = Vec::with_capacity(
        domain.len()
            + parts
                .iter()
                .map(|part| std::mem::size_of::<u64>() + part.len())
                .sum::<usize>(),
    );
    bytes.extend_from_slice(&(domain.len() as u64).to_be_bytes());
    bytes.extend_from_slice(domain);
    for part in parts {
        bytes.extend_from_slice(&(part.len() as u64).to_be_bytes());
        bytes.extend_from_slice(part.as_bytes());
    }
    Sha256Digest::for_bytes(&bytes)
}

/// Explicit host capability for preparing one fully bound local turn input.
///
/// The host callback owns the authority contract.  It must return an input
/// containing a validated [`LocalTurnLifecycleBinding`] and exact lease and
/// compact-executor handles; this type never invents epochs, generations,
/// fencing tokens, leases, or expiry values.  A missing capability means the
/// qualification writer remains inert.
#[derive(Clone)]
pub struct QualificationTurnWriterHost {
    capability_id: Arc<str>,
    prepare: Arc<QualificationTurnWriterPrepareFn>,
}

impl fmt::Debug for QualificationTurnWriterHost {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("QualificationTurnWriterHost")
            .field("capability_id", &self.capability_id)
            .finish_non_exhaustive()
    }
}

impl PartialEq for QualificationTurnWriterHost {
    fn eq(&self, other: &Self) -> bool {
        self.capability_id == other.capability_id && Arc::ptr_eq(&self.prepare, &other.prepare)
    }
}

impl Eq for QualificationTurnWriterHost {}

impl QualificationTurnWriterHost {
    /// Build a host capability from an embedding-owned asynchronous factory.
    ///
    /// `capability_id` is diagnostic provenance only; it does not grant
    /// authority and is intentionally not used to derive any fence value.
    pub fn from_fn<F, Fut>(capability_id: impl Into<String>, prepare: F) -> Self
    where
        F: Fn(String) -> Fut + Send + Sync + 'static,
        Fut: Future<Output = Result<QualificationTurnWriterInput, QualificationTurnWriterInputError>>
            + Send
            + 'static,
    {
        Self {
            capability_id: Arc::from(capability_id.into()),
            prepare: Arc::new(move |request| Box::pin(prepare(request.turn_id))),
        }
    }

    /// Build a host capability whose callback receives the stable logical
    /// identity supplied by the embedding.
    pub fn from_request_fn<F, Fut>(capability_id: impl Into<String>, prepare: F) -> Self
    where
        F: Fn(QualificationTurnWriterPrepareRequest) -> Fut + Send + Sync + 'static,
        Fut: Future<Output = Result<QualificationTurnWriterInput, QualificationTurnWriterInputError>>
            + Send
            + 'static,
    {
        Self {
            capability_id: Arc::from(capability_id.into()),
            prepare: Arc::new(move |request| Box::pin(prepare(request))),
        }
    }

    pub fn capability_id(&self) -> &str {
        &self.capability_id
    }

    async fn prepare(
        &self,
        turn_id: &str,
    ) -> Result<QualificationTurnWriterInput, QualificationTurnWriterInputError> {
        self.prepare_with_request(QualificationTurnWriterPrepareRequest::for_turn(turn_id))
            .await
    }

    async fn prepare_with_request(
        &self,
        request: QualificationTurnWriterPrepareRequest,
    ) -> Result<QualificationTurnWriterInput, QualificationTurnWriterInputError> {
        let turn_id = request.turn_id.clone();
        let input = (self.prepare)(request).await?;
        input.validate_for_turn(&turn_id)?;
        Ok(input)
    }
}

/// Seed a host capability into a thread's extension initializer.
///
/// The operation is append-only for this capability type: an embedding cannot
/// replace a capability that another owner already supplied.
pub fn insert_qualification_turn_writer_host(
    init: &mut ExtensionDataInit,
    host: QualificationTurnWriterHost,
) -> bool {
    init.insert(host).is_none()
}

/// Immutable host-supplied input for one turn writer invocation.
///
/// The lease and compact executor are cloned handles to the same Agent-local
/// store.  [`LocalTurnLifecycleBinding`] is derived from those exact handles,
/// so an input cannot be constructed from guessed epochs or a legacy lease.
#[derive(Clone)]
pub struct QualificationTurnWriterInput {
    pub schema_version: u32,
    pub turn_id: String,
    /// Attempt-scoped H7 trajectory identity.  It must not be reconstructed
    /// from the stable turn id when a logical turn is taken over by a new
    /// Agentd spawn.
    pub trajectory_id: String,
    pub binding: LocalTurnLifecycleBinding,
    pub occurrence_key: String,
    pub payload_json: String,
    pub lease: LocalLeaseOutbox,
    pub executor: LocalCompactExecutor,
}

impl QualificationTurnWriterInput {
    /// Build an input from exact host-owned handles and a binding made from
    /// those handles.  No database mutation occurs here.
    pub fn new(
        turn_id: impl Into<String>,
        binding: LocalTurnLifecycleBinding,
        lease: LocalLeaseOutbox,
        executor: LocalCompactExecutor,
        occurrence_key: impl Into<String>,
        payload_json: impl Into<String>,
    ) -> Result<Self, QualificationTurnWriterInputError> {
        let turn_id = turn_id.into();
        let trajectory_id = format!("qualification:trajectory:{turn_id}");
        Self::new_with_trajectory(
            turn_id,
            trajectory_id,
            binding,
            lease,
            executor,
            occurrence_key,
            payload_json,
        )
    }

    /// Build an input with an explicit physical-attempt trajectory identity.
    /// The legacy [`Self::new`] constructor remains available for standalone
    /// extension tests, while Agentd's stable logical registry always uses
    /// this constructor.
    pub fn new_with_trajectory(
        turn_id: impl Into<String>,
        trajectory_id: impl Into<String>,
        binding: LocalTurnLifecycleBinding,
        lease: LocalLeaseOutbox,
        executor: LocalCompactExecutor,
        occurrence_key: impl Into<String>,
        payload_json: impl Into<String>,
    ) -> Result<Self, QualificationTurnWriterInputError> {
        let turn_id = turn_id.into();
        let trajectory_id = trajectory_id.into();
        let occurrence_key = occurrence_key.into();
        let payload_json = payload_json.into();
        binding.validate()?;
        if binding.turn_id != turn_id {
            return Err(QualificationTurnWriterInputError::Invalid(
                "binding turn id does not match input turn id".to_string(),
            ));
        }
        if occurrence_key.trim().is_empty()
            || occurrence_key.len() > MAX_OCCURRENCE_KEY_BYTES
            || occurrence_key.as_bytes().contains(&0)
        {
            return Err(QualificationTurnWriterInputError::Invalid(
                "occurrence key must contain 1..=512 non-NUL bytes".to_string(),
            ));
        }
        if trajectory_id.trim().is_empty()
            || trajectory_id.len() > MAX_OCCURRENCE_KEY_BYTES
            || trajectory_id.as_bytes().contains(&0)
        {
            return Err(QualificationTurnWriterInputError::Invalid(
                "trajectory id must contain 1..=512 non-NUL bytes".to_string(),
            ));
        }
        if payload_json.trim().is_empty()
            || payload_json.len() > 65_536
            || payload_json.as_bytes().contains(&0)
        {
            return Err(QualificationTurnWriterInputError::Invalid(
                "payload must contain 1..=65536 non-NUL bytes".to_string(),
            ));
        }
        Ok(Self {
            schema_version: QUALIFICATION_TURN_WRITER_SCHEMA_VERSION,
            turn_id,
            trajectory_id,
            binding,
            occurrence_key,
            payload_json,
            lease,
            executor,
        })
    }

    fn validate_for_turn(&self, turn_id: &str) -> Result<(), QualificationTurnWriterInputError> {
        if self.schema_version != QUALIFICATION_TURN_WRITER_SCHEMA_VERSION {
            return Err(QualificationTurnWriterInputError::Invalid(
                "unsupported writer input schema".to_string(),
            ));
        }
        if self.turn_id != turn_id || self.binding.turn_id != turn_id {
            return Err(QualificationTurnWriterInputError::Invalid(
                "writer input is bound to a different turn".to_string(),
            ));
        }
        self.binding.validate()?;
        if self.trajectory_id.trim().is_empty()
            || self.trajectory_id.len() > MAX_OCCURRENCE_KEY_BYTES
            || self.trajectory_id.as_bytes().contains(&0)
        {
            return Err(QualificationTurnWriterInputError::Invalid(
                "trajectory id must contain 1..=512 non-NUL bytes".to_string(),
            ));
        }
        if self.occurrence_key.trim().is_empty()
            || self.occurrence_key.len() > MAX_OCCURRENCE_KEY_BYTES
            || self.occurrence_key.as_bytes().contains(&0)
        {
            return Err(QualificationTurnWriterInputError::Invalid(
                "occurrence key must contain 1..=512 non-NUL bytes".to_string(),
            ));
        }
        if self.payload_json.trim().is_empty()
            || self.payload_json.len() > 65_536
            || self.payload_json.as_bytes().contains(&0)
        {
            return Err(QualificationTurnWriterInputError::Invalid(
                "payload must contain 1..=65536 non-NUL bytes".to_string(),
            ));
        }
        Ok(())
    }
}

/// Atomically attach an input to a turn store.
///
/// A second attachment is rejected rather than replaced.  This prevents a
/// late or untrusted host callback from swapping the lease/fence underneath a
/// running turn.
pub fn attach_qualification_turn_writer(
    turn_store: &ExtensionData,
    input: QualificationTurnWriterInput,
) -> bool {
    turn_store.insert_if(input, |current| current.is_none())
}

/// Register the qualification contributor on an embedding-owned registry.
///
/// This function is intentionally separate from [`super::install`].  An
/// embedding must choose the qualification profile explicitly and must still
/// attach a host-bound input for each turn; registration alone cannot create a
/// lease or grant authority.
pub fn install_qualification_turn_writer<C: Sync>(builder: &mut ExtensionRegistryBuilder<C>) {
    builder.turn_lifecycle_contributor(Arc::new(QualificationTurnLifecycleContributor::new()));
}

/// Register the qualification contributor with an explicit host capability.
///
/// Registration is still opt-in; the host is copied into each thread's
/// extension scope and is consulted only for turns whose embedding supplied
/// the capability.  No host means no automatic lease or outbox activity.
pub fn install_qualification_turn_writer_with_host<C: Sync>(
    builder: &mut ExtensionRegistryBuilder<C>,
    host: QualificationTurnWriterHost,
) {
    builder.turn_lifecycle_contributor(Arc::new(QualificationTurnLifecycleContributor::with_host(
        host,
    )));
}

#[derive(Default)]
struct TurnWriterState {
    attempted: bool,
    starting: bool,
    terminal_requested: Option<TerminalAction>,
    terminal_started: bool,
    active: Option<ActiveTurn>,
}

#[derive(Clone)]
struct ActiveTurn {
    input: QualificationTurnWriterInput,
    trajectory_id: String,
    event_seq: u32,
    event_sha256: Sha256Digest,
}

struct TerminalProjection {
    outcome: String,
    reason: String,
    lease_expired: bool,
}

#[derive(Clone, Debug)]
enum TerminalAction {
    Stop,
    Indeterminate(String),
}

/// Explicit qualification-only lifecycle contributor.
///
/// Hosts may either attach a [`QualificationTurnWriterInput`] before
/// `on_turn_start` or supply a [`QualificationTurnWriterHost`] capability.
/// The regular extension installer deliberately does not register it.
pub struct QualificationTurnLifecycleContributor {
    host: Option<QualificationTurnWriterHost>,
}

impl Default for QualificationTurnLifecycleContributor {
    fn default() -> Self {
        Self { host: None }
    }
}

impl QualificationTurnLifecycleContributor {
    pub const fn new() -> Self {
        Self { host: None }
    }

    pub fn with_host(host: QualificationTurnWriterHost) -> Self {
        Self { host: Some(host) }
    }

    fn state<'a>(&self, turn_store: &'a ExtensionData) -> std::sync::Arc<Mutex<TurnWriterState>> {
        turn_store.get_or_init(Mutex::default)
    }

    /// Settle the local lifecycle occurrence before closing its lease.
    ///
    /// The lease layer intentionally rejects a blind `release` while an
    /// admitted occurrence is queued or indeterminate.  Qualification H7 has
    /// already supplied the terminal observation at this point, so map that
    /// observation to an explicit local outcome and use the status-aware
    /// finalizer.  Keeping the two writes separate preserves replayability if
    /// the host dies between them; a retry reuses the exact transition and
    /// cannot append a second admission or H7 event.
    async fn settle_and_release(
        lease: &LocalLeaseOutbox,
        occurrence_key: &str,
        outcome: &str,
        reason: &str,
    ) -> Result<(), QualificationTurnWriterInputError> {
        match outcome {
            "turn_stopped" => {
                lease
                    .rollback_occurrence(occurrence_key, reason)
                    .await
                    .map_err(QualificationTurnWriterInputError::from)?;
            }
            "turn_indeterminate" => {
                lease
                    .mark_indeterminate(occurrence_key, reason)
                    .await
                    .map_err(QualificationTurnWriterInputError::from)?;
            }
            other => {
                return Err(QualificationTurnWriterInputError::Invalid(format!(
                    "unsupported qualification terminal outcome {other:?}"
                )));
            }
        }

        match lease
            .finalize_replayed_occurrence(occurrence_key)
            .await
            .map_err(QualificationTurnWriterInputError::from)?
        {
            LocalReplayFinalization::Released { .. } => Ok(()),
            LocalReplayFinalization::Queued(_) => Err(QualificationTurnWriterInputError::Invalid(
                "qualification terminal outcome left the local occurrence queued".to_string(),
            )),
            LocalReplayFinalization::NotAdmitted => {
                Err(QualificationTurnWriterInputError::Invalid(
                    "qualification terminal outcome has no local admission".to_string(),
                ))
            }
        }
    }

    async fn admit(
        input: &QualificationTurnWriterInput,
    ) -> Result<Option<QueuedReceipt>, QualificationTurnWriterInputError> {
        let recovery = read_h7_trajectory_bound_for_recovery(
            &input.lease,
            &input.executor,
            &input.binding,
            input.trajectory_id.clone(),
        )
        .await
        .map_err(|error| QualificationTurnWriterInputError::Invalid(error.to_string()))?;
        if let Some(trajectory) = recovery.trajectory {
            if let Some(terminal) = trajectory.events.last().filter(|event| event.terminal) {
                let terminal_occurrence_key =
                    bounded_terminal_occurrence_key(&input.occurrence_key);
                if !trajectory.is_complete_qualification_terminal(
                    &input.turn_id,
                    &input.occurrence_key,
                    &terminal_occurrence_key,
                ) {
                    return Err(QualificationTurnWriterInputError::Invalid(
                        "durable H7 terminal does not match qualification lifecycle shape"
                            .to_string(),
                    ));
                }
                // A process may die after the H7 terminal observation commits
                // but before the local outcome/release transaction.  The
                // durable trajectory is authoritative for this local
                // observation; close the leftover lease without attempting a
                // second turn_start append.
                if recovery.lease_expired {
                    // Post-TTL recovery is deliberately timeout-only.  Do
                    // not append an outcome or reopen a writable executor;
                    // the exact old head is terminalized by the lease CAS.
                    input.lease.expire_lease().await?;
                    return Ok(None);
                }
                Self::settle_and_release(
                    &input.lease,
                    &input.occurrence_key,
                    &terminal.outcome,
                    &bounded_terminal_reason(&terminal.reason),
                )
                .await?;
                return Ok(None);
            }
        }
        if recovery.lease_expired {
            // An expired attempt without a durable H7 terminal is not safe to
            // infer or silently close here: doing so would erase the very
            // evidence needed to distinguish a crash before/after turn
            // start.  Leave it for an explicit timeout/audit decision.
            return Err(QualificationTurnWriterInputError::Invalid(
                "qualification lease expired without a durable H7 terminal".to_string(),
            ));
        }
        input
            .binding
            .verify_current(&input.lease, &input.executor)
            .await?;
        let replay = input
            .lease
            .finalize_replayed_occurrence(input.occurrence_key.clone())
            .await?;
        match replay {
            LocalReplayFinalization::Released { .. } => Ok(None),
            LocalReplayFinalization::Queued(receipt) => Ok(Some(receipt)),
            LocalReplayFinalization::NotAdmitted => {
                match input
                    .lease
                    .admit(
                        input.occurrence_key.clone(),
                        TURN_START_TOPIC,
                        input.payload_json.clone(),
                    )
                    .await?
                {
                    LocalAdmission::Queued(receipt) | LocalAdmission::Replay(receipt) => {
                        Ok(Some(receipt))
                    }
                }
            }
        }
    }

    async fn append_start(
        input: &QualificationTurnWriterInput,
        receipt: &QueuedReceipt,
    ) -> Result<ActiveTurn, QualificationTurnWriterInputError> {
        let trajectory_id = input.trajectory_id.clone();
        let state_digest = Sha256Digest::for_bytes(input.payload_json.as_bytes());
        let policy_digest = Sha256Digest::for_bytes(b"qualification:observation-only-policy:v1");
        let model_receipt_digest =
            Sha256Digest::for_bytes(b"qualification:model-receipt:not-applicable:v1");
        let record = H7TrajectoryRecord::new(
            trajectory_id.clone(),
            /*event_seq*/ 1,
            format!("{trajectory_id}:event:turn-start"),
            H7TrajectoryEventKind::TurnStart,
            input.turn_id.clone(),
            input.occurrence_key.clone(),
            /*causal_parent_seq*/ None,
            /*causal_parent_sha256*/ None,
            state_digest,
            policy_digest,
            model_receipt_digest,
            h7_trajectory_local_receipt_digest(receipt),
            "turn_started",
            /*reward_bps*/ 0,
            /*safety_ok*/ true,
            serde_json::json!({
                "observation_only": true,
                "propensity": "not_applicable",
                "support": "not_applicable",
                "source": "qualification_turn_writer"
            })
            .to_string(),
            "not_applicable",
        )
        .map_err(|error| QualificationTurnWriterInputError::Invalid(error.to_string()))?;
        let result = append_h7_trajectory_event_bound(
            &input.lease,
            &input.executor,
            &input.binding,
            &record,
        )
        .await
        .map_err(|error| QualificationTurnWriterInputError::Invalid(error.to_string()))?;
        let event_sha256 = match result {
            codex_hepta_memory::H7TrajectoryAppend::Inserted { event_sha256, .. }
            | codex_hepta_memory::H7TrajectoryAppend::Replay { event_sha256, .. } => event_sha256,
        };
        Ok(ActiveTurn {
            input: input.clone(),
            trajectory_id,
            event_seq: 1,
            event_sha256,
        })
    }

    async fn append_terminal(
        active: &ActiveTurn,
        action: TerminalAction,
    ) -> Result<TerminalProjection, QualificationTurnWriterInputError> {
        let input = &active.input;
        // A terminal event may already have committed before a callback
        // crashed while projecting the local outcome/release.  Read that
        // durable observation first so a retry with a different reason (or a
        // different callback action) reuses the immutable terminal instead of
        // colliding on its fixed event id.
        let recovery = read_h7_trajectory_bound_for_recovery(
            &input.lease,
            &input.executor,
            &input.binding,
            active.trajectory_id.clone(),
        )
        .await
        .map_err(|error| QualificationTurnWriterInputError::Invalid(error.to_string()))?;
        if let Some(trajectory) = recovery.trajectory {
            if let Some(terminal) = trajectory.events.last().filter(|event| event.terminal) {
                let terminal_occurrence_key =
                    bounded_terminal_occurrence_key(&input.occurrence_key);
                if !trajectory.is_complete_qualification_terminal(
                    &input.turn_id,
                    &input.occurrence_key,
                    &terminal_occurrence_key,
                ) {
                    return Err(QualificationTurnWriterInputError::Invalid(
                        "durable H7 terminal does not match qualification lifecycle shape"
                            .to_string(),
                    ));
                }
                return Ok(TerminalProjection {
                    outcome: terminal.outcome.clone(),
                    reason: bounded_terminal_reason(&terminal.reason),
                    lease_expired: recovery.lease_expired,
                });
            }
        }
        if recovery.lease_expired {
            return Err(QualificationTurnWriterInputError::Invalid(
                "qualification lease expired before H7 terminal observation".to_string(),
            ));
        }
        // Re-check the host-owned binding before any terminal write.  A stale
        // callback must not mark an occurrence indeterminate (or release a
        // lease) after ownership has moved to a newer epoch.
        input
            .binding
            .verify_current(&input.lease, &input.executor)
            .await?;
        let (outcome, reason, action_label) = match &action {
            TerminalAction::Stop => (
                "turn_stopped".to_string(),
                "turn_stopped".to_string(),
                "stop",
            ),
            TerminalAction::Indeterminate(reason) => (
                "turn_indeterminate".to_string(),
                reason.clone(),
                "indeterminate",
            ),
        };
        let reason = bounded_terminal_reason(&reason);
        let next_seq = active.event_seq.checked_add(1).ok_or_else(|| {
            QualificationTurnWriterInputError::Invalid("trajectory sequence overflow".to_string())
        })?;
        let terminal_receipt = Sha256Digest::for_bytes(
            format!(
                "qualification:terminal-observation:v1:{}:{}:{}",
                active.event_sha256.as_str(),
                action_label,
                reason
            )
            .as_bytes(),
        );
        let record = H7TrajectoryRecord::terminal(
            active.trajectory_id.clone(),
            next_seq,
            format!("{}:event:terminal:{}", active.trajectory_id, action_label),
            input.turn_id.clone(),
            bounded_terminal_occurrence_key(&input.occurrence_key),
            active.event_seq,
            active.event_sha256.clone(),
            Sha256Digest::for_bytes(format!("terminal:{}:{}", input.turn_id, reason).as_bytes()),
            Sha256Digest::for_bytes(b"qualification:observation-only-policy:v1"),
            Sha256Digest::for_bytes(b"qualification:model-receipt:not-applicable:v1"),
            terminal_receipt,
            outcome.clone(),
            reason.clone(),
            serde_json::json!({
                "observation_only": true,
                "propensity": "not_applicable",
                "support": "not_applicable",
                "source": "qualification_turn_writer",
                "terminal_action": action_label
            })
            .to_string(),
        )
        .map_err(|error| QualificationTurnWriterInputError::Invalid(error.to_string()))?;
        append_h7_trajectory_event_bound(&input.lease, &input.executor, &input.binding, &record)
            .await
            .map_err(|error| QualificationTurnWriterInputError::Invalid(error.to_string()))?;
        Ok(TerminalProjection {
            outcome,
            reason,
            lease_expired: false,
        })
    }

    async fn complete(
        active: &ActiveTurn,
        action: TerminalAction,
    ) -> Result<(), QualificationTurnWriterInputError> {
        let input = &active.input;
        let projection = Self::append_terminal(active, action).await?;
        if projection.lease_expired {
            // Once the old exact head is past TTL, only the explicit timeout
            // CAS is allowed.  In particular, do not append a fresh local
            // outcome under an expired fence.
            input.lease.expire_lease().await?;
            return Ok(());
        }
        Self::settle_and_release(
            &input.lease,
            &input.occurrence_key,
            &projection.outcome,
            &projection.reason,
        )
        .await
    }

    async fn start_one(
        &self,
        input: QualificationTurnWriterInput,
        turn_store: &ExtensionData,
    ) -> bool {
        let result = tokio::time::timeout(IO_TIMEOUT, Self::admit(&input)).await;
        let active = match result {
            Ok(Ok(Some(receipt))) => {
                match tokio::time::timeout(IO_TIMEOUT, Self::append_start(&input, &receipt)).await {
                    Ok(Ok(active)) => Some(active),
                    Ok(Err(_)) | Err(_) => {
                        // Cleanup is best-effort, but it must not turn a
                        // qualification writer fault into an unbounded
                        // turn-start stall.  If the store is locked or
                        // unavailable, retain the exact witness for explicit
                        // recovery/inspection rather than weakening a fence.
                        let lease = input.lease.clone();
                        let occurrence_key = input.occurrence_key.clone();
                        let _ = tokio::time::timeout(IO_TIMEOUT, async move {
                            let _ = Self::settle_and_release(
                                &lease,
                                &occurrence_key,
                                "turn_indeterminate",
                                "h7_start_failed",
                            )
                            .await;
                        })
                        .await;
                        None
                    }
                }
            }
            _ => None,
        };
        let mut dispatchable = active.is_some();
        let terminal = {
            let state = turn_store.get::<Mutex<TurnWriterState>>();
            let Some(state) = state else { return false };
            let mut guard = state.lock().unwrap_or_else(PoisonError::into_inner);
            guard.starting = false;
            if let Some(active) = active.clone() {
                guard.active = Some(active);
            }
            guard
                .terminal_requested
                .take()
                .map(|action| (action, active))
        };
        if let Some((action, Some(active))) = terminal {
            dispatchable = false;
            let completed = tokio::time::timeout(IO_TIMEOUT, Self::complete(&active, action))
                .await
                .is_ok_and(|result| result.is_ok());
            if let Some(state) = turn_store.get::<Mutex<TurnWriterState>>() {
                let mut guard = state.lock().unwrap_or_else(PoisonError::into_inner);
                guard.terminal_started = completed;
                if completed {
                    guard.active = None;
                } else {
                    guard.active = Some(active);
                }
            }
        }
        dispatchable
    }

    async fn finish(&self, turn_store: &ExtensionData, action: TerminalAction) {
        let state = turn_store.get::<Mutex<TurnWriterState>>();
        let Some(state) = state else { return };
        let active = {
            let mut guard = state.lock().unwrap_or_else(PoisonError::into_inner);
            if guard.terminal_started {
                return;
            }
            if guard.starting {
                guard.terminal_requested.get_or_insert(action);
                return;
            }
            let Some(active) = guard.active.clone() else {
                return;
            };
            guard.terminal_started = true;
            active
        };
        let completed = tokio::time::timeout(IO_TIMEOUT, Self::complete(&active, action))
            .await
            .is_ok_and(|result| result.is_ok());
        let mut guard = state.lock().unwrap_or_else(PoisonError::into_inner);
        if completed {
            guard.active = None;
        } else {
            guard.terminal_started = false;
            guard.active = Some(active);
        }
    }
}

impl<C: Sync> ThreadLifecycleContributor<C> for QualificationTurnLifecycleContributor {
    fn on_thread_start<'a>(&'a self, input: ThreadStartInput<'a, C>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            let Some(host) = self.host.as_ref() else {
                return;
            };
            // A host may already have seeded this exact capability through
            // `StartThreadOptions.thread_extension_init`; never replace it.
            input
                .thread_store
                .insert_if(host.clone(), |current| current.is_none());
        })
    }
}

impl TurnLifecycleContributor for QualificationTurnLifecycleContributor {
    fn on_turn_start<'a>(&'a self, input: TurnStartInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            let attached_input = input.turn_store.get::<QualificationTurnWriterInput>();
            let has_admission_identity = input
                .turn_store
                .get::<QualificationTurnAdmissionIdentity>()
                .is_some();
            let host = input
                .thread_store
                .get::<QualificationTurnWriterHost>()
                .map(|host| (*host).clone())
                .or_else(|| self.host.clone());
            // Recovery/automatic turns intentionally remain inert until a
            // dedicated recovery identity protocol exists. Only a fresh turn
            // with an explicit client-bound identity or an explicitly
            // attached writer input can authorize this gate.
            let gate = if input.origin == TurnStartOrigin::NewTurn
                && (attached_input.is_some() || has_admission_identity)
            {
                input.turn_store.get_or_init(TurnStartGate::new)
            } else {
                // This contributor is inert for recovery/automatic/direct
                // turns.  Leave any gate owned by another contributor intact;
                // Core owns the turn scope and must decide stale-gate cleanup.
                return;
            };
            let host_input = if let Some(host_input) = attached_input {
                host_input
            } else {
                // Prefer the host capability seeded into the exact thread
                // scope.  The contributor's captured host is a fallback for
                // resumed/forked threads whose initializer was reconstructed
                // by Core without the embedding's optional seed.
                let Some(host) = host else {
                    gate.block("qualification_host_missing");
                    return;
                };
                let prepared = if let Some(identity) =
                    input.turn_store.get::<QualificationTurnAdmissionIdentity>()
                {
                    tokio::time::timeout(
                        IO_TIMEOUT,
                        host.prepare_with_request(
                            QualificationTurnWriterPrepareRequest::from_admission(
                                input.turn_id,
                                identity.as_ref(),
                            ),
                        ),
                    )
                    .await
                } else {
                    tokio::time::timeout(IO_TIMEOUT, host.prepare(input.turn_id)).await
                };
                let Ok(Ok(prepared)) = prepared else {
                    gate.block("qualification_prepare_failed");
                    return;
                };
                if !attach_qualification_turn_writer(input.turn_store, prepared) {
                    gate.block("qualification_input_already_bound");
                    return;
                }
                let Some(host_input) = input.turn_store.get::<QualificationTurnWriterInput>()
                else {
                    gate.block("qualification_input_missing_after_prepare");
                    return;
                };
                host_input
            };
            if host_input.validate_for_turn(input.turn_id).is_err()
                || input.turn_store.level_id() != input.turn_id
            {
                gate.block("qualification_input_invalid");
                return;
            }
            let state = self.state(input.turn_store);
            {
                let mut guard = state.lock().unwrap_or_else(PoisonError::into_inner);
                if guard.attempted {
                    gate.block("qualification_duplicate_start");
                    return;
                }
                guard.attempted = true;
                guard.starting = true;
            }
            if self
                .start_one((*host_input).clone(), input.turn_store)
                .await
            {
                gate.allow();
            } else {
                gate.block("qualification_turn_not_dispatchable");
            }
        })
    }

    fn on_turn_stop<'a>(&'a self, input: TurnStopInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move { self.finish(input.turn_store, TerminalAction::Stop).await })
    }

    fn on_turn_abort<'a>(&'a self, input: TurnAbortInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            self.finish(
                input.turn_store,
                TerminalAction::Indeterminate(format!("turn_aborted:{:?}", input.reason)),
            )
            .await;
        })
    }

    fn on_turn_error<'a>(&'a self, input: TurnErrorInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if input.turn_id != input.turn_store.level_id() {
                return;
            }
            self.finish(
                input.turn_store,
                TerminalAction::Indeterminate(format!("turn_error:{:?}", input.error)),
            )
            .await;
        })
    }
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::time::Instant;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    use codex_extension_api::ExtensionData;
    use codex_extension_api::ThreadStartInput;
    use codex_extension_api::TurnStartInput;
    use codex_extension_api::TurnStopInput;
    use codex_hepta_contracts::AgentId;
    use codex_hepta_memory::CognitiveAccess;
    use codex_hepta_memory::CognitiveScope;
    use codex_hepta_memory::CognitiveStore;
    use codex_hepta_memory::CompactFence;
    use codex_hepta_memory::KgFactSetDraft;
    use codex_hepta_memory::LedgerSourceKind;
    use codex_hepta_memory::LocalLeaseAcquire;
    use codex_hepta_memory::LocalLeaseHeadDisposition;
    use codex_hepta_memory::LocalLeaseState;
    use codex_hepta_memory::MemoryAdmissionEvidence;
    use codex_hepta_memory::MemoryCandidateDraft;
    use codex_hepta_memory::MemoryCandidateOrigin;
    use codex_hepta_memory::MemoryCandidateState;
    use codex_hepta_memory::MemoryLifecycleState;
    use codex_hepta_memory::RetrievalRequest;
    use codex_hepta_memory::SourceDraft;
    use codex_hepta_paths::HeptaFleetRoot;
    use codex_protocol::config_types::CollaborationMode;
    use codex_protocol::config_types::ModeKind;
    use codex_protocol::config_types::Settings;
    use codex_protocol::protocol::SessionSource;
    use codex_protocol::protocol::TokenUsage;
    use codex_state::SqliteConfig;
    use codex_utils_absolute_path::AbsolutePathBuf;
    use tempfile::TempDir;

    use super::*;

    const TURN_ID: &str = "turn:writer-e26";
    const LEASE_ID: &str = "lease:writer-e26";
    const OCCURRENCE: &str = "occurrence:writer-e26";

    fn mode() -> CollaborationMode {
        CollaborationMode {
            mode: ModeKind::Default,
            settings: Settings {
                model: "test-model".to_string(),
                reasoning_effort: None,
                developer_instructions: None,
            },
        }
    }

    async fn prepared() -> (TempDir, CognitiveStore, QualificationTurnWriterInput) {
        let temp = TempDir::new().expect("temp");
        let fleet_root = temp.path().join("fleet");
        fs::create_dir_all(&fleet_root).expect("fleet root");
        let fleet = HeptaFleetRoot::parse(fleet_root).expect("fleet");
        let owner = AgentId::parse("00000000-0000-4000-8000-000000000981").expect("owner");
        let store = CognitiveStore::open(&fleet.layout().agent(&owner))
            .await
            .expect("store");
        let fence = CompactFence::new(17, 19, 1, "writer-e26-fence").expect("fence");
        let expires = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_secs()
            + 3_600;
        let lease = match store
            .acquire_local_lease_bound(
                LEASE_ID,
                fence.authority_epoch,
                fence.owner_epoch,
                fence.generation,
                fence.fencing_token.clone(),
                expires,
            )
            .await
            .expect("bound lease")
        {
            LocalLeaseAcquire::Acquired(lease) | LocalLeaseAcquire::Replay(lease) => lease,
        };
        let executor = store
            .open_local_compact_executor_bound("journal:writer-e26", fence, &lease)
            .await
            .expect("bound executor");
        let binding =
            LocalTurnLifecycleBinding::from_handles(TURN_ID, &lease, &executor).expect("binding");
        let input = QualificationTurnWriterInput::new(
            TURN_ID,
            binding,
            lease,
            executor,
            OCCURRENCE,
            r#"{"schema_version":1,"external_effect":false,"kg_write_authority":false}"#,
        )
        .expect("writer input");
        (temp, store, input)
    }

    fn start_input<'a>(
        turn_store: &'a ExtensionData,
        thread_store: &'a ExtensionData,
        session_store: &'a ExtensionData,
        mode: &'a CollaborationMode,
        usage: &'a TokenUsage,
    ) -> TurnStartInput<'a> {
        start_input_with_origin(
            turn_store,
            thread_store,
            session_store,
            mode,
            usage,
            TurnStartOrigin::NewTurn,
        )
    }

    fn start_input_with_origin<'a>(
        turn_store: &'a ExtensionData,
        thread_store: &'a ExtensionData,
        session_store: &'a ExtensionData,
        mode: &'a CollaborationMode,
        usage: &'a TokenUsage,
        origin: TurnStartOrigin,
    ) -> TurnStartInput<'a> {
        TurnStartInput {
            turn_id: TURN_ID,
            origin,
            collaboration_mode: mode,
            token_usage_at_turn_start: usage,
            session_store,
            thread_store,
            turn_store,
        }
    }

    #[tokio::test]
    async fn explicit_bound_writer_admits_once_and_releases_on_stop() {
        let (_temp, store, input) = prepared().await;
        let turn_store = ExtensionData::new(TURN_ID);
        let thread_store = ExtensionData::new("thread:writer-e26");
        let session_store = ExtensionData::new("session:writer-e26");
        assert!(attach_qualification_turn_writer(&turn_store, input.clone()));
        assert!(!attach_qualification_turn_writer(
            &turn_store,
            input.clone()
        ));
        let contributor = QualificationTurnLifecycleContributor::new();
        let mode = mode();
        let usage = TokenUsage::default();
        contributor
            .on_turn_start(start_input(
                &turn_store,
                &thread_store,
                &session_store,
                &mode,
                &usage,
            ))
            .await;
        assert_eq!(
            turn_store
                .get::<TurnStartGate>()
                .expect("turn-start gate")
                .disposition(),
            codex_extension_api::TurnStartGateDisposition::Allowed
        );
        contributor
            .on_turn_start(start_input(
                &turn_store,
                &thread_store,
                &session_store,
                &mode,
                &usage,
            ))
            .await;
        let counts = input.lease.snapshot_counts().await.expect("counts");
        assert_eq!(counts.event_rows, 1);
        assert_eq!(counts.outbox_rows, 1);
        contributor
            .on_turn_stop(TurnStopInput {
                session_store: &session_store,
                thread_store: &thread_store,
                turn_store: &turn_store,
            })
            .await;
        contributor
            .on_turn_stop(TurnStopInput {
                session_store: &session_store,
                thread_store: &thread_store,
                turn_store: &turn_store,
            })
            .await;
        assert!(
            store
                .reopen_local_lease(LEASE_ID, 1, input.lease.fencing_token().to_string())
                .await
                .is_err()
        );
    }

    #[tokio::test]
    async fn turn_start_is_bounded_when_sqlite_is_locked() {
        let (_temp, store, input) = prepared().await;
        let turn_store = ExtensionData::new(TURN_ID);
        let thread_store = ExtensionData::new("thread:writer-e26");
        let session_store = ExtensionData::new("session:writer-e26");
        assert!(attach_qualification_turn_writer(&turn_store, input.clone()));
        let sqlite_home = AbsolutePathBuf::try_from(
            store
                .path()
                .parent()
                .expect("cognitive db parent")
                .to_path_buf(),
        )
        .expect("absolute sqlite home");
        let blocker_pool = SqliteConfig::from_sqlite_home(sqlite_home)
            .open_durable_evidence_pool(store.path())
            .await
            .expect("open lock pool");
        let blocker = blocker_pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .expect("lock cognitive store");
        let contributor = QualificationTurnLifecycleContributor::new();
        let mode = mode();
        let usage = TokenUsage::default();
        let started = Instant::now();
        contributor
            .on_turn_start(start_input(
                &turn_store,
                &thread_store,
                &session_store,
                &mode,
                &usage,
            ))
            .await;
        let gate = turn_store
            .get::<TurnStartGate>()
            .expect("locked start must publish a gate");
        assert_eq!(
            gate.disposition(),
            codex_extension_api::TurnStartGateDisposition::Blocked
        );
        assert_eq!(
            gate.reason_code().as_deref(),
            Some("qualification_turn_not_dispatchable")
        );
        assert!(
            started.elapsed() < Duration::from_secs(3),
            "locked start cleanup must remain bounded"
        );
        // The timeout is fail-closed: if cleanup could not acquire the lock,
        // the exact active witness remains for explicit inspection/recovery.
        blocker.rollback().await.expect("release lock");
        let inspection = store
            .inspect_local_lease_head(LEASE_ID)
            .await
            .expect("inspect locked-start witness");
        assert_eq!(inspection.disposition, LocalLeaseHeadDisposition::Active);
        blocker_pool.close().await;
    }

    #[tokio::test]
    async fn recovery_turn_stays_inert_without_a_recovery_identity() {
        let (_temp, _store, input) = prepared().await;
        let turn_store = ExtensionData::new(TURN_ID);
        let thread_store = ExtensionData::new("thread:writer-e26");
        let session_store = ExtensionData::new("session:writer-e26");
        assert!(attach_qualification_turn_writer(&turn_store, input.clone()));
        let contributor = QualificationTurnLifecycleContributor::new();
        let mode = mode();
        let usage = TokenUsage::default();

        contributor
            .on_turn_start(start_input_with_origin(
                &turn_store,
                &thread_store,
                &session_store,
                &mode,
                &usage,
                TurnStartOrigin::Recovery,
            ))
            .await;

        assert!(
            turn_store.get::<TurnStartGate>().is_none(),
            "recovery must not manufacture a fresh provider gate"
        );
        let counts = input.lease.snapshot_counts().await.expect("counts");
        assert_eq!(counts.event_rows, 0);
        assert_eq!(counts.outbox_rows, 0);

        let other_gate = TurnStartGate::new();
        other_gate.block("other_contributor_failed");
        turn_store.insert(other_gate);
        contributor
            .on_turn_start(start_input_with_origin(
                &turn_store,
                &thread_store,
                &session_store,
                &mode,
                &usage,
                TurnStartOrigin::Recovery,
            ))
            .await;
        assert_eq!(
            turn_store
                .get::<TurnStartGate>()
                .expect("inert contributor must preserve another gate")
                .disposition(),
            codex_extension_api::TurnStartGateDisposition::Blocked
        );
    }

    #[tokio::test]
    async fn host_capability_seeds_thread_and_prepares_exact_turn_input() {
        let (_temp, _store, template) = prepared().await;
        let callback_template = template.clone();
        let host =
            QualificationTurnWriterHost::from_fn("qualification-test-host", move |turn_id| {
                let callback_template = callback_template.clone();
                async move {
                    QualificationTurnWriterInput::new(
                        turn_id,
                        callback_template.binding.clone(),
                        callback_template.lease.clone(),
                        callback_template.executor.clone(),
                        callback_template.occurrence_key.clone(),
                        callback_template.payload_json.clone(),
                    )
                }
            });
        let contributor = QualificationTurnLifecycleContributor::with_host(host.clone());
        let turn_store = ExtensionData::new(TURN_ID);
        let thread_store = ExtensionData::new("thread:writer-e26");
        let session_store = ExtensionData::new("session:writer-e26");
        let config = ();
        contributor
            .on_thread_start(ThreadStartInput {
                config: &config,
                session_source: &SessionSource::Cli,
                installation_id: "qualification-installation",
                persistent_thread_state_available: true,
                environments: &[],
                mcp_resource_client: None,
                extension_metrics: None,
                session_store: &session_store,
                thread_store: &thread_store,
            })
            .await;
        assert_eq!(
            thread_store
                .get::<QualificationTurnWriterHost>()
                .expect("thread host capability")
                .capability_id(),
            "qualification-test-host"
        );
        turn_store.insert(
            QualificationTurnAdmissionIdentity::new(
                "thread:writer-e26",
                "client:writer-e26",
                "0000000000000000000000000000000000000000000000000000000000000000",
            )
            .expect("durable admission identity"),
        );

        let mode = mode();
        let usage = TokenUsage::default();
        contributor
            .on_turn_start(start_input(
                &turn_store,
                &thread_store,
                &session_store,
                &mode,
                &usage,
            ))
            .await;
        assert!(
            turn_store.get::<QualificationTurnWriterInput>().is_some(),
            "host callback must attach the exact prepared input"
        );
        let counts = template.lease.snapshot_counts().await.expect("counts");
        assert_eq!(counts.event_rows, 1);
        assert_eq!(counts.outbox_rows, 1);
        contributor
            .on_turn_stop(TurnStopInput {
                session_store: &session_store,
                thread_store: &thread_store,
                turn_store: &turn_store,
            })
            .await;
    }

    #[test]
    fn admission_identity_hashes_are_length_framed() {
        let first = QualificationTurnAdmissionIdentity::new(
            "thread:a:b",
            "client:c",
            "0000000000000000000000000000000000000000000000000000000000000000",
        )
        .expect("first identity");
        let second = QualificationTurnAdmissionIdentity::new(
            "thread:a",
            "b:client:c",
            "0000000000000000000000000000000000000000000000000000000000000000",
        )
        .expect("second identity");
        let first_request = QualificationTurnWriterPrepareRequest::from_admission("turn", &first);
        let second_request = QualificationTurnWriterPrepareRequest::from_admission("turn", &second);
        assert_ne!(
            first_request.logical_turn_id, second_request.logical_turn_id,
            "delimiter-containing identities must not alias"
        );
        assert_ne!(
            first_request.logical_binding_sha256, second_request.logical_binding_sha256,
            "binding digest must preserve field boundaries"
        );
    }

    #[tokio::test]
    async fn host_rejects_public_input_with_malformed_attempt_fields() {
        let (_temp, _store, mut template) = prepared().await;
        template.trajectory_id = "bad\0trajectory".to_string();
        let host = QualificationTurnWriterHost::from_request_fn(
            "qualification-malformed-input-test",
            move |_request| {
                let template = template.clone();
                async move { Ok(template) }
            },
        );
        let result = host
            .prepare_with_request(QualificationTurnWriterPrepareRequest::for_turn(TURN_ID))
            .await;
        assert!(result.is_err(), "malformed host input must fail closed");
    }

    #[tokio::test]
    async fn reopened_host_replays_same_occurrence_without_second_outbox_row() {
        let (temp, store, input) = prepared().await;
        let first_turn = ExtensionData::new(TURN_ID);
        let thread_store = ExtensionData::new("thread:writer-e26");
        let session_store = ExtensionData::new("session:writer-e26");
        assert!(attach_qualification_turn_writer(&first_turn, input.clone()));
        let contributor = QualificationTurnLifecycleContributor::new();
        let mode = mode();
        let usage = TokenUsage::default();
        contributor
            .on_turn_start(start_input(
                &first_turn,
                &thread_store,
                &session_store,
                &mode,
                &usage,
            ))
            .await;
        let counts_before = input.lease.snapshot_counts().await.expect("counts");
        drop(contributor);
        drop(first_turn);
        drop(input);
        drop(store);

        let fleet_root = temp.path().join("fleet");
        let fleet = HeptaFleetRoot::parse(fleet_root).expect("fleet reopen");
        let owner = AgentId::parse("00000000-0000-4000-8000-000000000981").expect("owner");
        let reopened_store = CognitiveStore::open(&fleet.layout().agent(&owner))
            .await
            .expect("reopen store");
        let lease = reopened_store
            .reopen_local_lease(LEASE_ID, 1, "writer-e26-fence")
            .await
            .expect("reopen lease");
        let fence = CompactFence::new(17, 19, 1, "writer-e26-fence").expect("fence");
        let executor = reopened_store
            .open_local_compact_executor_bound("journal:writer-e26", fence, &lease)
            .await
            .expect("reopen executor");
        let binding = LocalTurnLifecycleBinding::from_handles(TURN_ID, &lease, &executor)
            .expect("reopen binding");
        let input = QualificationTurnWriterInput::new(
            TURN_ID,
            binding,
            lease,
            executor,
            OCCURRENCE,
            r#"{"schema_version":1,"external_effect":false,"kg_write_authority":false}"#,
        )
        .expect("reopen input");
        let second_turn = ExtensionData::new(TURN_ID);
        assert!(attach_qualification_turn_writer(
            &second_turn,
            input.clone()
        ));
        let contributor = QualificationTurnLifecycleContributor::new();
        contributor
            .on_turn_start(start_input(
                &second_turn,
                &thread_store,
                &session_store,
                &mode,
                &usage,
            ))
            .await;
        assert_eq!(
            input.lease.snapshot_counts().await.expect("counts"),
            counts_before
        );
        contributor
            .on_turn_stop(TurnStopInput {
                session_store: &session_store,
                thread_store: &thread_store,
                turn_store: &second_turn,
            })
            .await;
    }

    #[tokio::test]
    async fn reopened_host_terminal_h7_closes_queued_occurrence_without_start_replay() {
        let (temp, store, input) = prepared().await;
        let receipt = QualificationTurnLifecycleContributor::admit(&input)
            .await
            .expect("admit")
            .expect("queued receipt");
        let active = QualificationTurnLifecycleContributor::append_start(&input, &receipt)
            .await
            .expect("H7 start");
        // Simulate a kill in the narrow window after the immutable H7
        // terminal row commits but before the local outcome/release step.
        QualificationTurnLifecycleContributor::append_terminal(&active, TerminalAction::Stop)
            .await
            .expect("H7 terminal");
        let counts_before = input.lease.snapshot_counts().await.expect("counts");
        assert_eq!(counts_before.event_rows, 1);
        assert_eq!(counts_before.outbox_rows, 1);
        drop(active);
        drop(input);
        drop(store);

        let fleet = HeptaFleetRoot::parse(temp.path().join("fleet")).expect("fleet reopen");
        let owner = AgentId::parse("00000000-0000-4000-8000-000000000981").expect("owner");
        let reopened_store = CognitiveStore::open(&fleet.layout().agent(&owner))
            .await
            .expect("reopen store");
        let lease = reopened_store
            .reopen_local_lease(LEASE_ID, 1, "writer-e26-fence")
            .await
            .expect("reopen active lease");
        let fence = CompactFence::new(17, 19, 1, "writer-e26-fence").expect("fence");
        let executor = reopened_store
            .open_local_compact_executor_bound("journal:writer-e26", fence, &lease)
            .await
            .expect("reopen executor");
        let binding = LocalTurnLifecycleBinding::from_handles(TURN_ID, &lease, &executor)
            .expect("reopen binding");
        let reopened_input = QualificationTurnWriterInput::new(
            TURN_ID,
            binding,
            lease,
            executor,
            OCCURRENCE,
            r#"{"schema_version":1,"external_effect":false,"kg_write_authority":false}"#,
        )
        .expect("reopen input");
        let second_turn = ExtensionData::new(TURN_ID);
        assert!(attach_qualification_turn_writer(
            &second_turn,
            reopened_input.clone()
        ));
        let contributor = QualificationTurnLifecycleContributor::new();
        let thread_store = ExtensionData::new("thread:writer-e26");
        let session_store = ExtensionData::new("session:writer-e26");
        let mode = mode();
        let usage = TokenUsage::default();
        contributor
            .on_turn_start(start_input(
                &second_turn,
                &thread_store,
                &session_store,
                &mode,
                &usage,
            ))
            .await;
        let counts_after = reopened_input
            .lease
            .snapshot_counts()
            .await
            .expect("reopened counts");
        // Closing the queued local intent requires an explicit rollback
        // marker before the terminal lease row; the immutable outbox remains
        // unchanged.
        assert_eq!(counts_after.event_rows, counts_before.event_rows + 1);
        assert_eq!(counts_after.outbox_rows, counts_before.outbox_rows);
        assert_eq!(counts_after.lease_rows, counts_before.lease_rows + 1);
        assert_eq!(
            reopened_store
                .read_h7_trajectory("qualification:trajectory:turn:writer-e26")
                .await
                .expect("read terminal trajectory")
                .expect("trajectory")
                .events
                .len(),
            2
        );
        assert!(
            reopened_store
                .reopen_local_lease(LEASE_ID, 1, "writer-e26-fence")
                .await
                .is_err(),
            "replay must release the leftover active lease after terminal H7"
        );
    }

    #[tokio::test]
    async fn terminal_retry_reuses_durable_reason_instead_of_fixed_event_conflict() {
        let (_temp, store, input) = prepared().await;
        let receipt = match input
            .lease
            .admit(OCCURRENCE, TURN_START_TOPIC, input.payload_json.clone())
            .await
            .expect("admit")
        {
            LocalAdmission::Queued(receipt) | LocalAdmission::Replay(receipt) => receipt,
        };
        let active = QualificationTurnLifecycleContributor::append_start(&input, &receipt)
            .await
            .expect("append start");

        // Simulate a crash after the immutable H7 terminal commit but before
        // the local outcome/release projection.  The retry intentionally has
        // a different reason; the durable first terminal must win.
        QualificationTurnLifecycleContributor::append_terminal(
            &active,
            TerminalAction::Indeterminate("first durable reason".to_string()),
        )
        .await
        .expect("first terminal");
        QualificationTurnLifecycleContributor::complete(
            &active,
            TerminalAction::Indeterminate("different retry reason".to_string()),
        )
        .await
        .expect("terminal retry projection");

        let trajectory = store
            .read_h7_trajectory("qualification:trajectory:turn:writer-e26")
            .await
            .expect("read trajectory")
            .expect("trajectory");
        assert_eq!(trajectory.events.len(), 2);
        assert_eq!(trajectory.events[1].reason, "first durable reason");
        assert!(input.lease.verify_current().await.is_err());
    }

    /// The qualification-only admission/Saga/forget path must keep all state
    /// in one real Agent-local SQLite store: a candidate is admitted,
    /// explicitly verified without facts, bound to one lifecycle outbox
    /// occurrence, host-tombstoned, and then observed again after reopen.
    ///
    /// This intentionally exercises no production caller, shared KG, or
    /// external effect.  The queued outbox row is only a local intent, and a
    /// replay after the simulated crash must return that same row rather than
    /// append a second admission.
    #[tokio::test]
    async fn qualification_admission_saga_forget_tombstone_survives_reopen() {
        let (temp, store, prepared_input) = prepared().await;
        let owner = prepared_input.lease.owner_agent_id().clone();
        let access = CognitiveAccess::agent_private(owner.clone());
        let content = "qualification candidate is withdrawn by the host";
        let candidate = store
            .admit_memory_candidate(
                &access,
                &MemoryCandidateDraft {
                    stable_key: "writer-e26-forget-candidate".to_string(),
                    scope: CognitiveScope::AgentPrivate,
                    content: content.to_string(),
                    source_event_key: "qualification:writer-e26:candidate".to_string(),
                    observed_at_unix_seconds: 100,
                    origin: MemoryCandidateOrigin::CompactionSummary,
                },
            )
            .await
            .expect("candidate admission");
        assert_eq!(candidate.state, MemoryCandidateState::Provisional);
        assert!(!candidate.fact_admitted);
        assert_eq!(candidate.write.projection.entity_count, 0);
        assert_eq!(candidate.write.projection.relation_count, 0);

        let evidence = MemoryAdmissionEvidence::from_bytes(content.as_bytes(), "qualification")
            .expect("content-bound evidence");
        let verify_source = SourceDraft {
            scope: CognitiveScope::AgentPrivate,
            kind: LedgerSourceKind::ExplicitMemoryDirective,
            event_key: "qualification:writer-e26:verify".to_string(),
            content: content.as_bytes().to_vec(),
            observed_at_unix_seconds: 101,
        };
        let verified = store
            .verify_memory_candidate(
                &access,
                &candidate.candidate_id,
                1,
                candidate.origin,
                &verify_source,
                content.to_string(),
                101,
                &evidence,
                &KgFactSetDraft::default(),
            )
            .await
            .expect("candidate verification");
        assert_eq!(verified.state, MemoryCandidateState::Verified);
        assert!(!verified.fact_admitted);
        assert_eq!(verified.revision, 2);
        assert_eq!(verified.write.projection.entity_count, 0);
        assert_eq!(verified.write.projection.relation_count, 0);

        let before_forget = store
            .retrieve_memory_candidates(&access, &RetrievalRequest::new("withdrawn host", 200))
            .await
            .expect("pre-forget retrieval");
        assert_eq!(before_forget.candidates.len(), 1);
        assert_eq!(
            before_forget.candidates[0].memory.id.memory_id,
            candidate.candidate_id
        );

        // Bind the Saga payload to the exact local candidate identity.  This
        // remains a local queue intent; it is never sent to a provider.
        let writer_input = QualificationTurnWriterInput::new(
            TURN_ID,
            prepared_input.binding.clone(),
            prepared_input.lease.clone(),
            prepared_input.executor.clone(),
            OCCURRENCE,
            format!(
                r#"{{"candidate_id":"{}","external_effect":false,"kg_write_authority":false}}"#,
                candidate.candidate_id.as_str()
            ),
        )
        .expect("candidate-bound writer input");
        let turn_store = ExtensionData::new(TURN_ID);
        let thread_store = ExtensionData::new("thread:writer-e26");
        let session_store = ExtensionData::new("session:writer-e26");
        assert!(attach_qualification_turn_writer(
            &turn_store,
            writer_input.clone()
        ));
        let contributor = QualificationTurnLifecycleContributor::new();
        let mode = mode();
        let usage = TokenUsage::default();
        contributor
            .on_turn_start(start_input(
                &turn_store,
                &thread_store,
                &session_store,
                &mode,
                &usage,
            ))
            .await;
        let counts_before_forget = writer_input.lease.snapshot_counts().await.expect("counts");
        assert_eq!(counts_before_forget.event_rows, 1);
        assert_eq!(counts_before_forget.outbox_rows, 1);
        assert!(
            !writer_input
                .lease
                .admit(
                    OCCURRENCE,
                    TURN_START_TOPIC,
                    r#"{"candidate_id":"different"}"#,
                )
                .await
                .is_ok(),
            "replaying with a different payload must fail closed"
        );

        let reason = "qualification host withdrawal".to_string();
        let tombstone_source = SourceDraft {
            scope: CognitiveScope::AgentPrivate,
            kind: LedgerSourceKind::ExplicitMemoryDirective,
            event_key: "qualification:writer-e26:forget".to_string(),
            content: reason.as_bytes().to_vec(),
            observed_at_unix_seconds: 102,
        };
        let tombstone = store
            .tombstone_memory_candidate(
                &access,
                &candidate.candidate_id,
                2,
                candidate.origin,
                &tombstone_source,
                reason,
                102,
            )
            .await
            .expect("host tombstone");
        assert_eq!(tombstone.state, MemoryCandidateState::Tombstoned);
        assert_eq!(tombstone.revision, 3);
        assert!(!tombstone.fact_admitted);
        assert_eq!(tombstone.write.projection.entity_count, 0);
        assert_eq!(tombstone.write.projection.relation_count, 0);
        assert!(matches!(
            tombstone.write.memory.lifecycle,
            MemoryLifecycleState::Tombstoned { .. }
        ));
        assert!(
            store
                .retrieve_memory_candidates(&access, &RetrievalRequest::new("withdrawn host", 200))
                .await
                .expect("post-forget retrieval")
                .candidates
                .is_empty()
        );

        // Simulate a host crash after durable admission and forget but before
        // lifecycle terminalization.  Reopen must replay the same local
        // occurrence and keep the immutable tombstone visible.
        drop(contributor);
        drop(turn_store);
        drop(writer_input);
        drop(prepared_input);
        drop(store);

        let fleet = HeptaFleetRoot::parse(temp.path().join("fleet")).expect("fleet reopen");
        let reopened_store = CognitiveStore::open(&fleet.layout().agent(&owner))
            .await
            .expect("reopen store");
        let reopened_access = CognitiveAccess::agent_private(owner.clone());
        let reopened_latest = reopened_store
            .latest_memory(&reopened_access, &candidate.candidate_id)
            .await
            .expect("reopened tombstone");
        assert_eq!(reopened_latest.id.revision, 3);
        assert!(matches!(
            reopened_latest.lifecycle,
            MemoryLifecycleState::Tombstoned { .. }
        ));
        assert!(
            reopened_store
                .retrieve_memory_candidates(
                    &reopened_access,
                    &RetrievalRequest::new("withdrawn host", 200)
                )
                .await
                .expect("reopened post-forget retrieval")
                .candidates
                .is_empty()
        );

        let reopened_lease = reopened_store
            .reopen_local_lease(LEASE_ID, 1, "writer-e26-fence")
            .await
            .expect("reopen active Saga lease");
        let replay = reopened_lease
            .finalize_replayed_occurrence(OCCURRENCE)
            .await
            .expect("replay local occurrence");
        match replay {
            LocalReplayFinalization::Queued(receipt) => {
                assert!(!receipt.external_effect);
            }
            other => panic!("queued occurrence changed state on reopen: {other:?}"),
        }
        assert_eq!(
            reopened_lease
                .snapshot_counts()
                .await
                .expect("reopened counts"),
            counts_before_forget
        );
        // The queued local intent is immutable metadata, but the lease guard
        // requires an explicit outcome before terminalization.  Host
        // withdrawal settles it as a local rollback; no external effect or KG
        // write is implied.
        reopened_lease
            .rollback_occurrence(OCCURRENCE, "qualification host withdrawal")
            .await
            .expect("settle withdrawn occurrence");
        let released = reopened_lease
            .release()
            .await
            .expect("terminalize Saga lease");
        assert_eq!(released.state, LocalLeaseState::Released);
        assert!(!QUALIFICATION_TURN_WRITER_EXTERNAL_EFFECTS);
        assert!(!QUALIFICATION_TURN_WRITER_KG_WRITE_AUTHORITY);
        assert!(!QUALIFICATION_TURN_WRITER_PRODUCTION_CALLER);
    }

    #[tokio::test]
    async fn forged_binding_is_rejected_before_any_admission() {
        let (_temp, _store, mut input) = prepared().await;
        input.binding.fence.owner_epoch += 1;
        let turn_store = ExtensionData::new(TURN_ID);
        assert!(attach_qualification_turn_writer(&turn_store, input));
        let contributor = QualificationTurnLifecycleContributor::new();
        let thread_store = ExtensionData::new("thread:writer-e26");
        let session_store = ExtensionData::new("session:writer-e26");
        let mode = mode();
        let usage = TokenUsage::default();
        contributor
            .on_turn_start(start_input(
                &turn_store,
                &thread_store,
                &session_store,
                &mode,
                &usage,
            ))
            .await;
        let state = turn_store.get::<Mutex<TurnWriterState>>();
        assert!(
            state.is_none(),
            "invalid input must not create writer state"
        );
    }

    #[tokio::test]
    async fn stale_terminal_callback_verifies_before_indeterminate_write() {
        let (_temp, _store, input) = prepared().await;
        input
            .lease
            .admit(OCCURRENCE, TURN_START_TOPIC, input.payload_json.clone())
            .await
            .expect("admit occurrence");

        // Keep the lease active but make only the callback's copied binding
        // stale.  A terminal callback must reject this before appending an
        // indeterminate outcome; otherwise a late stale owner can mutate the
        // current occurrence even though its fence no longer matches.
        let mut stale = input.clone();
        stale.binding.fence.owner_epoch += 1;
        let stale_active = ActiveTurn {
            input: stale,
            trajectory_id: "qualification:trajectory:stale".to_string(),
            event_seq: 1,
            event_sha256: Sha256Digest::for_bytes(b"stale-parent"),
        };
        assert!(
            QualificationTurnLifecycleContributor::complete(
                &stale_active,
                TerminalAction::Indeterminate("stale callback".to_string()),
            )
            .await
            .is_err()
        );

        let replay = input
            .lease
            .finalize_replayed_occurrence(OCCURRENCE)
            .await
            .expect("replay after stale callback");
        assert!(matches!(replay, LocalReplayFinalization::Queued(_)));
    }

    #[test]
    fn terminal_projection_bounds_long_occurrence_and_reason_values() {
        let long_occurrence = "o".repeat(MAX_OCCURRENCE_KEY_BYTES);
        let terminal_occurrence = bounded_terminal_occurrence_key(&long_occurrence);
        assert!(terminal_occurrence.len() <= MAX_OCCURRENCE_KEY_BYTES);
        assert!(terminal_occurrence.starts_with("qualification:terminal-occurrence:"));
        assert_eq!(
            terminal_occurrence,
            bounded_terminal_occurrence_key(&long_occurrence)
        );

        let long_reason = format!("{}\0", "r".repeat(513));
        let terminal_reason = bounded_terminal_reason(&long_reason);
        assert!(terminal_reason.len() <= 512);
        assert!(terminal_reason.starts_with("reason_sha256:"));
    }
}
