//! Resolve both previous applications from one complete protected original cut.
use super::*;
use crate::AgentdCalculatorPreviousRecoveryRequest;
use crate::AgentdCalculatorRecoverySelector;
use crate::AgentdNotesPreviousRecoveryRequest;
use crate::AgentdNotesRecoverySelector;
use crate::calculator_deadline::Deadline;
use codex_hepta_memory::CalculatorTargetIdentity;
use codex_hepta_memory::LocalOutcomeState;
use codex_hepta_memory::NotesTargetIdentity;
use std::collections::BTreeSet;

pub(crate) struct ResolvedDesktopOperationIds {
    pub(crate) notes: Option<String>,
    pub(crate) calculator: Option<String>,
}

struct Candidate {
    order: (u64, u64),
    operation_id: String,
    matches_previous: bool,
    retirement_ack: bool,
}

enum Selection<'a> {
    Exact(&'a str),
    Latest,
}

fn select(
    candidates: &[Candidate],
    selector: Selection<'_>,
) -> Result<Option<String>, AgentdError> {
    let mut orders = BTreeSet::new();
    let mut ids = BTreeSet::new();
    for candidate in candidates {
        if !orders.insert(candidate.order) || !ids.insert(&candidate.operation_id) {
            return Err(invalid(
                "previous Desktop recovery has an ambiguous original cut",
            ));
        }
    }
    let mut matching = candidates
        .iter()
        .filter(|candidate| candidate.matches_previous);
    let selected = match selector {
        Selection::Exact(operation_id) => Some(
            matching
                .find(|candidate| candidate.operation_id == operation_id)
                .ok_or_else(|| {
                    invalid("exact Desktop recovery is absent from the original previous target")
                })?,
        ),
        Selection::Latest => matching.max_by_key(|candidate| candidate.order),
    };
    // A single old helper cannot preserve two unresolved operations. Only an
    // original writer's durable, validated target ACK permits ignoring a row.
    if candidates.iter().any(|candidate| {
        !candidate.retirement_ack
            && selected.is_none_or(|chosen| chosen.operation_id != candidate.operation_id)
    }) {
        return Err(invalid(
            "another original Desktop operation still requires retirement",
        ));
    }
    Ok(selected.map(|candidate| candidate.operation_id.clone()))
}

impl AgentdNotesLiteralAdapter {
    pub(crate) async fn desktop_previous_operation_ids(
        &self,
        route: &AgentdTextSessionConfig,
        notes: &AgentdNotesPreviousRecoveryRequest,
        calculator: &AgentdCalculatorPreviousRecoveryRequest,
        deadline: Deadline,
    ) -> Result<ResolvedDesktopOperationIds, AgentdError> {
        deadline.remaining()?;
        self.check_available()?;
        if self.profile != NotesAdapterProfile::OriginalDesktop
            || route.agent_id != self.identity.agent_id
            || route.codex_home != self.identity.home_root
        {
            return Err(invalid(
                "joint recovery requires the exact original Desktop owner and route",
            ));
        }
        let end = tokio::time::Instant::now() + deadline.remaining()?;
        let result = tokio::time::timeout_at(end, async {
            let requests = self
                .sender
                .retained_owner_requests()
                .await
                .map_err(|error| invalid(&error.to_string()))?;
            let mut notes_candidates = Vec::new();
            let mut calculator_candidates = Vec::new();
            let mut orders = BTreeSet::new();
            let mut operation_ids = BTreeSet::new();
            for request in requests {
                deadline.remaining()?;
                self.check_available()?;
                let ingress: AuthBusObjectiveIngress =
                    serde_json::from_slice(request.exact_original())?;
                let source =
                    decode_source_envelope_json_v1(ingress.body.source_envelope_json.as_bytes())
                        .map_err(|error| invalid(&error.to_string()))?;
                if source.input_schema_digest != self.input_schema_digest
                    || source
                        .structured_intent
                        .provenance
                        .normalization_profile_digest
                        != self.normalization_digest
                    || source.principal_scope_digest != self.bindings.principal_scope_digest
                {
                    continue;
                }
                if request.origin().agent_id != self.identity.agent_id
                    || request.origin().spawn_generation > self.identity.spawn_generation
                {
                    return Err(invalid(
                        "previous Desktop cut has another owner or generation",
                    ));
                }
                let reference = request
                    .origin()
                    .original_desktop_thread
                    .as_ref()
                    .ok_or_else(|| invalid("previous Desktop cut has no versioned reference"))?;
                reference
                    .validate_shape()
                    .map_err(|error| invalid(&error.to_string()))?;
                if reference.thread_id != route.thread_id
                    || reference.app_server_session_id != route.app_server_session_id
                {
                    return Err(invalid(
                        "previous Desktop cut differs from the retained original route",
                    ));
                }
                let tool = reference.tool.clone();
                let order = (
                    request.origin().spawn_generation,
                    request.origin().request_id,
                );
                if !orders.insert(order) {
                    return Err(invalid(
                        "previous Desktop cut has an ambiguous original order",
                    ));
                }
                // Verify the exact signed callback and retained operation BEFORE
                // filtering by previous target. A missing/unknown row is fatal.
                let RecordedDesktopLookup::Found(found) =
                    self.verify_desktop_recorded(route, &tool, request).await?
                else {
                    return Err(invalid("previous Desktop operation is unknown"));
                };
                deadline.remaining()?;
                if !operation_ids.insert(found.run_id.clone()) {
                    return Err(invalid(
                        "previous Desktop cut duplicates an original operation",
                    ));
                }
                if !matches!(
                    found.operation.state,
                    LocalOutcomeState::Indeterminate | LocalOutcomeState::Committed
                ) {
                    return Err(invalid(
                        "previous Desktop state does not prove target retirement",
                    ));
                }
                let payload: Value = serde_json::from_str(&found.operation.payload_json)?;
                match tool.as_str() {
                    "hepta_notes_replace" => {
                        let target: NotesTargetIdentity =
                            serde_json::from_value(payload["target"].clone())?;
                        let retirement_ack = match found.operation.state {
                            LocalOutcomeState::Committed => {
                                self.writer
                                    .retained_notes_retirement_ack(&found.run_id)
                                    .await?
                            }
                            _ => false,
                        };
                        notes_candidates.push(Candidate {
                            order,
                            operation_id: found.run_id,
                            matches_previous: target == notes.previous_target,
                            retirement_ack,
                        });
                    }
                    "hepta_calculator_evaluate" => {
                        let target: CalculatorTargetIdentity =
                            serde_json::from_value(payload["target"].clone())?;
                        let retirement_ack = match found.operation.state {
                            LocalOutcomeState::Committed => {
                                self.writer
                                    .retained_calculator_retirement_ack(&found.run_id)
                                    .await?
                            }
                            _ => false,
                        };
                        calculator_candidates.push(Candidate {
                            order,
                            operation_id: found.run_id,
                            matches_previous: target == calculator.previous_target,
                            retirement_ack,
                        });
                    }
                    _ => return Err(invalid("previous Desktop cut contains another effect tool")),
                }
            }
            let notes = select(
                &notes_candidates,
                match &notes.selector {
                    AgentdNotesRecoverySelector::ExactOperation { operation_id } => {
                        Selection::Exact(operation_id)
                    }
                    AgentdNotesRecoverySelector::LatestRecordedOriginalNotes => Selection::Latest,
                },
            )?;
            let calculator = select(
                &calculator_candidates,
                match &calculator.selector {
                    AgentdCalculatorRecoverySelector::ExactOperation { operation_id } => {
                        Selection::Exact(operation_id)
                    }
                    AgentdCalculatorRecoverySelector::LatestRecordedOriginalCalculator => {
                        Selection::Latest
                    }
                },
            )?;
            Ok::<_, AgentdError>(ResolvedDesktopOperationIds { notes, calculator })
        })
        .await
        .map_err(|_| invalid("original joint Desktop recovery cut timed out"))?;
        // Recheck the same suspend-aware end and original Root authority after
        // all asynchronous reads. Late or revoked observations never select.
        deadline.remaining()?;
        self.check_available()?;
        result
    }
}

#[cfg(test)]
#[path = "desktop_thread_recovery_tests.rs"]
mod tests;
