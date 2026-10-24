//! Read the original owner without creating sending or cancellation rights.

use super::*;

/// Immutable retained observations, in original append order. Unknown history
/// never removes an earlier publication. This is not a run or effect status.
pub struct ObjectiveSenderSnapshot {
    pub observations: Vec<ObjectiveSenderObservation>,
    pub locally_cancelled: bool,
}

/// Opaque owner-bound keyset cursor, carrying no authority or send permission.
#[derive(Clone)]
pub struct ObjectiveSenderRetainedCursor {
    owner: codex_hepta_contracts::AgentId,
    after_sha256: String,
}

impl ObjectiveSenderRetainedCursor {
    /// Public navigation data only. The token grants no authority, acknowledgment
    /// or sending permission; the receiving sender always binds its own owner.
    pub fn navigation_token(&self) -> &str {
        &self.after_sha256
    }
}

pub enum ObjectiveSenderRetainedPosition {
    Beginning,
    After(ObjectiveSenderRetainedCursor),
}

/// At most sixteen exact retained requests in the private host capability.
/// These are data, never tickets. Do not forward raw requests to a renderer,
/// model, diagnostics or a second ledger. Use recover_pending for a new read
/// handle. Pagination is live keyset traversal: restart at Beginning to include
/// records concurrently inserted before a previously returned key.
pub struct ObjectiveSenderRetainedPage {
    pub requests: Vec<ObjectiveSenderRequest>,
    pub next: Option<ObjectiveSenderRetainedCursor>,
}

impl<C: ObjectiveSenderCheckpoint> ProductionObjectiveSender<C> {
    /// Verify exact original bytes and origin against the existing row. No
    /// missing row is created and no recovered handle receives a send permit.
    pub async fn recover_pending(
        &self,
        request: ObjectiveSenderRequest,
    ) -> Result<ObjectiveSenderTicket, ObjectiveSenderError> {
        self.writer.sender_live_check()?;
        self.writer.verify_authority().await?;
        if request.origin.agent_id != *self.writer.owner_agent_id() {
            return Err(ObjectiveSenderError::IdentityMismatch);
        }
        let mut transaction = self
            .writer
            .store
            .observation_pool()
            .begin()
            .await
            .map_err(unavailable)?;
        store::require_request(&mut transaction, &request).await?;
        transaction.rollback().await.map_err(unavailable)?;
        self.writer.sender_live_check()?;
        Ok(ObjectiveSenderTicket {
            request,
            local: AtomicU8::new(RECOVERED),
            writer: Arc::downgrade(&self.writer),
        })
    }

    /// Recover original private bytes from this owner after caller memory was
    /// lost. Each page verifies complete request and observation-chain integrity
    /// within one read snapshot and rechecks the retained live authority. This
    /// read cannot mint, reset or acknowledge a sending opportunity.
    pub async fn retained_page(
        &self,
        position: ObjectiveSenderRetainedPosition,
    ) -> Result<ObjectiveSenderRetainedPage, ObjectiveSenderError> {
        self.writer.sender_live_check()?;
        self.writer.verify_authority().await?;
        let after = match position {
            ObjectiveSenderRetainedPosition::Beginning => String::new(),
            ObjectiveSenderRetainedPosition::After(cursor) => {
                if cursor.owner != *self.writer.owner_agent_id() {
                    return Err(ObjectiveSenderError::IdentityMismatch);
                }
                cursor.after_sha256
            }
        };
        let mut transaction = self
            .writer
            .store
            .observation_pool()
            .begin()
            .await
            .map_err(unavailable)?;
        let mut requests =
            store::retained_page(&mut transaction, self.writer.owner_agent_id(), &after).await?;
        let next = if requests.len() > 16 {
            requests.pop();
            Some(ObjectiveSenderRetainedCursor {
                owner: self.writer.owner_agent_id().clone(),
                after_sha256: requests
                    .last()
                    .ok_or(ObjectiveSenderError::Missing)?
                    .identity
                    .original_sha256
                    .as_str()
                    .to_string(),
            })
        } else {
            None
        };
        transaction.rollback().await.map_err(unavailable)?;
        self.writer.sender_live_check()?;
        Ok(ObjectiveSenderRetainedPage { requests, next })
    }

    /// Resume bounded navigation within this sender's fixed owner. A syntactically
    /// valid token may select any historical position; it never proves a complete
    /// scan or grants a send permit. Restart at Beginning for concurrent inserts.
    pub async fn retained_page_after_token(
        &self,
        after: &str,
    ) -> Result<ObjectiveSenderRetainedPage, ObjectiveSenderError> {
        if after.len() != 64
            || !after
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        {
            return Err(ObjectiveSenderError::IdentityMismatch);
        }
        self.retained_page(ObjectiveSenderRetainedPosition::After(
            ObjectiveSenderRetainedCursor {
                owner: self.writer.owner_agent_id().clone(),
                after_sha256: after.to_owned(),
            },
        ))
        .await
    }

    /// Read one exact original request without scanning unrelated history. The
    /// original request and complete observation chain are verified in the same
    /// physical read-only snapshot. A missing record creates no sender ticket.
    pub async fn retained_request_for_run(
        &self,
        run_id: &str,
    ) -> Result<Option<ObjectiveSenderRequest>, ObjectiveSenderError> {
        self.writer.sender_live_check()?;
        self.writer.verify_authority().await?;
        let mut transaction = self
            .writer
            .store
            .observation_pool()
            .begin()
            .await
            .map_err(unavailable)?;
        let request =
            store::retained_request_for_run(&mut transaction, self.writer.owner_agent_id(), run_id)
                .await?;
        transaction.rollback().await.map_err(unavailable)?;
        self.writer.sender_live_check()?;
        Ok(request)
    }

    pub async fn snapshot(
        &self,
        ticket: &ObjectiveSenderTicket,
    ) -> Result<ObjectiveSenderSnapshot, ObjectiveSenderError> {
        self.require_ticket_owner(ticket)?;
        self.writer.sender_live_check()?;
        self.writer.verify_authority().await?;
        let mut transaction = self
            .writer
            .store
            .observation_pool()
            .begin()
            .await
            .map_err(unavailable)?;
        store::require_request(&mut transaction, &ticket.request).await?;
        let snapshot = store::snapshot(&mut transaction, &ticket.request).await?;
        transaction.rollback().await.map_err(unavailable)?;
        self.writer.sender_live_check()?;
        Ok(snapshot)
    }
}
