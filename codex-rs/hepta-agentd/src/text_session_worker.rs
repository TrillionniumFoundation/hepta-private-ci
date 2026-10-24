//! Nonblocking native-UI boundary. The signer is an independently installed
//! owner service; no signing key, sequence allocator, or durable journal lives
//! in this worker. A host must authenticate the human before installing it.

use codex_hepta_types::Digest32;
use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::mpsc;
use std::thread;

use super::*;

#[path = "text_session_worker_recovery.rs"]
mod recovery;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct TextSignerEndpoint {
    pub socket_path: PathBuf,
    pub owner_uid: u32,
    pub owner_pid: u32,
}

#[derive(Clone, Debug)]
pub enum TextCommand {
    ResolveApproval {
        connection_id: u64,
        id: String,
        decision: TextApprovalDecision,
    },
    EarlierHistory,
    LatestHistory,
    Submit {
        request_id: String,
        text: String,
    },
    /// Release one retained original only after the shared ChatWorkspace has
    /// accepted its exact SignedTextRef and returned the original dispatch ticket.
    Dispatch {
        request_id: String,
    },
    Retire {
        message_id: String,
    },
    /// UI has consumed the original retirement receipt; free only transient
    /// client correlation after Root independently proved the durable outcome.
    Release {
        message_id: String,
    },
    Interrupt {
        message_id: String,
    },
    Reconcile {
        message_id: String,
    },
    Reconnect,
}

/// A projection reference to the host-retained signed bytes. This contains no
/// signature/key and cannot authorize submission without the actual envelope.
#[derive(Clone, Debug)]
pub struct TextPrepared {
    pub host_reference: String,
    pub issuer_id: String,
    pub key_epoch: u64,
    pub message_id: String,
    pub sequence: u64,
    pub expires_at_ms: u64,
    pub payload_sha256: [u8; 32],
    pub envelope_sha256: [u8; 32],
    pub text: String,
    pub delivery_id: String,
    pub spawn_generation: u64,
    pub lookup_only: bool,
}

#[derive(Clone, Debug)]
pub enum TextWorkerEvent {
    Approval(TextApprovalObservation),
    ApprovalWritten {
        connection_id: u64,
        id: String,
    },
    History {
        connection_id: u64,
        page: TextHistorySnapshot,
        viewing_earlier: bool,
    },
    HistoryActivity {
        connection_id: u64,
        page: TextHistorySnapshot,
    },
    /// Connection identity only; never a readiness or authority attestation.
    Connected {
        connection_id: u64,
    },
    /// Only emitted after the actual Root peer authenticated this registered
    /// UI and the original Agentd confirmed the same session/thread route.
    Authenticated {
        connection_id: u64,
        owner: TextOwnerReceipt,
    },
    Prepared {
        connection_id: u64,
        reference: TextPrepared,
    },
    /// Original Root reference recovered by lookup; never a new-send ticket.
    Recovered {
        connection_id: u64,
        reference: TextPrepared,
    },
    RecoveryComplete {
        connection_id: u64,
    },
    Admission {
        connection_id: u64,
        request_id: String,
        message_id: String,
        status: AuthBusTextStatus,
    },
    Notification(AgentdTextEvent),
    Reconciled {
        connection_id: u64,
        view: TextReconciliation,
    },
    Retired {
        connection_id: u64,
        request_id: String,
        message_id: String,
    },
    Unavailable {
        request_id: Option<String>,
        message: String,
    },
}

/// A single bounded background worker for a native composition. Draw/IME only
/// call try_send/try_recv; dropping it closes its client and does not cancel a
/// durable turn. The original owner remains responsible for shutdown/recovery.
pub struct AgentdTextWorker {
    commands: tokio::sync::mpsc::Sender<TextCommand>,
    events: mpsc::Receiver<TextWorkerEvent>,
}

impl AgentdTextWorker {
    pub fn start(
        config: AgentdTextSessionConfig,
        signer: TextSignerEndpoint,
        waker: Arc<dyn Fn() + Send + Sync>,
    ) -> Result<Self, TextSessionError> {
        Self::start_inner(Some(config), signer, waker)
    }

    /// The trusted Root receipt selects the existing daemon/thread. No renderer
    /// setting can substitute another route or construct an OwnerSession.
    pub fn start_authenticated(
        signer: TextSignerEndpoint,
        waker: Arc<dyn Fn() + Send + Sync>,
    ) -> Result<Self, TextSessionError> {
        Self::start_inner(None, signer, waker)
    }

    fn start_inner(
        config: Option<AgentdTextSessionConfig>,
        signer: TextSignerEndpoint,
        waker: Arc<dyn Fn() + Send + Sync>,
    ) -> Result<Self, TextSessionError> {
        if !signer.socket_path.is_absolute() || signer.owner_pid == 0 {
            return Err(TextSessionError::Identity);
        }
        let (commands, receiver) = tokio::sync::mpsc::channel(8);
        let (sender, events) = mpsc::sync_channel(128);
        thread::Builder::new()
            .name("hepta-text-session".into())
            .spawn(move || {
                let runtime = tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build();
                let result = match runtime {
                    Ok(runtime) => {
                        let result =
                            runtime.block_on(run(config, signer, receiver, &sender, &waker));
                        runtime.shutdown_timeout(Duration::from_secs(1));
                        result
                    }
                    Err(error) => Err(unavailable(error)),
                };
                if let Err(error) = result {
                    let _ = sender.try_send(TextWorkerEvent::Unavailable {
                        request_id: None,
                        message: error.to_string(),
                    });
                    waker();
                }
            })
            .map_err(unavailable)?;
        Ok(Self { commands, events })
    }

    pub fn try_send(&self, command: TextCommand) -> Result<(), TextSessionError> {
        self.commands
            .try_send(command)
            .map_err(|_| TextSessionError::Capacity)
    }

    pub fn try_recv(&self) -> Result<Option<TextWorkerEvent>, TextSessionError> {
        match self.events.try_recv() {
            Ok(event) => Ok(Some(event)),
            Err(mpsc::TryRecvError::Empty) => Ok(None),
            Err(mpsc::TryRecvError::Disconnected) => Err(unavailable("text worker stopped")),
        }
    }
}

async fn run(
    config: Option<AgentdTextSessionConfig>,
    signer: TextSignerEndpoint,
    mut commands: tokio::sync::mpsc::Receiver<TextCommand>,
    output: &mpsc::SyncSender<TextWorkerEvent>,
    waker: &Arc<dyn Fn() + Send + Sync>,
) -> Result<(), TextSessionError> {
    let emit = |event| -> Result<(), TextSessionError> {
        output
            .try_send(event)
            .map_err(|_| TextSessionError::Capacity)?;
        waker();
        Ok(())
    };
    let mut startup_until = std::time::Instant::now() + Duration::from_secs(10);
    let mut last_connect_error = None;
    let (mut owner, mut session) = loop {
        let attempt = async {
            let owner = super::signer::owner(&signer).await?;
            if config.as_ref().is_some_and(|config| config != &owner.route) {
                return Err(TextSessionError::Identity);
            }
            let session = AgentdTextSession::connect(owner.route.clone()).await?;
            Ok::<_, TextSessionError>((owner, session))
        }
        .await;
        match attempt {
            Ok(connected) => break connected,
            Err(issue) => {
                let message = issue.to_string();
                if last_connect_error.as_ref() != Some(&message) {
                    emit(TextWorkerEvent::Unavailable {
                        request_id: None,
                        message: message.clone(),
                    })?;
                    last_connect_error = Some(message);
                }
            }
        }
        // No intent has been accepted before authentication. Stay available to
        // retry the SAME configured Root endpoint after startup/transport loss.
        loop {
            let command = tokio::select! {
                _ = tokio::time::sleep(Duration::from_millis(250)), if std::time::Instant::now() < startup_until => break,
                command = commands.recv() => command,
            };
            match command {
                Some(TextCommand::Reconnect) => {
                    startup_until = std::time::Instant::now() + Duration::from_secs(10);
                    last_connect_error = None;
                    break;
                }
                Some(TextCommand::Submit { request_id, .. })
                | Some(TextCommand::Dispatch { request_id }) => {
                    emit(TextWorkerEvent::Unavailable {
                        request_id: Some(request_id),
                        message: "Original Root chat owner is not authenticated".into(),
                    })?
                }
                Some(_) => emit(TextWorkerEvent::Unavailable {
                    request_id: None,
                    message: "Original chat owner is not connected".into(),
                })?,
                None => return Ok(()),
            }
        }
    };
    let config = owner.route.clone();
    emit(TextWorkerEvent::Connected {
        connection_id: session.requests.connection_id(),
    })?;
    emit(TextWorkerEvent::Authenticated {
        connection_id: session.requests.connection_id(),
        owner: owner.clone(),
    })?;
    // A retained request maps to one exact human intent. An ambiguous signing
    // response is subsequently looked up, never reissued as a fresh signature.
    let mut intents = BTreeMap::<String, String>::new();
    let mut messages = BTreeMap::<String, String>::new();
    let mut retired = std::collections::BTreeSet::<String>::new();
    let prepared = Arc::new(Mutex::new(
        BTreeMap::<String, (AuthBusTextIngress, bool)>::new(),
    ));
    let mut inflight: tokio::task::JoinSet<
        Result<TextWorkerEvent, (Option<String>, TextSessionError)>,
    > = tokio::task::JoinSet::new();
    let mut stream_open = true;
    let mut earlier_cursor = None;
    let mut ready = match recovery::restore(
        &signer,
        &owner,
        &session,
        &mut intents,
        &mut messages,
        &prepared,
        &emit,
    )
    .await
    {
        Ok(cursor) => {
            earlier_cursor = cursor;
            true
        }
        Err(issue) => {
            emit(TextWorkerEvent::Unavailable {
                request_id: None,
                message: issue.to_string(),
            })?;
            stream_open = false;
            false
        }
    };
    let mut last_polled = String::new();
    let mut poll = tokio::time::interval(Duration::from_millis(250));
    poll.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    let mut history_poll = tokio::time::interval(Duration::from_millis(1000));
    history_poll.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    loop {
        if ready && crate::authbus_ingress::now_ms().map_err(unavailable)? >= owner.expires_at_ms {
            ready = false;
            stream_open = false;
            session.requests.fence()?;
            emit(TextWorkerEvent::Unavailable {
                request_id: None,
                message:
                    "Original Root chat session expired; original re-authentication is required"
                        .into(),
            })?;
        }
        let until_expiry = owner
            .expires_at_ms
            .saturating_sub(crate::authbus_ingress::now_ms().map_err(unavailable)?)
            .min(300_000);
        tokio::select! {
            _ = tokio::time::sleep(Duration::from_millis(until_expiry)), if ready => continue,
            event = session.events.next_observation(), if stream_open => match event {
                Ok(Some(AgentdTextObservation::Notification(event))) => emit(TextWorkerEvent::Notification(event))?,
                Ok(Some(AgentdTextObservation::Approval(event))) => emit(TextWorkerEvent::Approval(event))?,
                Ok(None) => { stream_open = false; ready = false; },
                Err(error) => {
                    stream_open = false;
                    ready = false;
                    emit(TextWorkerEvent::Unavailable { request_id: None, message: error.to_string() })?;
                }
            },
            result = inflight.join_next(), if !inflight.is_empty() => {
                match result.ok_or_else(|| unavailable("request task missing"))?.map_err(unavailable)? {
                    Ok(event) => {
                        if let TextWorkerEvent::Prepared { reference, .. } = &event {
                            messages.insert(reference.message_id.clone(), reference.host_reference.clone());
                        }
                        if let TextWorkerEvent::Retired { request_id, message_id, .. } = &event {
                            let _ = request_id;
                            retired.insert(message_id.clone());
                        }
                        if ready { emit(event)?; }
                    }
                    Err((request_id, error)) => emit(TextWorkerEvent::Unavailable { request_id, message: error.to_string() })?,
                }
            },
            _ = history_poll.tick(), if ready && inflight.is_empty() => {
                let activity = match session.requests.has_snapshot_activity() {
                    Ok(value) => value,
                    Err(issue) => {
                        ready = false; stream_open = false;
                        emit(TextWorkerEvent::Unavailable { request_id: None, message: issue.to_string() })?;
                        continue;
                    }
                };
                if activity {
                    match session.requests.refresh_snapshot_activity().await {
                        Ok(page) if !page.turns.is_empty() || page.notice.is_some() => emit(TextWorkerEvent::HistoryActivity { connection_id: session.requests.connection_id(), page })?,
                        Ok(_) => {},
                        Err(issue) => emit(TextWorkerEvent::Unavailable { request_id: Some("history".into()), message: issue.to_string() })?,
                    }
                }
            },
            _ = poll.tick(), if inflight.is_empty() && ready => {
                let next = recovery::next_work(&session, &prepared, &messages, &last_polled)?;
                if let Some((message_id, retire)) = next {
                    last_polled = message_id.clone();
                    let requests = session.requests.clone();
                    if retire && !retired.contains(&message_id) {
                        let request_id = messages.get(&message_id).cloned().ok_or(TextSessionError::UnknownRequest)?;
                        let text = intents.get(&request_id).cloned().ok_or(TextSessionError::UnknownRequest)?;
                        let signer = signer.clone(); let config = config.clone();
                        inflight.spawn(async move {
                            super::signer::retire_input(&signer, &config, &request_id, &text).await
                                .map(|()| TextWorkerEvent::Retired { connection_id: requests.connection_id(), request_id: request_id.clone(), message_id })
                                .map_err(|error| (Some(request_id), error))
                        });
                    } else if !retired.contains(&message_id) {
                        inflight.spawn(async move {
                            requests.reconcile(&message_id).await
                                .map(|view| TextWorkerEvent::Reconciled { connection_id: requests.connection_id(), view })
                                .map_err(|error| (Some(message_id), error))
                        });
                    }
                }
            },
            command = commands.recv() => {
                let Some(command) = command else { break; };
                if let TextCommand::Release { message_id } = &command {
                    if retired.contains(message_id) {
                        // Root's independently verified original terminal/close
                        // receipt, not a local timer, permits transient release.
                        session.requests.shared.current()?.pending.remove(message_id);
                        retired.remove(message_id);
                        if let Some(request_id) = messages.remove(message_id) {
                            intents.remove(&request_id);
                            prepared.lock().map_err(|_| TextSessionError::Fenced)?.remove(&request_id);
                        }
                    }
                    continue;
                }
                if inflight.len() >= 4 { emit(TextWorkerEvent::Unavailable { request_id: None, message: "text request capacity reached".into() })?; continue; }
                if !ready && !matches!(&command, TextCommand::Reconnect) {
                    emit(TextWorkerEvent::Unavailable { request_id: None, message: "Original references must finish recovery before new work".into() })?;
                    continue;
                }
                let interrupt_requested = matches!(&command, TextCommand::Interrupt { .. });
                match command {
                    TextCommand::ResolveApproval { connection_id, id, decision } => {
                        if !owner.can_resolve_approvals || connection_id != session.requests.connection_id() {
                            emit(TextWorkerEvent::Unavailable { request_id: Some(format!("approval:{id}")), message: "Original Root session does not permit this approval callback".into() })?;
                            continue;
                        }
                        let requests = session.requests.clone();
                        let signer = signer.clone();
                        let expected_owner = owner.clone();
                        inflight.spawn(async move {
                            let result = async {
                                let current = super::signer::owner(&signer).await?;
                                if !current.same_authorization(&expected_owner) || !current.can_resolve_approvals { return Err(TextSessionError::Identity); }
                                requests.resolve_approval(connection_id, &id, decision).await?;
                                Ok(TextWorkerEvent::ApprovalWritten { connection_id, id: id.clone() })
                            }.await;
                            result.map_err(|error| (Some(format!("approval:{id}")), error))
                        });
                    }
                    TextCommand::EarlierHistory | TextCommand::LatestHistory => {
                        if !inflight.is_empty() {
                            emit(TextWorkerEvent::Unavailable { request_id: Some("history".into()), message: "Wait for original input reconciliation before changing history pages".into() })?;
                            continue;
                        }
                        let viewing_earlier = matches!(&command, TextCommand::EarlierHistory);
                        let cursor = if viewing_earlier {
                            let Some(cursor) = earlier_cursor.clone() else { continue; };
                            Some(cursor)
                        } else { None };
                        match session.requests.history_page(cursor).await {
                            Ok(page) => {
                                earlier_cursor = page.earlier_cursor.clone();
                                emit(TextWorkerEvent::History { connection_id: session.requests.connection_id(), page, viewing_earlier })?;
                            }
                            Err(issue) => emit(TextWorkerEvent::Unavailable { request_id: Some("history".into()), message: issue.to_string() })?,
                        }
                    }
                    TextCommand::Submit { request_id, text } => {
                        if request_id.is_empty() || request_id.len() > 192
                            || !request_id.bytes().all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
                            || text.trim().is_empty() || text.len() > 8192 {
                            emit(TextWorkerEvent::Unavailable { request_id: Some(request_id), message: "invalid signed text intent".into() })?;
                            continue;
                        }
                        let lookup = if let Some(prior) = intents.get(&request_id) {
                            if prior != &text { emit(TextWorkerEvent::Unavailable { request_id: Some(request_id), message: "text intent identity conflict".into() })?; continue; }
                            true
                        } else {
                            if intents.len() >= MAX_RETAINED { return Err(TextSessionError::Capacity); }
                            intents.insert(request_id.clone(), text.clone());
                            false
                        };
                        let requests = session.requests.clone();
                        let signer = signer.clone();
                        let config = config.clone();
                        let prepared = prepared.clone();
                        inflight.spawn(async move {
                            let result = async {
                                let envelope = super::signer::signed_input(&signer, &config, &request_id, &text, lookup).await?;
                                let lookup_only = lookup || envelope.body.spawn_generation != config.spawn_generation;
                                let claims = crate::authbus_text_claims(&config.agent_id, &envelope).map_err(unavailable)?;
                                let envelope_bytes = serde_json::to_vec(&envelope).map_err(unavailable)?;
                                let reference = TextPrepared {
                                    host_reference: request_id.clone(), issuer_id: envelope.issuer_id.clone(), key_epoch: envelope.key_epoch,
                                    message_id: envelope.message_id.clone(), sequence: envelope.sequence, expires_at_ms: envelope.expires_at_ms,
                                    payload_sha256: *claims.payload_digest.as_array(),
                                    envelope_sha256: *Digest32::of_bytes(&envelope_bytes).as_array(), text: envelope.body.text.clone(),
                                    spawn_generation: envelope.body.spawn_generation, lookup_only,
                                    delivery_id: super::prepare(&config, envelope.clone())?.delivery_id,
                                };
                                let mut retained = prepared.lock().map_err(|_| TextSessionError::Fenced)?;
                                if retained.len() >= MAX_RETAINED && !retained.contains_key(&request_id) { return Err(TextSessionError::Capacity); }
                                if let Some((old, _)) = retained.get(&request_id)
                                    && old != &envelope { return Err(TextSessionError::Identity); }
                                retained.insert(request_id.clone(), (envelope, lookup_only));
                                Ok(TextWorkerEvent::Prepared { connection_id: requests.connection_id(), reference })
                            }.await;
                            result.map_err(|error| (Some(request_id), error))
                        });
                    }
                    TextCommand::Dispatch { request_id } => {
                        let retained = prepared.lock().map_err(|_| TextSessionError::Fenced)?.remove(&request_id);
                        let Some((envelope, lookup_only)) = retained else {
                            emit(TextWorkerEvent::Unavailable { request_id: Some(request_id), message: "Original signed input is not prepared".into() })?;
                            continue;
                        };
                        let requests = session.requests.clone();
                        messages.insert(envelope.message_id.clone(), request_id.clone());
                        inflight.spawn(async move {
                            let message_id = envelope.message_id.clone();
                            let result = if lookup_only { requests.lookup_signed(envelope).await } else { requests.submit_signed(envelope).await };
                            result.map(|status| TextWorkerEvent::Admission { connection_id: requests.connection_id(), request_id: request_id.clone(), message_id, status })
                                .map_err(|error| (Some(request_id), error))
                        });
                    }
                    TextCommand::Retire { message_id } => {
                        let Some(request_id) = messages.get(&message_id).cloned() else { continue; };
                        let text = intents.get(&request_id).cloned().ok_or(TextSessionError::UnknownRequest)?;
                        let signer = signer.clone();
                        let config = config.clone();
                        let requests = session.requests.clone();
                        inflight.spawn(async move {
                            let result = async {
                                super::signer::retire_input(&signer, &config, &request_id, &text).await?;
                                Ok(TextWorkerEvent::Retired { connection_id: requests.connection_id(), request_id: request_id.clone(), message_id })
                            }.await;
                            result.map_err(|error| (Some(request_id), error))
                        });
                    }
                    TextCommand::Interrupt { message_id } | TextCommand::Reconcile { message_id } => {
                        let interrupt = interrupt_requested;
                        if interrupt && !owner.can_interrupt {
                            emit(TextWorkerEvent::Unavailable { request_id: Some(message_id), message: "Root session does not permit interruption".into() })?;
                            continue;
                        }
                        let requests = session.requests.clone();
                        let signer = signer.clone();
                        let expected_owner = owner.clone();
                        inflight.spawn(async move {
                            let result = async {
                                if interrupt {
                                    let current = super::signer::owner(&signer).await?;
                                    if !current.same_authorization(&expected_owner) || !current.can_interrupt {
                                        return Err(TextSessionError::Identity);
                                    }
                                    requests.interrupt(&message_id).await
                                } else { requests.reconcile(&message_id).await }
                            }.await;
                            result.map(|view| TextWorkerEvent::Reconciled { connection_id: requests.connection_id(), view })
                                .map_err(|error| (Some(message_id), error))
                        });
                    }
                    TextCommand::Reconnect => {
                        if !inflight.is_empty() { emit(TextWorkerEvent::Unavailable { request_id: Some("reconnect:busy".into()), message: "wait for retained requests before reconnect".into() })?; continue; }
                        let attempt = async {
                            let refreshed = super::signer::owner(&signer).await?;
                            if !refreshed.same_authorization(&owner) { return Err(TextSessionError::Identity); }
                            let next = session.reattach(config.clone()).await?;
                            Ok::<_, TextSessionError>((refreshed, next))
                        }.await;
                        let (refreshed, next) = match attempt {
                            Ok(value) => value,
                            Err(issue) => {
                                let _ = session.requests.fence();
                                stream_open = false;
                                ready = false;
                                emit(TextWorkerEvent::Unavailable { request_id: None, message: issue.to_string() })?;
                                continue;
                            }
                        };
                        let _ = session.events.shutdown().await;
                        session = next;
                        owner = refreshed.clone();
                        stream_open = true;
                        emit(TextWorkerEvent::Connected { connection_id: session.requests.connection_id() })?;
                        emit(TextWorkerEvent::Authenticated { connection_id: session.requests.connection_id(), owner: refreshed })?;
                        ready = match recovery::restore(&signer, &owner, &session, &mut intents, &mut messages, &prepared, &emit).await {
                            Ok(cursor) => { earlier_cursor = cursor; true },
                            Err(issue) => {
                                stream_open = false;
                                emit(TextWorkerEvent::Unavailable { request_id: None, message: issue.to_string() })?;
                                false
                            }
                        };
                        if !ready { continue; }
                        let ids = session.requests.shared.current()?.pending.keys().cloned().collect::<Vec<_>>();
                        for message_id in ids {
                            match session.requests.reconcile(&message_id).await {
                                Ok(view) => emit(TextWorkerEvent::Reconciled { connection_id: session.requests.connection_id(), view })?,
                                Err(issue) => emit(TextWorkerEvent::Unavailable { request_id: Some(message_id.clone()), message: issue.to_string() })?,
                            }
                            if retired.contains(&message_id) && let Some(request_id) = messages.get(&message_id) {
                                emit(TextWorkerEvent::Retired { connection_id: session.requests.connection_id(), request_id: request_id.clone(), message_id })?;
                            }
                        }
                    }
                    TextCommand::Release { .. } => unreachable!("release is handled before the work-capacity gate"),
                }
            }
        }
    }
    session.requests.fence()?;
    inflight.abort_all();
    while inflight.join_next().await.is_some() {}
    session.events.shutdown().await
}

#[cfg(test)]
#[path = "text_session_worker_tests.rs"]
mod tests;
