use super::*;

impl AgentdTextRequests {
    // Owner fencing stays outside the protocol adapter and is checked across
    // every await. A transport substitution cannot bypass the original owner.
    pub(super) async fn observe<T>(
        &self,
        response: impl std::future::Future<Output = Result<T, TextSessionError>>,
    ) -> Result<T, TextSessionError> {
        drop(self.shared.current()?);
        let response = response.await?;
        drop(self.shared.current()?);
        Ok(response)
    }

    /// Sole new-input path. Signatures and sequence numbers come from the
    /// installed independent host. The exact input is retained before I/O.
    /// Repeated calls only look up the original delivery, even after lost ACK.
    pub async fn submit_signed(
        &self,
        envelope: AuthBusTextIngress,
    ) -> Result<AuthBusTextStatus, TextSessionError> {
        self.retain_signed(envelope, false).await
    }

    /// Recover an issuer-retained original after an unknown ACK or new process.
    /// This path NEVER invokes AuthBus submission, even if status is missing.
    pub async fn lookup_signed(
        &self,
        envelope: AuthBusTextIngress,
    ) -> Result<AuthBusTextStatus, TextSessionError> {
        self.retain_signed(envelope, true).await
    }

    async fn retain_signed(
        &self,
        envelope: AuthBusTextIngress,
        lookup_only: bool,
    ) -> Result<AuthBusTextStatus, TextSessionError> {
        let pending = prepare(&self.shared.config, envelope)?;
        let lookup_only = lookup_only
            || pending.envelope.body.spawn_generation != self.shared.config.spawn_generation;
        let existing = {
            let mut state = self.shared.current()?;
            if let Some(old) = state.pending.get(&pending.envelope.message_id) {
                if old.envelope != pending.envelope {
                    return Err(TextSessionError::Identity);
                }
                true
            } else {
                if state.pending.len() >= MAX_RETAINED {
                    return Err(TextSessionError::Capacity);
                }
                state
                    .pending
                    .insert(pending.envelope.message_id.clone(), pending.clone());
                false
            }
        };
        let status = if existing || lookup_only {
            self.shared
                .control
                .authbus_text_status(pending.delivery_id.clone())
                .await
        } else {
            self.shared
                .control
                .submit_authbus_text(pending.envelope)
                .await
        }
        .map_err(unavailable)?;
        drop(self.shared.current()?);
        if status.delivery_id != pending.delivery_id {
            self.fence()?;
            return Err(TextSessionError::Identity);
        }
        Ok(status)
    }

    pub fn connection_id(&self) -> u64 {
        self.shared.connection_id
    }

    pub fn fence(&self) -> Result<(), TextSessionError> {
        self.shared.state()?.fenced = true;
        Ok(())
    }

    /// Lookup only through the same original queue identity and payload digest.
    /// Missing never authorizes allowIfAbsent or a replacement signed message.
    pub async fn reconcile(
        &self,
        message_id: &str,
    ) -> Result<TextReconciliation, TextSessionError> {
        let pending = self
            .shared
            .current()?
            .pending
            .get(message_id)
            .cloned()
            .ok_or(TextSessionError::UnknownRequest)?;
        let delivery = self
            .shared
            .control
            .authbus_text_status(pending.delivery_id.clone())
            .await
            .map_err(unavailable)?;
        if delivery.delivery_id != pending.delivery_id {
            self.fence()?;
            return Err(TextSessionError::Identity);
        }
        let response: ThreadQueueReconcileResponse = self
            .observe(self.shared.backend.reconcile_original(
                pending.input.clone(),
                pending.client_id.clone(),
                pending.input_digest.clone(),
            ))
            .await?;
        if response.client_user_message_id != pending.client_id
            || response.payload_sha256 != pending.input_digest
        {
            self.fence()?;
            return Err(TextSessionError::Identity);
        }
        let mut turn = None;
        match &response.outcome {
            ThreadQueueReconcileOutcome::Queued {
                queued_submission,
                created,
            } => {
                if *created
                    || queued_submission.client_user_message_id != pending.client_id
                    || queued_submission.input != pending.input
                {
                    self.fence()?;
                    return Err(TextSessionError::Identity);
                }
                if pending.cancellation_requested {
                    self.check_current_ingress().await?;
                    let _: ThreadQueueDeleteResponse = self
                        .observe(
                            self.shared
                                .backend
                                .delete_queued(queued_submission.id.clone()),
                        )
                        .await?;
                    // A racing dequeue can return false. Only a later observed
                    // Cancelled or terminal turn is a cancellation outcome.
                }
            }
            ThreadQueueReconcileOutcome::Persisted { turn_id } => {
                if turn_id.is_empty() {
                    self.fence()?;
                    return Err(TextSessionError::Identity);
                }
                self.shared
                    .current()?
                    .pending
                    .get_mut(message_id)
                    .ok_or(TextSessionError::UnknownRequest)?
                    .turn_id = Some(turn_id.clone());
                turn = self.read_turn(turn_id, &pending).await?;
                if pending.cancellation_requested
                    && turn
                        .as_ref()
                        .is_none_or(|turn| turn.status == TurnStatus::InProgress)
                {
                    self.interrupt_turn(turn_id.clone()).await?;
                }
            }
            ThreadQueueReconcileOutcome::Cancelled => {
                self.shared
                    .current()?
                    .pending
                    .get_mut(message_id)
                    .ok_or(TextSessionError::UnknownRequest)?
                    .terminal = true;
            }
            ThreadQueueReconcileOutcome::Missing => {}
        }
        Ok(TextReconciliation {
            message_id: message_id.to_string(),
            delivery,
            queue: response.outcome,
            turn,
        })
    }

    async fn read_turn(
        &self,
        turn_id: &str,
        pending: &Pending,
    ) -> Result<Option<Turn>, TextSessionError> {
        // Bounded pagination avoids loading an unbounded conversation into the
        // renderer. Hitting a history limit leaves the outcome unknown.
        let mut cursor = None;
        for _ in 0..32 {
            let page: ThreadTurnsListResponse = self
                .observe(self.shared.backend.read_turn_page(cursor))
                .await?;
            if serde_json::to_vec(&page).map_err(unavailable)?.len() > MAX_OBSERVATION_BYTES {
                return Err(TextSessionError::Capacity);
            }
            if let Some(turn) = page.data.into_iter().find(|turn| turn.id == turn_id) {
                if turn.items_view != TurnItemsView::Full || !turn.items.iter().any(|item| matches!(item, ThreadItem::UserMessage {client_id: Some(id), content, ..} if id == &pending.client_id && content == &pending.input)) {
                    return Err(TextSessionError::Identity);
                }
                if turn.status != TurnStatus::InProgress {
                    self.shared
                        .current()?
                        .pending
                        .get_mut(&pending.envelope.message_id)
                        .ok_or(TextSessionError::UnknownRequest)?
                        .terminal = true;
                }
                return Ok(Some(turn));
            }
            cursor = page.next_cursor;
            if cursor.is_none() {
                return Ok(None);
            }
        }
        Err(TextSessionError::Capacity)
    }

    /// Records cancellation before awaiting anything. It is not a completion
    /// receipt. While AuthBus is still queued, periodic reconciliation keeps
    /// the intent until the original Core queue/turn can be cancelled.
    pub async fn interrupt(
        &self,
        message_id: &str,
    ) -> Result<TextReconciliation, TextSessionError> {
        self.shared
            .current()?
            .pending
            .get_mut(message_id)
            .ok_or(TextSessionError::UnknownRequest)?
            .cancellation_requested = true;
        self.reconcile(message_id).await
    }

    pub(super) async fn interrupt_turn(&self, turn_id: String) -> Result<(), TextSessionError> {
        self.check_current_ingress().await?;
        {
            let mut state = self.shared.current()?;
            let pending = state
                .pending
                .values_mut()
                .find(|pending| pending.turn_id.as_ref() == Some(&turn_id))
                .ok_or(TextSessionError::UnknownRequest)?;
            if pending.terminal || pending.interrupt_attempted {
                return Ok(());
            }
            // A buffered UserMessage ItemStarted may precede an interruption
            // that already reached Core. Do not issue that cancellation twice
            // while waiting to consume the original terminal observation.
            // Record before I/O so concurrent callers also share this attempt.
            pending.interrupt_attempted = true;
        }
        let _: TurnInterruptResponse = self
            .observe(self.shared.backend.interrupt_turn(turn_id.clone()))
            .await?;
        let mut state = self.shared.current()?;
        let pending = state
            .pending
            .values_mut()
            .find(|pending| pending.turn_id.as_ref() == Some(&turn_id))
            .ok_or(TextSessionError::UnknownRequest)?;
        pending.interrupt_acknowledged = true;
        // Neither an attempt nor its ACK is a completion receipt. Only the
        // original observed terminal event/snapshot can set pending.terminal.
        Ok(())
    }

    async fn check_current_ingress(&self) -> Result<(), TextSessionError> {
        drop(self.shared.current()?);
        let ingress = self
            .shared
            .control
            .session_ingress()
            .await
            .map_err(unavailable)?;
        if ingress.socket_path != self.shared.ingress_socket {
            self.fence()?;
            return Err(TextSessionError::Identity);
        }
        Ok(())
    }

    /// Retires only a resolved presentation correlation slot. Core and AuthBus
    /// continue to own dedupe/history; no durable message or receipt is removed.
    pub fn retire(&self, message_id: &str) -> Result<(), TextSessionError> {
        let mut state = self.shared.current()?;
        if !state
            .pending
            .get(message_id)
            .is_some_and(|pending| pending.terminal)
        {
            return Err(TextSessionError::UnknownRequest);
        }
        state.pending.remove(message_id);
        Ok(())
    }
}
