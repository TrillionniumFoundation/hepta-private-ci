use super::*;

impl AgentdTextRequests {
    pub(super) fn id(&self) -> RequestId {
        RequestId::Integer(self.shared.request_id.fetch_add(1, Ordering::Relaxed))
    }

    pub(super) async fn call<T: serde::de::DeserializeOwned>(&self, request: ClientRequest) -> Result<T, TextSessionError> {
        self.shared.current()?;
        let response = tokio::time::timeout(REQUEST_TIMEOUT, self.handle.request_typed(request))
            .await.map_err(unavailable)?.map_err(unavailable)?;
        self.shared.current()?;
        Ok(response)
    }

    /// Sole new-input path. Signatures and sequence numbers come from the
    /// installed independent host. The exact input is retained before I/O.
    /// Repeated calls only look up the original delivery, even after lost ACK.
    pub async fn submit_signed(&self, envelope: AuthBusTextIngress) -> Result<AuthBusTextStatus, TextSessionError> {
        let pending = prepare(&self.shared.config, envelope)?;
        let existing = {
            let mut state = self.shared.current()?;
            if let Some(old) = state.pending.get(&pending.envelope.message_id) {
                if old.envelope != pending.envelope { return Err(TextSessionError::Identity); }
                true
            } else {
                if state.pending.len() >= MAX_RETAINED { return Err(TextSessionError::Capacity); }
                state.pending.insert(pending.envelope.message_id.clone(), pending.clone());
                false
            }
        };
        let status = if existing {
            self.shared.control.authbus_text_status(pending.delivery_id.clone()).await
        } else {
            self.shared.control.submit_authbus_text(pending.envelope).await
        }.map_err(unavailable)?;
        self.shared.current()?;
        if status.delivery_id != pending.delivery_id { self.fence()?; return Err(TextSessionError::Identity); }
        Ok(status)
    }

    pub fn connection_id(&self) -> u64 { self.shared.connection_id }

    pub fn fence(&self) -> Result<(), TextSessionError> {
        self.shared.state()?.fenced = true;
        Ok(())
    }

    /// Lookup only through the same original queue identity and payload digest.
    /// Missing never authorizes allowIfAbsent or a replacement signed message.
    pub async fn reconcile(&self, message_id: &str) -> Result<TextReconciliation, TextSessionError> {
        let pending = self.shared.current()?.pending.get(message_id).cloned().ok_or(TextSessionError::UnknownRequest)?;
        let delivery = self.shared.control.authbus_text_status(pending.delivery_id.clone()).await.map_err(unavailable)?;
        if delivery.delivery_id != pending.delivery_id { self.fence()?; return Err(TextSessionError::Identity); }
        let response: ThreadQueueReconcileResponse = self.call(ClientRequest::ThreadQueueReconcile {
            request_id: self.id(), params: ThreadQueueReconcileParams {
                thread_id: self.shared.config.thread_id.clone(), input: pending.input.clone(),
                client_user_message_id: pending.client_id.clone(), expected_payload_sha256: pending.input_digest.clone(),
                mode: ThreadQueueReconcileMode::ReconcileOnly,
            },
        }).await?;
        if response.client_user_message_id != pending.client_id || response.payload_sha256 != pending.input_digest {
            self.fence()?; return Err(TextSessionError::Identity);
        }
        let mut turn = None;
        match &response.outcome {
            ThreadQueueReconcileOutcome::Queued { queued_submission, created } => {
                if *created || queued_submission.client_user_message_id != pending.client_id || queued_submission.input != pending.input {
                    self.fence()?; return Err(TextSessionError::Identity);
                }
                if pending.cancellation_requested {
                    self.check_current_ingress().await?;
                    let _: ThreadQueueDeleteResponse = self.call(ClientRequest::ThreadQueueDelete {
                        request_id: self.id(), params: ThreadQueueDeleteParams {
                            thread_id: self.shared.config.thread_id.clone(), queued_submission_id: queued_submission.id.clone(),
                        },
                    }).await?;
                    // A racing dequeue can return false. Only a later observed
                    // Cancelled or terminal turn is a cancellation outcome.
                }
            }
            ThreadQueueReconcileOutcome::Persisted { turn_id } => {
                if turn_id.is_empty() { self.fence()?; return Err(TextSessionError::Identity); }
                self.shared.current()?.pending.get_mut(message_id).ok_or(TextSessionError::UnknownRequest)?.turn_id = Some(turn_id.clone());
                turn = self.read_turn(turn_id, &pending).await?;
                if pending.cancellation_requested && turn.as_ref().is_none_or(|turn| turn.status == TurnStatus::InProgress) {
                    self.interrupt_turn(turn_id.clone()).await?;
                }
            }
            ThreadQueueReconcileOutcome::Cancelled => {
                self.shared.current()?.pending.get_mut(message_id).ok_or(TextSessionError::UnknownRequest)?.terminal = true;
            }
            ThreadQueueReconcileOutcome::Missing => {}
        }
        Ok(TextReconciliation { message_id: message_id.to_string(), delivery, queue: response.outcome, turn })
    }

    async fn read_turn(&self, turn_id: &str, pending: &Pending) -> Result<Option<Turn>, TextSessionError> {
        // Bounded pagination avoids loading an unbounded conversation into the
        // renderer. Hitting a history limit leaves the outcome unknown.
        let mut cursor = None;
        for _ in 0..32 {
            let page: ThreadTurnsListResponse = self.call(ClientRequest::ThreadTurnsList {
                request_id: self.id(), params: ThreadTurnsListParams {
                    thread_id: self.shared.config.thread_id.clone(), cursor, limit: Some(16),
                    sort_direction: Some(SortDirection::Desc), items_view: Some(TurnItemsView::Full),
                },
            }).await?;
            if serde_json::to_vec(&page).map_err(unavailable)?.len() > MAX_OBSERVATION_BYTES { return Err(TextSessionError::Capacity); }
            if let Some(turn) = page.data.into_iter().find(|turn| turn.id == turn_id) {
                if !turn.items.iter().any(|item| matches!(item, ThreadItem::UserMessage {client_id: Some(id), content, ..} if id == &pending.client_id && content == &pending.input)) {
                    return Err(TextSessionError::Identity);
                }
                if turn.status != TurnStatus::InProgress {
                    self.shared.current()?.pending.get_mut(&pending.envelope.message_id).ok_or(TextSessionError::UnknownRequest)?.terminal = true;
                }
                return Ok(Some(turn));
            }
            cursor = page.next_cursor;
            if cursor.is_none() { return Ok(None); }
        }
        Err(TextSessionError::Capacity)
    }

    /// Records cancellation before awaiting anything. It is not a completion
    /// receipt. While AuthBus is still queued, periodic reconciliation keeps
    /// the intent until the original Core queue/turn can be cancelled.
    pub async fn interrupt(&self, message_id: &str) -> Result<TextReconciliation, TextSessionError> {
        self.shared.current()?.pending.get_mut(message_id).ok_or(TextSessionError::UnknownRequest)?.cancellation_requested = true;
        self.reconcile(message_id).await
    }

    pub(super) async fn interrupt_turn(&self, turn_id: String) -> Result<(), TextSessionError> {
        self.check_current_ingress().await?;
        let _: TurnInterruptResponse = self.call(ClientRequest::TurnInterrupt {
            request_id: self.id(), params: TurnInterruptParams { thread_id: self.shared.config.thread_id.clone(), turn_id },
        }).await?;
        Ok(())
    }

    async fn check_current_ingress(&self) -> Result<(), TextSessionError> {
        self.shared.current()?;
        let ingress = self.shared.control.session_ingress().await.map_err(unavailable)?;
        if ingress.socket_path != self.shared.ingress_socket { self.fence()?; return Err(TextSessionError::Identity); }
        Ok(())
    }

    /// Retires only a resolved presentation correlation slot. Core and AuthBus
    /// continue to own dedupe/history; no durable message or receipt is removed.
    pub fn retire(&self, message_id: &str) -> Result<(), TextSessionError> {
        let mut state = self.shared.current()?;
        if !state.pending.get(message_id).is_some_and(|pending| pending.terminal) { return Err(TextSessionError::UnknownRequest); }
        state.pending.remove(message_id);
        Ok(())
    }
}
