use super::*;

impl AgentdTextRequests {
    pub(super) fn id(&self) -> RequestId {
        RequestId::Integer(self.shared.request_id.fetch_add(1, Ordering::Relaxed))
    }

    pub(super) async fn call<T: serde::de::DeserializeOwned>(
        &self,
        request: ClientRequest,
    ) -> Result<T, TextSessionError> {
        drop(self.shared.current()?);
        let response = tokio::time::timeout(REQUEST_TIMEOUT, self.handle.request_typed(request))
            .await
            .map_err(unavailable)?
            .map_err(unavailable)?;
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

    /// Restore an exact Root-retained reference without issuing any request.
    /// A later submit of this recovered identity is status-only, including for
    /// an older generation. The original issuer owns its durable bytes.
    pub fn restore_signed(&self, envelope: AuthBusTextIngress) -> Result<(), TextSessionError> {
        let mut pending = prepare(&self.shared.config, envelope)?;
        pending.recovered = true;
        let mut state = self.shared.current()?;
        if let Some(old) = state.pending.get_mut(&pending.envelope.message_id) {
            if old.envelope != pending.envelope {
                return Err(TextSessionError::Identity);
            }
            old.recovered = true;
        } else {
            if state.pending.len() >= MAX_RETAINED {
                return Err(TextSessionError::Capacity);
            }
            state
                .pending
                .insert(pending.envelope.message_id.clone(), pending);
        }
        Ok(())
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
        self.reconcile_mode(message_id, ThreadQueueReconcileMode::ReconcileOnly)
            .await
    }

    pub(crate) async fn close_expired_original(
        &self,
        message_id: &str,
    ) -> Result<TextReconciliation, TextSessionError> {
        let expires = self
            .shared
            .current()?
            .pending
            .get(message_id)
            .ok_or(TextSessionError::UnknownRequest)?
            .envelope
            .expires_at_ms;
        if crate::authbus_ingress::now_ms().map_err(unavailable)? < expires {
            return Err(unavailable("original signature is not expired"));
        }
        self.check_current_ingress().await?;
        self.reconcile_mode(message_id, ThreadQueueReconcileMode::CloseIfAbsent)
            .await
    }

    async fn reconcile_mode(
        &self,
        message_id: &str,
        mode: ThreadQueueReconcileMode,
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
            .authbus_text_lookup(pending.delivery_id.clone())
            .await
            .map_err(unavailable)?;
        if delivery
            .as_ref()
            .is_some_and(|status| status.delivery_id != pending.delivery_id)
        {
            self.fence()?;
            return Err(TextSessionError::Identity);
        }
        let response: ThreadQueueReconcileResponse = self
            .call(ClientRequest::ThreadQueueReconcile {
                request_id: self.id(),
                params: ThreadQueueReconcileParams {
                    thread_id: self.shared.config.thread_id.clone(),
                    input: pending.input.clone(),
                    client_user_message_id: pending.client_id.clone(),
                    expected_payload_sha256: pending.input_digest.clone(),
                    mode,
                },
            })
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
                        .call(ClientRequest::ThreadQueueDelete {
                            request_id: self.id(),
                            params: ThreadQueueDeleteParams {
                                thread_id: self.shared.config.thread_id.clone(),
                                queued_submission_id: queued_submission.id.clone(),
                            },
                        })
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
        {
            let mut state = self.shared.current()?;
            if state.snapshot_turns.len() >= 64 {
                state.snapshot_turns.retain(|_, terminal| !*terminal);
            }
            state
                .snapshot_turns
                .entry(turn_id.to_string())
                .or_insert(false);
            state
                .pending
                .get_mut(&pending.envelope.message_id)
                .ok_or(TextSessionError::UnknownRequest)?
                .recovered = true;
        }
        // Bounded pagination avoids loading an unbounded conversation into the
        // renderer. Hitting a history limit leaves the outcome unknown.
        let mut cursor = None;
        for _ in 0..32 {
            let page: ThreadTurnsListResponse = self
                .call(ClientRequest::ThreadTurnsList {
                    request_id: self.id(),
                    params: ThreadTurnsListParams {
                        thread_id: self.shared.config.thread_id.clone(),
                        cursor,
                        limit: Some(16),
                        sort_direction: Some(SortDirection::Desc),
                        items_view: Some(TurnItemsView::NotLoaded),
                    },
                })
                .await?;
            if serde_json::to_vec(&page).map_err(unavailable)?.len() > MAX_OBSERVATION_BYTES {
                return Err(TextSessionError::Capacity);
            }
            if let Some(turn) = page.data.into_iter().find(|turn| turn.id == turn_id) {
                if turn.items_view != TurnItemsView::NotLoaded
                    || !turn.items.is_empty()
                    || !self.original_input_in_turn(turn_id, pending).await?
                {
                    return Err(TextSessionError::Identity);
                }
                if turn.status != TurnStatus::InProgress {
                    self.shared
                        .current()?
                        .pending
                        .get_mut(&pending.envelope.message_id)
                        .ok_or(TextSessionError::UnknownRequest)?
                        .terminal = true;
                    self.shared
                        .current()?
                        .snapshot_turns
                        .insert(turn_id.to_string(), true);
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

    /// Reconcile's original Core binding already pins the exact turn/client ID
    /// and payload digest. Confirm its actual original UserMessage through item
    /// pagination without loading unrelated tool output into a terminal proof.
    async fn original_input_in_turn(
        &self,
        turn_id: &str,
        pending: &Pending,
    ) -> Result<bool, TextSessionError> {
        let mut cursor = None;
        for _ in 0..1024 {
            let page: ThreadItemsListResponse = self
                .call(ClientRequest::ThreadItemsList {
                    request_id: self.id(),
                    params: ThreadItemsListParams {
                        thread_id: self.shared.config.thread_id.clone(),
                        turn_id: Some(turn_id.into()),
                        cursor,
                        limit: Some(1),
                        sort_direction: Some(SortDirection::Asc),
                    },
                })
                .await?;
            if page.data.len() > 1
                || page.data.iter().any(|entry| entry.turn_id != turn_id)
                || page
                    .next_cursor
                    .as_ref()
                    .is_some_and(|value| value.is_empty() || value.len() > 2048)
            {
                return Err(TextSessionError::Identity);
            }
            for entry in page.data {
                if let ThreadItem::UserMessage {
                    client_id: Some(id),
                    content,
                    ..
                } = entry.item
                    && id == pending.client_id
                {
                    return if content == pending.input {
                        Ok(true)
                    } else {
                        Err(TextSessionError::Identity)
                    };
                }
            }
            cursor = page.next_cursor;
            if cursor.is_none() {
                return Ok(false);
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
        let observed = self.reconcile(message_id).await?;
        if matches!(&observed.queue, ThreadQueueReconcileOutcome::Missing) {
            // An explicit authorized interruption closes the same original
            // client binding before a delayed first delivery can arrive.
            self.check_current_ingress().await?;
            self.reconcile_mode(message_id, ThreadQueueReconcileMode::CloseIfAbsent)
                .await
        } else {
            Ok(observed)
        }
    }

    pub(super) async fn interrupt_turn(&self, turn_id: String) -> Result<(), TextSessionError> {
        self.check_current_ingress().await?;
        let _: TurnInterruptResponse = self
            .call(ClientRequest::TurnInterrupt {
                request_id: self.id(),
                params: TurnInterruptParams {
                    thread_id: self.shared.config.thread_id.clone(),
                    turn_id,
                },
            })
            .await?;
        Ok(())
    }

    pub(super) async fn check_current_ingress(&self) -> Result<(), TextSessionError> {
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
