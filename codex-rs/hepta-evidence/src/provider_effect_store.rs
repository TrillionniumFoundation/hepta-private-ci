use codex_hepta_contracts::ProviderEffectAck;
use codex_hepta_contracts::ProviderEffectAckSource;
use codex_hepta_contracts::ProviderEffectAckStatus;
use codex_hepta_contracts::ProviderEffectAdapter;
use codex_hepta_contracts::ProviderEffectBindingError;
use codex_hepta_contracts::ProviderEffectDispatch;
use codex_hepta_contracts::ProviderEffectIdempotencyCapability;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::ProviderEffectLookup;
use codex_hepta_contracts::ProviderEffectState;
use codex_hepta_contracts::ProviderEffectStatusObservation;
use codex_hepta_contracts::ProviderEffectUncertainty;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::reconcile_provider_lookup;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;

use crate::AppendDisposition;
use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::canonical::canonical_json;
use crate::schema_validation::classify_sqlx_error;
use crate::store::now_millis;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredProviderEffectIntent {
    pub seq: i64,
    pub intent: ProviderEffectIntent,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredProviderEffectAck {
    pub seq: i64,
    pub ack: ProviderEffectAck,
    pub source: ProviderEffectAckSource,
    pub recorded_at_ms: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredProviderEffectUncertainty {
    pub seq: i64,
    pub uncertainty: ProviderEffectUncertainty,
    pub recorded_at_ms: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredProviderEffect {
    pub intent: StoredProviderEffectIntent,
    pub acknowledgements: Vec<StoredProviderEffectAck>,
    pub uncertainties: Vec<StoredProviderEffectUncertainty>,
}

/// Result of one durable, qualification-only adapter dispatch attempt.
///
/// `dispatch_attempted` means that the adapter method was invoked; it is not
/// evidence that an external provider applied an effect.  The facade persists
/// an uncertainty claim before invoking an adapter and serializes competing
/// calls through one opened store.  This is deliberately a durable local
/// boundary claim, not provider physical exactly-once authority.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ProviderEffectQualificationDispatchReceipt {
    pub state: ProviderEffectState,
    /// Whether this invocation inserted the durable pre-dispatch claim.
    pub dispatch_claimed: bool,
    /// Whether this invocation called the adapter's `dispatch` method.
    pub dispatch_attempted: bool,
}

/// Descriptive qualification metadata only; this is not a runtime capability
/// or an isolation gate for an adapter supplied by a caller.
pub const PROVIDER_EFFECT_QUALIFICATION_NAMESPACE: &str = "local_qualification_only";
/// Registration convention only; an injected adapter can still have effects.
pub const PROVIDER_EFFECT_QUALIFICATION_EXTERNAL_EFFECTS: bool = false;
/// Registration convention only; this API does not authenticate its caller.
pub const PROVIDER_EFFECT_QUALIFICATION_PRODUCTION_CALLER: bool = false;
/// An intent that was already durable before the dispatch facade saw it has
/// no local proof that this process owns the pre-dispatch boundary.  It must
/// be quarantined before any adapter call.
const PROVIDER_EFFECT_IMPORTED_PENDING_REASON: &str = "provider_imported_pending";
/// Reserved local claim written immediately before the qualification adapter
/// crosses its dispatch boundary.  It is intentionally not accepted through
/// the public quarantine API: only the facade that owns the process-local
/// boundary lock may mint this witness.
const PROVIDER_EFFECT_DISPATCH_BOUNDARY_PENDING_REASON: &str = "provider_dispatch_boundary_pending";

#[derive(Clone, Debug)]
struct DispatchBoundaryClaim {
    key: ProviderEffectKey,
    recorded_at_ms: i64,
}

impl StoredProviderEffect {
    pub fn state(&self) -> ProviderEffectState {
        let latest_ack = self.acknowledgements.last();
        let latest_uncertainty = self.uncertainties.last();
        match (latest_ack, latest_uncertainty) {
            // Equal cross-table timestamps are not an ordering witness.  A
            // damaged/imported store must therefore remain quarantined until
            // the startup oracle rejects it, rather than letting the ACK win
            // an ambiguous tie.
            (Some(ack), Some(uncertainty)) if uncertainty.recorded_at_ms >= ack.recorded_at_ms => {
                ProviderEffectState::Indeterminate
            }
            (Some(ack), _) => ack.ack.state(),
            (None, Some(_)) => ProviderEffectState::Indeterminate,
            (None, None) => ProviderEffectState::Pending,
        }
    }
}

impl HeptaEvidenceStore {
    /// Persists the occurrence intent before any provider dispatch crosses the
    /// transport boundary.  Replaying the exact intent is idempotent; a
    /// same-key/different-payload attempt is rejected.
    pub async fn append_provider_effect_intent(
        &self,
        intent: &ProviderEffectIntent,
    ) -> Result<AppendDisposition, EvidenceError> {
        intent.validate().map_err(binding_invalid)?;
        let payload = canonical_json(intent)?;
        let payload_json = String::from_utf8(payload.clone())
            .map_err(|error| EvidenceError::Serialization(error.to_string()))?;
        let record_sha256 = Sha256Digest::for_bytes(&payload);
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let insert = sqlx::query(
            "INSERT INTO provider_effect_intents (
                effect_key, payload_sha256, schema_version,
                payload_json, record_sha256, recorded_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?)
             ON CONFLICT DO NOTHING",
        )
        .bind(intent.key.as_str())
        .bind(intent.payload_sha256.as_str())
        .bind(i64::from(intent.schema_version))
        .bind(&payload_json)
        .bind(record_sha256.as_str())
        .bind(now_millis()?)
        .execute(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;
        let disposition = verify_effect_intent(
            &mut transaction,
            intent,
            &payload_json,
            record_sha256.as_str(),
            insert.rows_affected() == 1,
        )
        .await?;
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(disposition)
    }

    /// Dispatch one provider effect through a durable, qualification-only
    /// adapter seam.
    ///
    /// The intent is persisted first.  A `provider_dispatch_boundary_pending`
    /// uncertainty is then won by at most one concurrent caller through this
    /// opened store before the adapter is invoked.  Any later facade call—
    /// including after process death and reopen—observes
    /// `Indeterminate`/`Accepted`/a terminal state and does not send again; it
    /// must use [`Self::reconcile_provider_effect_with_adapter`].  Direct
    /// low-level append/reconcile calls, separate store opens, and separate
    /// processes remain outside this process-local lock and can still race;
    /// provider-owned idempotency is therefore required for physical
    /// exactly-once semantics.
    /// An intent that was already present before this facade call is treated
    /// as imported Pending state and quarantined without a dispatch attempt;
    /// only a call that inserts the intent may claim this local boundary.
    ///
    /// This method is not registered with Agentd, App Server, automation, or a
    /// production caller.  `dispatch_attempted` is only a local observation
    /// of the adapter call and never a provider effect receipt.
    pub async fn dispatch_provider_effect_qualification<A: ProviderEffectAdapter + ?Sized>(
        &self,
        adapter: &A,
        intent: &ProviderEffectIntent,
    ) -> Result<ProviderEffectQualificationDispatchReceipt, EvidenceError> {
        let _boundary_guard = self
            .provider_effect_boundary_lock
            .clone()
            .lock_owned()
            .await;
        intent.validate().map_err(binding_invalid)?;
        let intent_disposition = self.append_provider_effect_intent(intent).await?;
        let key = intent.key.clone();
        let current = self
            .get_provider_effect(&key)
            .await?
            .ok_or_else(|| EvidenceError::Corrupt("provider effect intent disappeared".into()))?;
        if current.state() != ProviderEffectState::Pending {
            return Ok(ProviderEffectQualificationDispatchReceipt {
                state: current.state(),
                dispatch_claimed: false,
                dispatch_attempted: false,
            });
        }
        if intent_disposition == AppendDisposition::AlreadyPresent
            && current.acknowledgements.is_empty()
            && current.uncertainties.is_empty()
        {
            // A Pending intent imported from another local journal (or left
            // behind by a crash before this facade's claim) has no durable
            // proof that this caller owns the physical dispatch boundary.
            // Persist quarantine first; reconciliation may still resolve a
            // later provider ACK, but blind redispatch is forbidden.
            self.mark_provider_effect_indeterminate(&key, PROVIDER_EFFECT_IMPORTED_PENDING_REASON)
                .await?;
            return Ok(ProviderEffectQualificationDispatchReceipt {
                state: ProviderEffectState::Indeterminate,
                dispatch_claimed: false,
                dispatch_attempted: false,
            });
        }

        let boundary_claim = self.claim_provider_effect_dispatch_boundary(&key).await?;
        let claimed = boundary_claim.is_some();
        let after_claim = self
            .get_provider_effect(&key)
            .await?
            .ok_or_else(|| EvidenceError::Corrupt("provider effect claim disappeared".into()))?;
        // A concurrent caller may have won the claim, or a reconciler may
        // have appended an ACK while this call was between transactions.  In
        // either case, do not cross the adapter boundary a second time.  The
        // ACK check is also needed when a separate store open bypasses the
        // process-local mutex.
        if !claimed
            || after_claim.state() != ProviderEffectState::Indeterminate
            || after_claim.uncertainties.len() != 1
            || !after_claim.acknowledgements.is_empty()
        {
            return Ok(ProviderEffectQualificationDispatchReceipt {
                state: after_claim.state(),
                dispatch_claimed: claimed,
                dispatch_attempted: false,
            });
        }

        // An unsupported capability is explicitly fail-closed: retain the
        // durable quarantine but never invoke even a nominal adapter method.
        if adapter.capability() == ProviderEffectIdempotencyCapability::Unsupported {
            self.mark_provider_effect_indeterminate(&key, "provider_capability_unsupported")
                .await?;
            return Ok(ProviderEffectQualificationDispatchReceipt {
                state: ProviderEffectState::Indeterminate,
                dispatch_claimed: true,
                dispatch_attempted: false,
            });
        }

        let dispatch = adapter.dispatch(intent).await;
        match dispatch {
            ProviderEffectDispatch::Ack(ack) => {
                let ack_result = match ack.validate_for(intent) {
                    Ok(()) => {
                        self.append_provider_effect_ack_with_boundary_claim(
                            &ack,
                            ProviderEffectAckSource::DispatchResponse,
                            boundary_claim.as_ref(),
                        )
                        .await
                    }
                    Err(error) => Err(binding_invalid(error)),
                };
                if let Err(error) = ack_result {
                    // A malformed/lost ACK must leave a durable quarantine
                    // marker before the error escapes to the caller.
                    if let Err(quarantine_error) = self
                        .mark_provider_effect_indeterminate(&key, "provider_dispatch_ack_invalid")
                        .await
                    {
                        return Err(EvidenceError::Corrupt(format!(
                            "provider dispatch ACK failed ({error}); durable quarantine failed ({quarantine_error})"
                        )));
                    }
                    return Err(error);
                }
            }
            ProviderEffectDispatch::Rejected { reason_code } => {
                self.mark_provider_effect_indeterminate(
                    &key,
                    qualification_reason_code(&reason_code, "provider_dispatch_rejected"),
                )
                .await?;
            }
            ProviderEffectDispatch::NotDispatched { reason_code } => {
                self.mark_provider_effect_indeterminate(
                    &key,
                    qualification_reason_code(&reason_code, "provider_not_dispatched"),
                )
                .await?;
            }
            ProviderEffectDispatch::Unknown => {
                self.mark_provider_effect_indeterminate(&key, "provider_dispatch_unknown")
                    .await?;
            }
        }
        let state = self
            .get_provider_effect(&key)
            .await?
            .map(|effect| effect.state())
            .unwrap_or(ProviderEffectState::Indeterminate);
        Ok(ProviderEffectQualificationDispatchReceipt {
            state,
            dispatch_claimed: true,
            dispatch_attempted: true,
        })
    }

    /// Reconcile an existing intent through lookup.  The intent may have been
    /// claimed by this facade or explicitly imported from another local
    /// journal; this path never calls `dispatch`, including after a reopen.
    /// `Unknown`/`NotFound` outcomes remain durably quarantined and therefore
    /// cannot be sent again by the dispatch facade.
    pub async fn reconcile_provider_effect_with_adapter<A: ProviderEffectAdapter + ?Sized>(
        &self,
        adapter: &A,
        key: &ProviderEffectKey,
    ) -> Result<ProviderEffectState, EvidenceError> {
        let _boundary_guard = self
            .provider_effect_boundary_lock
            .clone()
            .lock_owned()
            .await;
        let stored = self.get_provider_effect(key).await?.ok_or_else(|| {
            EvidenceError::InvalidRecord("provider effect intent not found".into())
        })?;
        if stored.state().is_terminal() {
            return Ok(stored.state());
        }
        let capability = adapter.capability();
        if capability == ProviderEffectIdempotencyCapability::Unsupported {
            return self
                .reconcile_provider_effect_lookup(capability, key, ProviderEffectLookup::Unknown)
                .await;
        }
        // Pass the authoritative intent, not only its occurrence key, so a
        // transport that supports it can bind the status query to the exact
        // payload digest before returning an ACK.  The trait's compatibility
        // default still serves older qualification adapters.
        let lookup = adapter.lookup_for_intent(&stored.intent.intent).await;
        match lookup {
            ProviderEffectLookup::Ack(ack) => {
                match self
                    .reconcile_provider_effect_lookup(
                        capability,
                        key,
                        ProviderEffectLookup::Ack(ack),
                    )
                    .await
                {
                    Ok(state) => Ok(state),
                    Err(error) => {
                        // A malformed or conflicting lookup ACK must close
                        // the local occurrence before the error escapes; a
                        // later dispatch facade call must not treat it as
                        // fresh Pending work.
                        let quarantine_required = matches!(
                            &error,
                            EvidenceError::InvalidRecord(_)
                                | EvidenceError::IdempotencyConflict { .. }
                        );
                        if quarantine_required
                            && let Err(quarantine_error) = self
                                .mark_provider_effect_indeterminate(
                                    key,
                                    "provider_reconcile_ack_invalid",
                                )
                                .await
                        {
                            return Err(EvidenceError::Corrupt(format!(
                                "provider reconcile ACK failed ({error}); durable quarantine failed ({quarantine_error})"
                            )));
                        }
                        Err(error)
                    }
                }
            }
            lookup => {
                self.reconcile_provider_effect_lookup(capability, key, lookup)
                    .await
            }
        }
    }

    /// Appends a provider ACK after validating it against the authoritative
    /// intent and the monotonic Accepted → Completed transition rules.
    pub async fn append_provider_effect_ack(
        &self,
        ack: &ProviderEffectAck,
    ) -> Result<AppendDisposition, EvidenceError> {
        self.append_provider_effect_ack_from_source(ack, ProviderEffectAckSource::DispatchResponse)
            .await
    }

    /// Appends an ACK with explicit local provenance.  Callers handling a
    /// provider status lookup must use `StatusLookup`; the compatibility
    /// wrapper above deliberately defaults to the conservative dispatch
    /// response source.
    pub async fn append_provider_effect_ack_from_source(
        &self,
        ack: &ProviderEffectAck,
        source: ProviderEffectAckSource,
    ) -> Result<AppendDisposition, EvidenceError> {
        self.append_provider_effect_ack_with_boundary_claim(
            ack, source, /*boundary_claim*/ None,
        )
        .await
    }

    /// Appends a provider-owned status observation as a durable qualification
    /// receipt.  The observation is secret-free and carries explicit
    /// `StatusLookup` provenance; no provider or network call is made here.
    /// The ACK/source table is the durable projection, so the existing
    /// authoritative-intent binding and monotonic transition checks apply.
    pub async fn append_provider_effect_status_observation(
        &self,
        observation: &ProviderEffectStatusObservation,
    ) -> Result<AppendDisposition, EvidenceError> {
        observation.validate().map_err(binding_invalid)?;
        self.append_provider_effect_ack_from_source(
            &observation.to_ack(),
            ProviderEffectAckSource::StatusLookup,
        )
        .await
    }

    async fn append_provider_effect_ack_with_boundary_claim(
        &self,
        ack: &ProviderEffectAck,
        source: ProviderEffectAckSource,
        boundary_claim: Option<&DispatchBoundaryClaim>,
    ) -> Result<AppendDisposition, EvidenceError> {
        let payload = canonical_json(ack)?;
        let payload_json = String::from_utf8(payload.clone())
            .map_err(|error| EvidenceError::Serialization(error.to_string()))?;
        let record_sha256 = Sha256Digest::for_bytes(&payload);
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let intent = load_effect_intent_in_transaction(&mut transaction, &ack.key).await?;
        let Some(intent) = intent else {
            transaction.rollback().await.map_err(classify_sqlx_error)?;
            return Err(EvidenceError::InvalidRecord(
                "provider effect acknowledgement has no authoritative intent".to_string(),
            ));
        };
        ack.validate_for(&intent.intent).map_err(binding_invalid)?;
        validate_ack_transition_in_transaction(
            &mut transaction,
            &intent.intent,
            ack,
            source,
            boundary_claim,
        )
        .await?;
        let recorded_at_ms = next_effect_recorded_at_ms(&mut transaction, &ack.key).await?;
        let insert = sqlx::query(
            "INSERT INTO provider_effect_acknowledgements (
                effect_key, payload_sha256, provider_operation_id_sha256,
                status, source, schema_version, payload_json, record_sha256, recorded_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT DO NOTHING",
        )
        .bind(ack.key.as_str())
        .bind(ack.payload_sha256.as_str())
        .bind(ack.provider_operation_id_sha256.as_str())
        .bind(ack_status_as_str(ack.status))
        .bind(source.as_str())
        .bind(i64::from(ack.schema_version))
        .bind(&payload_json)
        .bind(record_sha256.as_str())
        .bind(recorded_at_ms)
        .execute(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;
        let disposition = verify_effect_ack(
            &mut transaction,
            ack,
            source,
            &payload_json,
            record_sha256.as_str(),
            insert.rows_affected() == 1,
        )
        .await?;
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(disposition)
    }

    /// Appends a durable quarantine marker for an unknown provider outcome.
    ///
    /// This method is intentionally separate from ACK persistence: an
    /// uncertainty never claims that the provider applied (or rejected) the
    /// effect.  A later key-bound ACK may reconcile it.
    pub async fn mark_provider_effect_indeterminate(
        &self,
        key: &ProviderEffectKey,
        reason_code: impl Into<String>,
    ) -> Result<AppendDisposition, EvidenceError> {
        let reason_code = reason_code.into();
        if reason_code == PROVIDER_EFFECT_DISPATCH_BOUNDARY_PENDING_REASON {
            return Err(EvidenceError::InvalidRecord(
                "provider dispatch boundary claim is reserved to the qualification facade"
                    .to_string(),
            ));
        }
        self.append_provider_effect_uncertainty(
            key,
            reason_code,
            /*allow_reserved_reason*/ false,
        )
        .await
        .map(|(disposition, _)| disposition)
    }

    /// Mints the one local witness that permits the dispatch facade's own
    /// response to close its pre-dispatch boundary claim.  The reserved
    /// reason cannot be created through the public quarantine API, so a raw
    /// caller cannot manufacture this exception and bypass late-ACK fencing.
    async fn claim_provider_effect_dispatch_boundary(
        &self,
        key: &ProviderEffectKey,
    ) -> Result<Option<DispatchBoundaryClaim>, EvidenceError> {
        let (disposition, recorded_at_ms) = self
            .append_provider_effect_uncertainty(
                key,
                PROVIDER_EFFECT_DISPATCH_BOUNDARY_PENDING_REASON.to_string(),
                /*allow_reserved_reason*/ true,
            )
            .await?;
        Ok(
            (disposition == AppendDisposition::Inserted).then(|| DispatchBoundaryClaim {
                key: key.clone(),
                recorded_at_ms,
            }),
        )
    }

    async fn append_provider_effect_uncertainty(
        &self,
        key: &ProviderEffectKey,
        reason_code: String,
        allow_reserved_reason: bool,
    ) -> Result<(AppendDisposition, i64), EvidenceError> {
        if !allow_reserved_reason && reason_code == PROVIDER_EFFECT_DISPATCH_BOUNDARY_PENDING_REASON
        {
            return Err(EvidenceError::InvalidRecord(
                "provider dispatch boundary claim is reserved to the qualification facade"
                    .to_string(),
            ));
        }
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let intent = load_effect_intent_in_transaction(&mut transaction, key).await?;
        let Some(intent) = intent else {
            transaction.rollback().await.map_err(classify_sqlx_error)?;
            return Err(EvidenceError::InvalidRecord(
                "provider effect uncertainty has no authoritative intent".to_string(),
            ));
        };
        let uncertainty = ProviderEffectUncertainty::new(
            key.clone(),
            intent.intent.payload_sha256.clone(),
            reason_code,
        );
        uncertainty
            .validate_for(&intent.intent)
            .map_err(binding_invalid)?;
        if latest_ack_is_terminal(&mut transaction, &intent.intent, key).await? {
            transaction.rollback().await.map_err(classify_sqlx_error)?;
            return Err(EvidenceError::IdempotencyConflict {
                record_id: key.as_str().to_string(),
            });
        }
        let payload = canonical_json(&uncertainty)?;
        let payload_json = String::from_utf8(payload.clone())
            .map_err(|error| EvidenceError::Serialization(error.to_string()))?;
        let record_sha256 = Sha256Digest::for_bytes(&payload);
        let recorded_at_ms = next_effect_recorded_at_ms(&mut transaction, key).await?;
        let insert = sqlx::query(
            "INSERT INTO provider_effect_uncertainties (
                effect_key, payload_sha256, reason_code, schema_version,
                payload_json, record_sha256, recorded_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT DO NOTHING",
        )
        .bind(key.as_str())
        .bind(uncertainty.payload_sha256.as_str())
        .bind(&uncertainty.reason_code)
        .bind(i64::from(uncertainty.schema_version))
        .bind(&payload_json)
        .bind(record_sha256.as_str())
        .bind(recorded_at_ms)
        .execute(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;
        let disposition = verify_effect_uncertainty(
            &mut transaction,
            &uncertainty,
            &payload_json,
            record_sha256.as_str(),
            insert.rows_affected() == 1,
        )
        .await?;
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok((disposition, recorded_at_ms))
    }

    pub async fn get_provider_effect(
        &self,
        key: &ProviderEffectKey,
    ) -> Result<Option<StoredProviderEffect>, EvidenceError> {
        let mut transaction = self.pool.begin().await.map_err(classify_sqlx_error)?;
        let intent = load_effect_intent_in_transaction(&mut transaction, key).await?;
        let Some(intent) = intent else {
            transaction.commit().await.map_err(classify_sqlx_error)?;
            return Ok(None);
        };
        let rows = sqlx::query(
            "SELECT seq, effect_key, payload_sha256,
                    provider_operation_id_sha256, status, source, schema_version,
                    payload_json, record_sha256, recorded_at_ms
             FROM provider_effect_acknowledgements
             WHERE effect_key = ? ORDER BY seq ASC",
        )
        .bind(key.as_str())
        .fetch_all(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;
        let mut acknowledgements = Vec::with_capacity(rows.len());
        for row in rows {
            acknowledgements.push(decode_effect_ack_row(&row, &intent.intent)?);
        }
        let uncertainty_rows = sqlx::query(
            "SELECT seq, effect_key, payload_sha256, reason_code,
                    schema_version, payload_json, record_sha256, recorded_at_ms
             FROM provider_effect_uncertainties
             WHERE effect_key = ? ORDER BY recorded_at_ms ASC, seq ASC",
        )
        .bind(key.as_str())
        .fetch_all(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;
        let mut uncertainties = Vec::with_capacity(uncertainty_rows.len());
        for row in uncertainty_rows {
            uncertainties.push(decode_effect_uncertainty_row(&row, &intent.intent)?);
        }
        acknowledgements.sort_by_key(|ack| (ack.recorded_at_ms, ack.seq));
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(Some(StoredProviderEffect {
            intent,
            acknowledgements,
            uncertainties,
        }))
    }

    /// Reconciles a lookup and appends a matching ACK. Unknown, not-found,
    /// and conflict lookups persist a quarantine marker only for non-terminal
    /// local state; a durable Completed/Rejected ACK is returned unchanged.
    pub async fn reconcile_provider_effect_lookup(
        &self,
        capability: ProviderEffectIdempotencyCapability,
        key: &ProviderEffectKey,
        lookup: ProviderEffectLookup,
    ) -> Result<ProviderEffectState, EvidenceError> {
        let stored = self.get_provider_effect(key).await?.ok_or_else(|| {
            EvidenceError::InvalidRecord("provider effect intent not found".into())
        })?;
        // A durable terminal acknowledgement is authoritative for this local
        // occurrence.  Late Unknown/NotFound/Conflict observations must not
        // append a new uncertainty row and make a completed/rejected effect
        // appear Indeterminate.  An ACK is different: validate its exact
        // key/payload binding and let the append path distinguish an exact
        // replay from a conflicting acknowledgement.
        if stored.state().is_terminal() {
            if let ProviderEffectLookup::Ack(ack) = &lookup {
                ack.validate_for(&stored.intent.intent)
                    .map_err(binding_invalid)?;
                self.append_provider_effect_ack_from_source(
                    ack,
                    ProviderEffectAckSource::StatusLookup,
                )
                .await?;
            }
            return Ok(stored.state());
        }
        if capability == ProviderEffectIdempotencyCapability::Unsupported {
            self.mark_provider_effect_indeterminate(key, "provider_capability_unsupported")
                .await?;
            return Err(EvidenceError::InvalidRecord(
                "provider effect status lookup is unsupported".to_string(),
            ));
        }
        match lookup {
            ProviderEffectLookup::Ack(ack) => {
                let ack = reconcile_provider_lookup(
                    capability,
                    &stored.intent.intent,
                    ProviderEffectLookup::Ack(ack),
                )
                .map_err(binding_invalid)?;
                self.append_provider_effect_ack_from_source(
                    &ack,
                    ProviderEffectAckSource::StatusLookup,
                )
                .await?;
            }
            ProviderEffectLookup::Unknown => {
                self.mark_provider_effect_indeterminate(key, "provider_lookup_unknown")
                    .await?;
            }
            ProviderEffectLookup::NotFound => {
                self.mark_provider_effect_indeterminate(key, "provider_status_not_found")
                    .await?;
            }
            ProviderEffectLookup::Conflict { .. } => {
                self.mark_provider_effect_indeterminate(key, "provider_payload_conflict")
                    .await?;
            }
        }
        Ok(self
            .get_provider_effect(key)
            .await?
            .map(|effect| effect.state())
            .unwrap_or(ProviderEffectState::Indeterminate))
    }

    /// Reconciles one already-obtained provider status observation without
    /// performing a lookup.  This is a qualification-only ingestion boundary:
    /// callers must obtain the observation through their own authorized
    /// provider integration and pass only the signed/digest-only envelope.
    pub async fn reconcile_provider_effect_status_observation(
        &self,
        observation: &ProviderEffectStatusObservation,
    ) -> Result<ProviderEffectState, EvidenceError> {
        self.append_provider_effect_status_observation(observation)
            .await?;
        Ok(self
            .get_provider_effect(&observation.key)
            .await?
            .map(|effect| effect.state())
            .unwrap_or(ProviderEffectState::Indeterminate))
    }
}

/// Verifies every durable effect row during evidence-store open.  A schema
/// check alone is insufficient: canonical payloads, projected columns, ACK
/// bindings, and quarantine reasons must all agree before a caller can trust
/// an effect state after restart.
pub(crate) async fn verify_provider_effect_rows(pool: &SqlitePool) -> Result<(), EvidenceError> {
    let intent_rows = sqlx::query(
        "SELECT seq, effect_key, payload_sha256, schema_version,
                payload_json, record_sha256
         FROM provider_effect_intents ORDER BY seq ASC",
    )
    .fetch_all(pool)
    .await
    .map_err(classify_sqlx_error)?;
    for intent_row in intent_rows {
        let intent = decode_effect_intent_row(&intent_row)?;
        let ack_rows = sqlx::query(
            "SELECT seq, effect_key, payload_sha256,
                    provider_operation_id_sha256, status, source, schema_version,
                    payload_json, record_sha256, recorded_at_ms
             FROM provider_effect_acknowledgements
             WHERE effect_key = ? ORDER BY recorded_at_ms ASC, seq ASC",
        )
        .bind(intent.intent.key.as_str())
        .fetch_all(pool)
        .await
        .map_err(classify_sqlx_error)?;
        let uncertainty_rows = sqlx::query(
            "SELECT seq, effect_key, payload_sha256, reason_code,
                    schema_version, payload_json, record_sha256, recorded_at_ms
             FROM provider_effect_uncertainties
             WHERE effect_key = ? ORDER BY recorded_at_ms ASC, seq ASC",
        )
        .bind(intent.intent.key.as_str())
        .fetch_all(pool)
        .await
        .map_err(classify_sqlx_error)?;
        let mut previous_ack: Option<StoredProviderEffectAck> = None;
        let mut terminal_ack: Option<StoredProviderEffectAck> = None;
        for row in ack_rows {
            let ack = decode_effect_ack_row(&row, &intent.intent)?;
            if uncertainty_rows.iter().any(|uncertainty_row| {
                uncertainty_row.get::<i64, _>("recorded_at_ms") == ack.recorded_at_ms
            }) {
                return Err(EvidenceError::Corrupt(
                    "provider effect ACK and uncertainty share an ambiguous timestamp".to_string(),
                ));
            }
            let boundary_dispatch_ack = previous_ack.is_none()
                && ack.source == ProviderEffectAckSource::DispatchResponse
                && uncertainty_rows.len() == 1
                && uncertainty_rows[0].get::<String, _>("reason_code")
                    == PROVIDER_EFFECT_DISPATCH_BOUNDARY_PENDING_REASON
                && uncertainty_rows[0].get::<i64, _>("recorded_at_ms") < ack.recorded_at_ms;
            let uncertainty_before = uncertainty_rows.iter().any(|uncertainty_row| {
                uncertainty_row.get::<i64, _>("recorded_at_ms") < ack.recorded_at_ms
            });
            if uncertainty_before
                && ack.source != ProviderEffectAckSource::StatusLookup
                && !boundary_dispatch_ack
            {
                return Err(EvidenceError::Corrupt(
                    "provider effect dispatch ACK follows an uncertainty quarantine".to_string(),
                ));
            }
            if let Some(previous) = previous_ack.as_ref() {
                let uncertainty_between = uncertainty_rows.iter().any(|uncertainty_row| {
                    let recorded_at_ms = uncertainty_row.get::<i64, _>("recorded_at_ms");
                    recorded_at_ms > previous.recorded_at_ms && recorded_at_ms < ack.recorded_at_ms
                });
                if previous.ack.state().is_terminal() {
                    return Err(EvidenceError::Corrupt(
                        "provider effect terminal ACK has a later ACK".to_string(),
                    ));
                }
                let legal_status_transition = matches!(
                    (previous.ack.status, ack.ack.status),
                    (
                        ProviderEffectAckStatus::Accepted,
                        ProviderEffectAckStatus::Accepted
                    ) | (
                        ProviderEffectAckStatus::Accepted,
                        ProviderEffectAckStatus::Completed
                    )
                );
                let operation_rebound = previous.ack.provider_operation_id_sha256
                    != ack.ack.provider_operation_id_sha256;
                let legal = if uncertainty_between {
                    // An uncertainty can justify rebinding the provider
                    // operation id, but never permits Accepted -> Rejected.
                    ack.source == ProviderEffectAckSource::StatusLookup && legal_status_transition
                } else {
                    legal_status_transition && !operation_rebound
                };
                if !legal {
                    return Err(EvidenceError::Corrupt(
                        "provider effect ACK transition is not monotonic".to_string(),
                    ));
                }
            }
            if ack.ack.state().is_terminal() {
                terminal_ack = Some(ack.clone());
            }
            previous_ack = Some(ack);
        }
        for row in uncertainty_rows {
            let uncertainty = decode_effect_uncertainty_row(&row, &intent.intent)?;
            if let Some(terminal) = terminal_ack.as_ref() {
                // The public append path rejects this transition.  Repeat
                // the invariant during startup verification so a damaged or
                // imported store cannot downgrade a terminal provider result
                // to Indeterminate merely by appending a late quarantine row.
                // ACK and uncertainty `seq` values come from separate
                // AUTOINCREMENT tables and are not a shared journal order.
                // The per-key recorded timestamp is the only cross-table
                // ordering witness; public append paths make it strictly
                // increasing.
                let follows_terminal = uncertainty.recorded_at_ms >= terminal.recorded_at_ms;
                if follows_terminal {
                    return Err(EvidenceError::Corrupt(
                        "provider effect uncertainty follows terminal ACK".to_string(),
                    ));
                }
            }
        }
    }
    Ok(())
}

async fn load_effect_intent_in_transaction(
    transaction: &mut Transaction<'_, Sqlite>,
    key: &ProviderEffectKey,
) -> Result<Option<StoredProviderEffectIntent>, EvidenceError> {
    let row = sqlx::query(
        "SELECT seq, effect_key, payload_sha256, schema_version,
                payload_json, record_sha256
         FROM provider_effect_intents WHERE effect_key = ?",
    )
    .bind(key.as_str())
    .fetch_optional(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    row.map(|row| decode_effect_intent_row(&row)).transpose()
}

fn decode_effect_intent_row(
    row: &sqlx::sqlite::SqliteRow,
) -> Result<StoredProviderEffectIntent, EvidenceError> {
    let payload_json: String = row.get("payload_json");
    let record_sha256: String = row.get("record_sha256");
    verify_record_digest(&payload_json, &record_sha256, "provider effect intent")?;
    let intent: ProviderEffectIntent = serde_json::from_str(&payload_json)
        .map_err(|error| EvidenceError::Corrupt(error.to_string()))?;
    intent.validate().map_err(binding_corrupt)?;
    let payload_sha256: String = row.get("payload_sha256");
    if row.get::<String, _>("effect_key") != intent.key.as_str()
        || payload_sha256 != intent.payload_sha256.as_str()
        || row.get::<i64, _>("schema_version") != i64::from(intent.schema_version)
    {
        return Err(EvidenceError::Corrupt(
            "provider effect intent columns do not match canonical payload".to_string(),
        ));
    }
    Ok(StoredProviderEffectIntent {
        seq: row.get("seq"),
        intent,
    })
}

fn decode_effect_ack_row(
    row: &sqlx::sqlite::SqliteRow,
    intent: &ProviderEffectIntent,
) -> Result<StoredProviderEffectAck, EvidenceError> {
    let payload_json: String = row.get("payload_json");
    let record_sha256: String = row.get("record_sha256");
    verify_record_digest(
        &payload_json,
        &record_sha256,
        "provider effect acknowledgement",
    )?;
    let ack: ProviderEffectAck = serde_json::from_str(&payload_json)
        .map_err(|error| EvidenceError::Corrupt(error.to_string()))?;
    ack.validate_for(intent).map_err(binding_corrupt)?;
    let status: String = row.get("status");
    let source: Option<String> = row.try_get("source").map_err(classify_sqlx_error)?;
    let source = source
        .ok_or_else(|| {
            EvidenceError::Corrupt(
                "provider effect acknowledgement source provenance is missing".to_string(),
            )
        })
        .and_then(|source| ProviderEffectAckSource::parse(&source).map_err(binding_corrupt))?;
    if row.get::<String, _>("effect_key") != ack.key.as_str()
        || row.get::<String, _>("payload_sha256") != ack.payload_sha256.as_str()
        || row.get::<String, _>("provider_operation_id_sha256")
            != ack.provider_operation_id_sha256.as_str()
        || status != ack_status_as_str(ack.status)
        || row.get::<i64, _>("schema_version") != i64::from(ack.schema_version)
    {
        return Err(EvidenceError::Corrupt(
            "provider effect acknowledgement columns do not match canonical payload".to_string(),
        ));
    }
    Ok(StoredProviderEffectAck {
        seq: row.get("seq"),
        ack,
        source,
        recorded_at_ms: row.get("recorded_at_ms"),
    })
}

fn decode_effect_uncertainty_row(
    row: &sqlx::sqlite::SqliteRow,
    intent: &ProviderEffectIntent,
) -> Result<StoredProviderEffectUncertainty, EvidenceError> {
    let payload_json: String = row.get("payload_json");
    let record_sha256: String = row.get("record_sha256");
    verify_record_digest(&payload_json, &record_sha256, "provider effect uncertainty")?;
    let uncertainty: ProviderEffectUncertainty = serde_json::from_str(&payload_json)
        .map_err(|error| EvidenceError::Corrupt(error.to_string()))?;
    uncertainty.validate_for(intent).map_err(binding_corrupt)?;
    if row.get::<String, _>("effect_key") != uncertainty.key.as_str()
        || row.get::<String, _>("payload_sha256") != uncertainty.payload_sha256.as_str()
        || row.get::<String, _>("reason_code") != uncertainty.reason_code
        || row.get::<i64, _>("schema_version") != i64::from(uncertainty.schema_version)
    {
        return Err(EvidenceError::Corrupt(
            "provider effect uncertainty columns do not match canonical payload".to_string(),
        ));
    }
    Ok(StoredProviderEffectUncertainty {
        seq: row.get("seq"),
        uncertainty,
        recorded_at_ms: row.get("recorded_at_ms"),
    })
}

async fn verify_effect_intent(
    transaction: &mut Transaction<'_, Sqlite>,
    intent: &ProviderEffectIntent,
    payload_json: &str,
    record_sha256: &str,
    inserted: bool,
) -> Result<AppendDisposition, EvidenceError> {
    let row = sqlx::query(
        "SELECT seq, effect_key, payload_sha256, schema_version,
                payload_json, record_sha256
         FROM provider_effect_intents WHERE effect_key = ?",
    )
    .bind(intent.key.as_str())
    .fetch_optional(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?
    .ok_or_else(|| EvidenceError::Corrupt("provider effect intent disappeared".to_string()))?;
    let stored = decode_effect_intent_row(&row)?;
    if stored.intent != *intent
        || row.get::<String, _>("payload_json") != payload_json
        || row.get::<String, _>("record_sha256") != record_sha256
    {
        return Err(EvidenceError::IdempotencyConflict {
            record_id: intent.key.as_str().to_string(),
        });
    }
    Ok(if inserted {
        AppendDisposition::Inserted
    } else {
        AppendDisposition::AlreadyPresent
    })
}

async fn verify_effect_ack(
    transaction: &mut Transaction<'_, Sqlite>,
    ack: &ProviderEffectAck,
    source: ProviderEffectAckSource,
    payload_json: &str,
    record_sha256: &str,
    inserted: bool,
) -> Result<AppendDisposition, EvidenceError> {
    let rows = sqlx::query(
        "SELECT seq, effect_key, payload_sha256,
                provider_operation_id_sha256, status, source, schema_version,
                payload_json, record_sha256, recorded_at_ms
         FROM provider_effect_acknowledgements
         WHERE effect_key = ? AND provider_operation_id_sha256 = ?
           AND status = ? AND payload_sha256 = ?",
    )
    .bind(ack.key.as_str())
    .bind(ack.provider_operation_id_sha256.as_str())
    .bind(ack_status_as_str(ack.status))
    .bind(ack.payload_sha256.as_str())
    .fetch_all(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    if rows.len() != 1 {
        return Err(EvidenceError::Corrupt(format!(
            "expected one provider effect acknowledgement row but found {}",
            rows.len()
        )));
    }
    let intent = load_effect_intent_in_transaction(transaction, &ack.key)
        .await?
        .ok_or_else(|| EvidenceError::Corrupt("provider effect ACK lost its intent".to_string()))?;
    let stored = decode_effect_ack_row(&rows[0], &intent.intent)?;
    if stored.ack != *ack
        || (inserted && stored.source != source)
        || rows[0].get::<String, _>("payload_json") != payload_json
        || rows[0].get::<String, _>("record_sha256") != record_sha256
    {
        return Err(EvidenceError::IdempotencyConflict {
            record_id: ack.key.as_str().to_string(),
        });
    }
    Ok(if inserted {
        AppendDisposition::Inserted
    } else {
        AppendDisposition::AlreadyPresent
    })
}

async fn verify_effect_uncertainty(
    transaction: &mut Transaction<'_, Sqlite>,
    uncertainty: &ProviderEffectUncertainty,
    payload_json: &str,
    record_sha256: &str,
    inserted: bool,
) -> Result<AppendDisposition, EvidenceError> {
    let rows = sqlx::query(
        "SELECT seq, effect_key, payload_sha256, reason_code,
                schema_version, payload_json, record_sha256, recorded_at_ms
         FROM provider_effect_uncertainties
         WHERE effect_key = ? AND payload_sha256 = ? AND reason_code = ?",
    )
    .bind(uncertainty.key.as_str())
    .bind(uncertainty.payload_sha256.as_str())
    .bind(&uncertainty.reason_code)
    .fetch_all(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    if rows.len() != 1 {
        return Err(EvidenceError::Corrupt(format!(
            "expected one provider effect uncertainty row but found {}",
            rows.len()
        )));
    }
    let intent = load_effect_intent_in_transaction(transaction, &uncertainty.key)
        .await?
        .ok_or_else(|| {
            EvidenceError::Corrupt("provider effect uncertainty lost its intent".to_string())
        })?;
    let stored = decode_effect_uncertainty_row(&rows[0], &intent.intent)?;
    if stored.uncertainty != *uncertainty
        || rows[0].get::<String, _>("payload_json") != payload_json
        || rows[0].get::<String, _>("record_sha256") != record_sha256
    {
        return Err(EvidenceError::IdempotencyConflict {
            record_id: uncertainty.key.as_str().to_string(),
        });
    }
    Ok(if inserted {
        AppendDisposition::Inserted
    } else {
        AppendDisposition::AlreadyPresent
    })
}

async fn validate_ack_transition_in_transaction(
    transaction: &mut Transaction<'_, Sqlite>,
    intent: &ProviderEffectIntent,
    next: &ProviderEffectAck,
    source: ProviderEffectAckSource,
    boundary_claim: Option<&DispatchBoundaryClaim>,
) -> Result<(), EvidenceError> {
    let ack_rows = sqlx::query(
        "SELECT seq, effect_key, payload_sha256,
                provider_operation_id_sha256, status, source, schema_version,
                payload_json, record_sha256, recorded_at_ms
         FROM provider_effect_acknowledgements
         WHERE effect_key = ? ORDER BY seq ASC",
    )
    .bind(next.key.as_str())
    .fetch_all(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    let mut previous = None;
    for row in ack_rows {
        previous = Some(decode_effect_ack_row(&row, intent)?);
    }
    let uncertainty_rows = sqlx::query(
        "SELECT seq, effect_key, payload_sha256, reason_code,
                schema_version, payload_json, record_sha256, recorded_at_ms
         FROM provider_effect_uncertainties
         WHERE effect_key = ? ORDER BY recorded_at_ms ASC, seq ASC",
    )
    .bind(next.key.as_str())
    .fetch_all(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    let mut uncertainties = Vec::with_capacity(uncertainty_rows.len());
    for row in &uncertainty_rows {
        uncertainties.push(decode_effect_uncertainty_row(row, intent)?);
    }
    if uncertainties.iter().any(|uncertainty| {
        previous
            .as_ref()
            .is_some_and(|ack| uncertainty.recorded_at_ms == ack.recorded_at_ms)
    }) {
        return Err(EvidenceError::Corrupt(
            "provider effect ACK and uncertainty share an ambiguous timestamp".to_string(),
        ));
    }
    let boundary_claim_matches = boundary_claim.is_some_and(|claim| {
        source == ProviderEffectAckSource::DispatchResponse
            && claim.key == next.key
            && previous.is_none()
            && uncertainties.len() == 1
            && uncertainties[0].uncertainty.reason_code
                == PROVIDER_EFFECT_DISPATCH_BOUNDARY_PENDING_REASON
            && uncertainties[0].recorded_at_ms == claim.recorded_at_ms
    });
    if boundary_claim.is_some() && !boundary_claim_matches {
        return Err(EvidenceError::IdempotencyConflict {
            record_id: next.key.as_str().to_string(),
        });
    }
    if let Some(previous) = previous.as_ref()
        && previous.ack == *next
    {
        // Once a provider-owned status lookup has established the exact ACK,
        // a later raw dispatch response cannot forge the same provenance.
        // It must be rejected even when no uncertainty marker is present.
        if source == ProviderEffectAckSource::DispatchResponse
            && previous.source == ProviderEffectAckSource::StatusLookup
        {
            return Err(EvidenceError::IdempotencyConflict {
                record_id: next.key.as_str().to_string(),
            });
        }
        // Exact replays are idempotent even when the durable boundary marker
        // remains in the journal, but a raw dispatch replay after any
        // uncertainty is still forbidden.  A status lookup is an
        // authoritative observation and may repeat the same ACK.
        if uncertainties.is_empty() || source == ProviderEffectAckSource::StatusLookup {
            return Ok(());
        }
        return Err(EvidenceError::IdempotencyConflict {
            record_id: next.key.as_str().to_string(),
        });
    }
    // A provider-owned status lookup is the authoritative observation path.
    // A dispatch response arriving after it may be a delayed response from
    // the original call; it must not advance Accepted -> Completed (or any
    // other state) merely because the operation id happens to match.
    if source == ProviderEffectAckSource::DispatchResponse
        && previous
            .as_ref()
            .is_some_and(|ack| ack.source == ProviderEffectAckSource::StatusLookup)
    {
        return Err(EvidenceError::IdempotencyConflict {
            record_id: next.key.as_str().to_string(),
        });
    }
    if !uncertainties.is_empty()
        && source != ProviderEffectAckSource::StatusLookup
        && !boundary_claim_matches
    {
        return Err(EvidenceError::IdempotencyConflict {
            record_id: next.key.as_str().to_string(),
        });
    }
    let Some(previous) = previous else {
        return Ok(());
    };
    if uncertainties
        .iter()
        .any(|uncertainty| uncertainty.recorded_at_ms > previous.recorded_at_ms)
    {
        if previous.ack.state().is_terminal() {
            return Err(EvidenceError::IdempotencyConflict {
                record_id: next.key.as_str().to_string(),
            });
        }
        // An uncertainty marker permits a later status lookup to bind the
        // provider's authoritative operation id, but it must not weaken the
        // local monotonic state machine.  Once an operation was accepted,
        // only another Accepted observation or a Completed receipt can close
        // it.  Accepted -> Rejected remains fail-closed because the earlier
        // admission leaves open the possibility that the provider applied the
        // effect before the response was lost.
        let legal_after_uncertainty = matches!(
            (previous.ack.status, next.status),
            (
                ProviderEffectAckStatus::Accepted,
                ProviderEffectAckStatus::Accepted
            ) | (
                ProviderEffectAckStatus::Accepted,
                ProviderEffectAckStatus::Completed
            )
        );
        if source == ProviderEffectAckSource::StatusLookup && legal_after_uncertainty {
            return Ok(());
        }
        return Err(EvidenceError::IdempotencyConflict {
            record_id: next.key.as_str().to_string(),
        });
    }
    if previous.ack.provider_operation_id_sha256 != next.provider_operation_id_sha256 {
        return Err(EvidenceError::IdempotencyConflict {
            record_id: next.key.as_str().to_string(),
        });
    }
    let legal = matches!(
        (previous.ack.status, next.status),
        (
            ProviderEffectAckStatus::Accepted,
            ProviderEffectAckStatus::Completed
        ) | (
            ProviderEffectAckStatus::Accepted,
            ProviderEffectAckStatus::Accepted
        )
    );
    if legal {
        Ok(())
    } else {
        Err(EvidenceError::IdempotencyConflict {
            record_id: next.key.as_str().to_string(),
        })
    }
}

async fn latest_ack_is_terminal(
    transaction: &mut Transaction<'_, Sqlite>,
    intent: &ProviderEffectIntent,
    key: &ProviderEffectKey,
) -> Result<bool, EvidenceError> {
    let row = sqlx::query(
        "SELECT seq, effect_key, payload_sha256,
                provider_operation_id_sha256, status, source, schema_version,
                payload_json, record_sha256, recorded_at_ms
         FROM provider_effect_acknowledgements
         WHERE effect_key = ? ORDER BY recorded_at_ms DESC, seq DESC LIMIT 1",
    )
    .bind(key.as_str())
    .fetch_optional(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    row.map(|row| decode_effect_ack_row(&row, intent).map(|ack| ack.ack.state().is_terminal()))
        .transpose()
        .map(|value| value.unwrap_or(false))
}

async fn next_effect_recorded_at_ms(
    transaction: &mut Transaction<'_, Sqlite>,
    key: &ProviderEffectKey,
) -> Result<i64, EvidenceError> {
    let latest_ack: Option<i64> = sqlx::query_scalar(
        "SELECT MAX(recorded_at_ms) FROM provider_effect_acknowledgements
         WHERE effect_key = ?",
    )
    .bind(key.as_str())
    .fetch_one(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    let latest_uncertainty: Option<i64> = sqlx::query_scalar(
        "SELECT MAX(recorded_at_ms) FROM provider_effect_uncertainties
         WHERE effect_key = ?",
    )
    .bind(key.as_str())
    .fetch_one(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    let now = now_millis()?;
    let previous = latest_ack.unwrap_or(0).max(latest_uncertainty.unwrap_or(0));
    Ok(now.max(previous.saturating_add(1)))
}

fn verify_record_digest(
    payload_json: &str,
    expected: &str,
    description: &str,
) -> Result<(), EvidenceError> {
    let actual = Sha256Digest::for_bytes(payload_json.as_bytes());
    if actual.as_str() == expected {
        Ok(())
    } else {
        Err(EvidenceError::Corrupt(format!(
            "{description} canonical record digest does not match stored digest"
        )))
    }
}

fn ack_status_as_str(status: ProviderEffectAckStatus) -> &'static str {
    match status {
        ProviderEffectAckStatus::Accepted => "accepted",
        ProviderEffectAckStatus::Completed => "completed",
        ProviderEffectAckStatus::Rejected => "rejected",
    }
}

fn qualification_reason_code(value: &str, fallback: &'static str) -> String {
    if value.len() <= 128
        && !value.is_empty()
        && value.bytes().all(|byte| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || matches!(byte, b'_' | b'-' | b'.')
        })
    {
        value.to_string()
    } else {
        fallback.to_string()
    }
}

fn binding_invalid(error: ProviderEffectBindingError) -> EvidenceError {
    EvidenceError::InvalidRecord(format!("provider effect binding is invalid: {error:?}"))
}

fn binding_corrupt(error: ProviderEffectBindingError) -> EvidenceError {
    EvidenceError::Corrupt(format!("provider effect binding is corrupt: {error:?}"))
}
