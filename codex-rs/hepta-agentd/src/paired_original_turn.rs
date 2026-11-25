//! An opt-in, in-process request lane to the original protected turn owner.
//!
//! The returned value is an observation at verification time, not a persisted
//! grant. It cannot be deserialized, cloned or consumed by the legacy Python
//! intake. Native admission still needs its own durable, single-use boundary.

use std::time::Duration;

use codex_hepta_types::Digest32;
use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::PairedLearningDataUse;
use crate::notes_literal_adapter::invalid;
use crate::notes_thread_tool::human::VerifiedHumanTurn;
use crate::text_session::AgentdTextSessionConfig;
use crate::text_session::TextOwnerReceipt;

const DEADLINE: Duration = Duration::from_secs(10);

/// Exact references retained by the original enrollment/intake owner. These
/// fields constrain a live lookup; none is accepted as proof of authority.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PairedTurnRequest {
    pub turn_id: String,
    pub delivery_id: Digest32,
    pub study: Digest32,
    pub usage: PairedLearningDataUse,
    pub expected_principal: String,
}

impl PairedTurnRequest {
    pub(crate) fn validate(&self) -> Result<(), AgentdError> {
        if self.turn_id.is_empty()
            || self.turn_id.len() > 128
            || self.expected_principal.is_empty()
            || self.expected_principal.len() > 128
            || !self
                .expected_principal
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
        {
            return Err(invalid("invalid original paired turn reference"));
        }
        let mut digests = vec![self.study, self.delivery_id];
        match self.usage {
            PairedLearningDataUse::TrainOnFailureAndCorrection {
                failure,
                correction,
            } => digests.extend([failure, correction]),
            PairedLearningDataUse::EvaluateOnlyAfterFreeze { freeze, task } => {
                digests.extend([freeze, task]);
            }
            PairedLearningDataUse::RequestConsumerRun {
                operation,
                pair,
                candidate,
                task,
            } => digests.extend([operation, pair, candidate, task]),
            PairedLearningDataUse::ReportConsumerOutcome {
                operation,
                pair,
                candidate,
                task,
                run_receipt,
                output,
                effect,
                accepted: _,
            } => digests.extend([
                operation,
                pair,
                candidate,
                task,
                run_receipt,
                output,
                effect,
            ]),
        }
        if digests.into_iter().any(Digest32::is_zero) {
            return Err(invalid("zero paired use commitment"));
        }
        Ok(())
    }

    pub(crate) fn match_original(
        &self,
        original_client_id: &str,
        original_text: &str,
        owner: &TextOwnerReceipt,
    ) -> Result<(), AgentdError> {
        self.validate()?;
        if original_client_id != format!("hepta.authbus:{}", self.delivery_id)
            || original_text != self.usage.consent_text(self.study)
            || owner.principal_id != self.expected_principal
        {
            return Err(invalid(
                "original paired turn, principal or exact data use differs",
            ));
        }
        Ok(())
    }

    /// Correlate the retained signed bytes, never a substitute signature or
    /// current human verification. No verified-turn value is created here.
    pub(crate) fn match_ingress(
        &self,
        ingress: &crate::AuthBusTextIngress,
        owner: &TextOwnerReceipt,
    ) -> Result<(), AgentdError> {
        let message = codex_hepta_authbus::SignedMessage {
            claims: crate::authbus_text_claims(&owner.route.agent_id, ingress)?,
            signature: crate::authbus_trust::hex_bytes(&ingress.signature_hex)?,
        };
        self.match_original(
            &format!("hepta.authbus:{}", message.delivery_id()),
            &ingress.body.text,
            owner,
        )?;
        if ingress.body.thread_id != owner.route.thread_id
            || ingress.body.spawn_generation == 0
            || ingress.body.spawn_generation > owner.route.spawn_generation
        {
            return Err(invalid(
                "paired continuation lost its original signed route",
            ));
        }
        Ok(())
    }
}

/// Created only inside the required runtime after original Core, AuthBus and
/// current Root checks. It carries no transferable or replayable grant.
pub struct VerifiedPairedTurn {
    request: PairedTurnRequest,
    owner: TextOwnerReceipt,
    statement_sha256: Digest32,
    ingress: crate::AuthBusTextIngress,
}

impl VerifiedPairedTurn {
    pub(crate) fn from_original(
        request: PairedTurnRequest,
        human: &VerifiedHumanTurn,
        current: TextOwnerReceipt,
    ) -> Result<Self, AgentdError> {
        request.match_original(human.delivery_id(), &human.ingress().body.text, &current)?;
        if !human.owner().same_authorization(&current) {
            return Err(invalid(
                "paired human authorization changed during verification",
            ));
        }
        let verified = Self {
            statement_sha256: Digest32::of_bytes(human.ingress().body.text.as_bytes()),
            request,
            owner: current,
            ingress: human.ingress().clone(),
        };
        verified.original_ingress()?;
        Ok(verified)
    }

    pub fn request(&self) -> &PairedTurnRequest {
        &self.request
    }

    pub fn route(&self) -> &AgentdTextSessionConfig {
        &self.owner.route
    }

    pub fn permission_revision(&self) -> u64 {
        self.owner.permission_revision
    }

    pub fn expires_at_ms(&self) -> u64 {
        self.owner.expires_at_ms
    }

    pub fn statement_sha256(&self) -> Digest32 {
        self.statement_sha256
    }

    /// Borrow the original signed source inside the required owner only. This
    /// correlation check is not a fresh Root check or permission to read data.
    pub(crate) fn original_ingress(&self) -> Result<&crate::AuthBusTextIngress, AgentdError> {
        self.request.match_ingress(&self.ingress, &self.owner)?;
        if Digest32::of_bytes(self.ingress.body.text.as_bytes()) != self.statement_sha256 {
            return Err(invalid(
                "paired continuation lost its original signed delivery",
            ));
        }
        Ok(&self.ingress)
    }
}

pub(crate) struct PendingPairedTurn {
    pub(crate) request: PairedTurnRequest,
    pub(crate) deadline: Instant,
    pub(crate) reply: oneshot::Sender<Result<VerifiedPairedTurn, AgentdError>>,
}

impl PendingPairedTurn {
    pub(crate) async fn verify_on_owner(
        mut self,
        cancellation: &CancellationToken,
        verification: impl std::future::Future<Output = Result<VerifiedPairedTurn, AgentdError>>,
    ) {
        if self.reply.is_closed() {
            return;
        }
        let result = if cancellation.is_cancelled() {
            Err(invalid("original paired owner was cancelled"))
        } else if Instant::now() >= self.deadline {
            Err(invalid("original paired verification deadline elapsed"))
        } else {
            tokio::select! {
                biased;
                _ = cancellation.cancelled() => Err(invalid("original paired owner was cancelled")),
                _ = self.reply.closed() => return,
                verified = tokio::time::timeout_at(self.deadline, verification) => {
                    verified.unwrap_or_else(|_| Err(invalid("original paired verification deadline elapsed")))
                }
            }
        };
        let result = if cancellation.is_cancelled() {
            Err(invalid("original paired owner was cancelled"))
        } else if Instant::now() >= self.deadline {
            Err(invalid("original paired verification deadline elapsed"))
        } else {
            result
        };
        let _ = self.reply.send(result);
    }
}

/// A bounded handle issued only by explicit original-owner configuration.
/// Dropping or restarting that owner closes this particular handle permanently.
pub struct AgentdPairedTurnVerifier {
    sender: mpsc::Sender<PendingPairedTurn>,
}

pub(crate) fn channel() -> (AgentdPairedTurnVerifier, mpsc::Receiver<PendingPairedTurn>) {
    let (sender, receiver) = mpsc::channel(1);
    (AgentdPairedTurnVerifier { sender }, receiver)
}

impl AgentdPairedTurnVerifier {
    /// Verify on the existing protected owner. A timeout is a failed read-only
    /// observation; this method never admits data, starts work or retries.
    pub async fn verify(
        &self,
        request: PairedTurnRequest,
    ) -> Result<VerifiedPairedTurn, AgentdError> {
        request.validate()?;
        let deadline = Instant::now() + DEADLINE;
        let (reply, response) = oneshot::channel();
        self.sender
            .try_send(PendingPairedTurn {
                request,
                deadline,
                reply,
            })
            .map_err(|_| invalid("original paired verifier is closed or occupied"))?;
        tokio::time::timeout_at(deadline, response)
            .await
            .map_err(|_| invalid("original paired verification deadline elapsed"))?
            .map_err(|_| invalid("original paired owner ended before verification"))?
    }
}

#[cfg(test)]
#[path = "paired_original_turn_tests.rs"]
mod tests;
