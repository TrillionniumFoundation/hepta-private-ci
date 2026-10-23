//! Native execution orchestration; durable owners and the effect token own facts.

use super::*;

impl AppServerModelDriver {
    pub(super) async fn run_once(
        &self,
        control: &mut DurableInferenceControl,
        request_id: &str,
        prompt: String,
        context_query: Option<String>,
        intelligence: Option<&NativeIntelligenceRunBinding>,
        cancellation: &CancellationToken,
    ) -> Result<NativeRunOutput> {
        if prompt.is_empty() || prompt.len() > MAX_PROMPT_BYTES {
            return Err("prompt must contain 1..32768 bytes".into());
        }
        if cancellation.is_cancelled() {
            return Err("cancelled before admission".into());
        }
        let execution_clock =
            crate::native_deadline::NativeDeadline::new(unix_time_ms()?, self.config.timeout)?;
        let owner = AgentdClient::new(
            self.config.agentd_socket.clone(),
            self.config.agent_id.clone(),
            self.config.generation,
        )?;
        let health = owner.health().await?;
        if !health.ready || health.fenced {
            return Err("Agent is not ready".into());
        }
        if context_query.is_some() {
            let capabilities = owner.capabilities().await?;
            let supports_revalidation = capabilities.capabilities.iter().any(|capability| {
                capability.id == COGNITIVE_CONTEXT_REVALIDATION_CAPABILITY && capability.major == 1
            });
            if !supports_revalidation {
                return Err(
                    "owning Agent does not support final-use cognitive revalidation".into(),
                );
            }
        }
        let mut intelligence_revision = match intelligence {
            Some(binding) => Some(require_intelligence_handoff(&owner, binding).await?),
            None => None,
        };
        let ingress = owner.session_ingress().await?;
        let ingress_socket_path = ingress.socket_path;
        let socket_path = AbsolutePathBuf::from_absolute_path(ingress_socket_path.clone())?;
        let mut client = timeout(
            RPC_TIMEOUT,
            RemoteAppServerClient::connect_with_bounded_events(
                RemoteAppServerConnectArgs {
                    endpoint: RemoteAppServerEndpoint::UnixSocket { socket_path },
                    client_name: "hepta-infer-worker".to_string(),
                    client_version: env!("CARGO_PKG_VERSION").to_string(),
                    experimental_api: true,
                    mcp_server_openai_form_elicitation: false,
                    opt_out_notification_methods: Vec::new(),
                    channel_capacity: 32,
                },
                /*event_channel_capacity*/ 256,
            ),
        )
        .await??;
        let codex_home = client
            .codex_home()
            .ok_or("App Server initialize response omitted codex home")?
            .to_string();
        if Some(codex_home.as_str()) != health.home_root.to_str() {
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err("App Server home does not match the owning Agent".into());
        }
        let codex_home_digest = Digest32::of_bytes(codex_home.as_bytes());
        let connection_id = client.connection_id();
        let app_server_version = client
            .server_version()
            .ok_or("App Server initialize response omitted server version")?
            .to_string();
        let started: ThreadStartResponse = timeout(
            RPC_TIMEOUT,
            client.request_typed(ClientRequest::ThreadStart {
                request_id: RequestId::Integer(1),
                params: ThreadStartParams {
                    model: Some(self.config.model.clone()),
                    cwd: health.workspace.to_str().map(str::to_string),
                    approval_policy: Some(AskForApproval::Never),
                    sandbox: Some(SandboxMode::ReadOnly),
                    ephemeral: Some(true),
                    environments: Some(Vec::new()),
                    ..Default::default()
                },
            }),
        )
        .await??;
        let mut thread_guard = crate::native_thread_lifecycle::NativeThreadGuard::new(
            client.request_handle(),
            started.thread.id.clone(),
        );
        if started.model != self.config.model {
            thread_guard.cleanup().await;
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err("provider substituted the requested model".into());
        }
        // Recheck the actual generation after connecting and creating the
        // ephemeral thread. Only now acquire the retrieval result that will be
        // attached to turn/start. Agentd performs exact owner-cut, candidate
        // and retrieval-context revalidation before returning this value, so
        // preparatory provider I/O cannot leave an older context parked across
        // the final model-request attachment boundary.
        owner.session_ingress().await?;
        let context = match context_query {
            Some(query) => Some(owner.cognitive_context(query, /*limit*/ 4).await?),
            None => None,
        };
        let owner_context_digest = context
            .as_ref()
            .map(|snapshot| -> Result<_> { Ok(control::digest(&serde_json::to_vec(snapshot)?)) })
            .transpose()?;
        let additional_context = context
            .as_ref()
            .map(|snapshot| -> Result<_> {
                let value = serde_json::to_string(&snapshot)?;
                if value.len() > MAX_COGNITIVE_CONTEXT_BYTES {
                    return Err("verified context exceeds the model attachment byte limit".into());
                }
                Ok(HashMap::from([(
                    "hepta-cognitive-owner".to_string(),
                    AdditionalContextEntry {
                        value,
                        kind: AdditionalContextKind::Untrusted,
                    },
                )]))
            })
            .transpose()?;
        if cancellation.is_cancelled() {
            thread_guard.cleanup().await;
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err("cancelled before model dispatch".into());
        }
        if let Some(binding) = intelligence {
            let current_revision = require_intelligence_handoff(&owner, binding).await?;
            if Some(current_revision) != intelligence_revision {
                thread_guard.cleanup().await;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err("intelligence handoff revision changed before dispatch".into());
            }
        }
        let turn_params = TurnStartParams {
            thread_id: started.thread.id.clone(),
            client_user_message_id: Some(request_id.to_string()),
            input: vec![UserInput::Text {
                text: prompt,
                text_elements: Vec::new(),
            }],
            additional_context,
            environments: Some(Vec::new()),
            ..Default::default()
        };
        let turn_payload = serde_json::to_vec(&turn_params)?;
        let payload_digest = Digest32::of_bytes(&turn_payload);
        let user_input_digest = Digest32::of_bytes(&serde_json::to_vec(&turn_params.input)?);
        let adapted_at_ms = unix_time_ms()?;
        let source_admission_digest: Digest32 = control
            .native_record(request_id)
            .ok_or("missing durable native admission")?
            .request
            .payload_digest
            .parse()?;
        let adapter_intent = CodexOperationIntent {
            operation_id: StableId::new(format!(
                "native:{}",
                Digest32::of_bytes(request_id.as_bytes())
            ))?,
            thread_id: StableId::new(started.thread.id.clone())?,
            method_id: StableId::new(TURN_START_METHOD_ID)?,
            payload_digest,
            lease_payload_digest: payload_digest,
            deadline_ms: execution_clock.deadline_ms(),
            app_server_binding: Some(AppServerRequestBinding {
                source_admission_digest,
                agent_generation: Generation::new(self.config.generation)?,
                session_id: StableId::new(started.thread.session_id.clone())?,
                client_user_message_id: StableId::new(request_id.to_string())?,
                user_input_digest,
                protocol_id: StableId::new(APP_SERVER_V2_PROTOCOL_ID)?,
                app_server_version: app_server_version.clone(),
                codex_home_digest,
                connection_id,
            }),
        };
        let request_receipt = adapt_request(adapted_at_ms, adapter_intent.clone())?;
        let attempt = crate::runtime_codex_attempt::Attempt::new(
            crate::runtime_codex_attempt::AttemptIdentity {
                operation_id: adapter_intent.operation_id.clone(),
                request_digest: request_receipt.request_digest,
                payload_digest,
                deadline_ms: adapter_intent.deadline_ms,
            },
        )?
        .freeze_payload(payload_digest)?;
        let authority_binding = final_use_binding(
            &self.config.agent_id,
            &adapter_intent,
            &started.model,
            &started.model_provider,
        )?;
        let authorizer = self
            .turn_start_authorizer
            .as_ref()
            .ok_or("runtime.codex turn/start final-use authorizer is required")?;
        let claim_budget = execution_clock.remaining(unix_time_ms()?)?;
        let verified_use = timeout(claim_budget, authorizer.claim(authority_binding.clone()))
            .await
            .map_err(|_| "final-use authority request exceeded runtime.codex deadline")??;
        let attempt = attempt.authorize(Digest32::from_array(verified_use.witness_sha256()))?;
        let authority_epoch = verified_use.claimed_authority_epoch();
        let revocation_revision = verified_use.claimed_revocation_revision();
        let revocation_head_digest =
            Digest32::from_array(verified_use.claimed_revocation_head_sha256()).to_string();
        let authority_witness = Digest32::from_array(verified_use.witness_sha256()).to_string();

        let dispatch_digest = request_receipt.request_digest.to_string();
        let owner_dispatch = intelligence.map(|binding| NativeOwnerDispatchBinding {
            run_id: binding.run_id.clone(),
            pre_dispatch_revision: binding.expected_revision,
            dispatch_digest: request_receipt.request_digest.to_string(),
        });
        let dispatch = NativeDispatch {
            thread_id: started.thread.id.clone(),
            model_provider: started.model_provider.clone(),
            context_digest: control::digest(&serde_json::to_vec(&turn_params.additional_context)?),
            owner_context_digest: owner_context_digest.clone(),
            codex_payload_digest: Some(payload_digest.to_string()),
            codex_request_digest: Some(request_receipt.request_digest.to_string()),
            app_server_version: Some(app_server_version.clone()),
            protocol_id: Some(APP_SERVER_V2_PROTOCOL_ID.to_string()),
            codex_source_admission_digest: Some(source_admission_digest.to_string()),
            codex_home_digest: Some(codex_home_digest.to_string()),
            codex_connection_id: Some(connection_id),
            codex_session_id: Some(started.thread.session_id.clone()),
            codex_deadline_ms: Some(adapter_intent.deadline_ms),
            codex_authority_epoch: Some(authority_epoch),
            codex_revocation_revision: Some(revocation_revision),
            codex_revocation_head_sha256: Some(revocation_head_digest.clone()),
            codex_authority_witness_sha256: Some(authority_witness.clone()),
        };
        let (_, pre_effect_abort) = match owner_dispatch {
            Some(binding) => control
                .dispatch_native_with_pre_effect_abort_bound(request_id, dispatch, binding)?,
            None => control.dispatch_native_with_pre_effect_abort(request_id, dispatch)?,
        };
        let prepared_revision = control
            .native_record(request_id)
            .ok_or("native prepared dispatch missing")?
            .revision;
        let mut owner_abort_required = intelligence.is_some();
        let preparation: Result<(EnteredUseToken, Duration)> = async {
            verify_persisted_dispatch_binding(
                control,
                request_id,
                payload_digest,
                request_receipt.request_digest,
                source_admission_digest,
                codex_home_digest,
                connection_id,
                &started.thread.session_id,
                adapter_intent.deadline_ms,
                authority_epoch,
                revocation_revision,
                &revocation_head_digest,
                &authority_witness,
                &app_server_version,
            )?;
            if let Some(binding) = intelligence {
                let dispatched = owner
                    .run_mark_dispatched_exact(
                        binding.run_id.clone(),
                        binding.expected_revision,
                        dispatch_digest.clone(),
                    )
                    .await?;
                if dispatched.idempotent {
                    // A lost acknowledgement can be reconciled; it never grants a
                    // competing worker permission to stop the winning attempt.
                    owner_abort_required = false;
                    return Err("Agentd exact dispatch is already owned by another worker".into());
                }
                if dispatched.phase != AgentRunPhase::Dispatched
                    || dispatched.dispatch_digest.as_deref() != Some(dispatch_digest.as_str())
                    || dispatched.generation != self.config.generation
                    || dispatched.terminal_observed
                    || dispatched.context_digest.as_deref() != Some(binding.context_digest.as_str())
                    || dispatched.compilation_receipt_digest.as_deref()
                        != Some(binding.envelope_digest.as_str())
                {
                    return Err(
                        "Agentd did not newly commit this exact intelligence dispatch".into(),
                    );
                }
                intelligence_revision = Some(dispatched.revision);
            }
            let post_health = owner.health().await?;
            let current_ingress = owner.session_ingress().await?;
            validate_post_authority_fence(
                &post_health,
                &ingress_socket_path,
                &current_ingress.socket_path,
                cancellation.is_cancelled(),
                unix_time_ms()?,
                adapter_intent.deadline_ms,
            )?;
            #[cfg(test)]
            if context.is_some() {
                pause_before_final_revalidation_for_test().await;
            }
            if let Some(snapshot) = context.as_ref() {
                let revalidated = owner
                    .revalidate_cognitive_context(snapshot)
                    .await
                    .map_err(|error| format!("cognitive final-use revalidation failed: {error}"))?;
                if revalidated.snapshot_digest != snapshot.snapshot_digest
                    || revalidated.read_digest != snapshot.read_digest
                    || usize::from(revalidated.verified_item_count) != snapshot.items.len()
                {
                    return Err(
                        "cognitive final-use revalidation returned a mismatched receipt".into(),
                    );
                }
            }
            if cancellation.is_cancelled() {
                return Err("cancelled before model dispatch".into());
            }
            let send_budget = execution_clock.remaining(unix_time_ms()?)?.min(RPC_TIMEOUT);
            let entered_use = verified_use.enter(&authority_binding)?;
            if !entered_use.matches(&authority_binding) {
                return Err("kernel.authority final-use binding mismatch at entry".into());
            }
            Ok((entered_use, send_budget))
        }
        .await;
        let (entered_use, send_budget) = match preparation {
            Ok(value) => value,
            Err(error) => {
                let reason: String = error.to_string().chars().take(512).collect();
                let stopped = if owner_abort_required {
                    abort_pre_effect_consistently(
                        control,
                        &owner,
                        intelligence,
                        pre_effect_abort,
                        request_receipt.request_digest,
                        reason,
                    )
                    .await
                } else {
                    control
                        .abort_native_before_effect(pre_effect_abort, reason)
                        .map(|_| ())
                        .map_err(Into::into)
                };
                thread_guard.cleanup().await;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                stopped?;
                return Err(error);
            }
        };
        // From here on, a missing acknowledgement is reconcile-only. Recovery
        // cannot recreate the local pre-effect proof that is deliberately lost.
        let attempt = attempt
            .prepare_durable(request_receipt.request_digest)?
            .commit_owner(
                intelligence_revision.unwrap_or(prepared_revision),
                request_receipt.request_digest,
            )?;
        drop(pre_effect_abort);
        thread_guard.effect_entered();
        let attempt = attempt.enter_effect();
        let response = timeout(
            send_budget,
            send_authorized_turn_start(&mut client, entered_use, turn_params),
        )
        .await;
        let turn = match response {
            Ok(Ok(response)) => response.turn,
            Ok(Err(RemoteObservedTypedRequestError::Server { observed })) => {
                let receipt = adapt_observed_server_rejection(&adapter_intent, &observed)?;
                let reason: String = observed.error().message.chars().take(1024).collect();
                match receipt.status {
                    AdapterStatus::Overloaded | AdapterStatus::Rejected => {
                        let overloaded = receipt.status == AdapterStatus::Overloaded;
                        let status = if overloaded {
                            NativeDispatchRejectionStatus::Overloaded
                        } else {
                            NativeDispatchRejectionStatus::Rejected
                        };
                        let retry_safe_before_admission = overloaded;
                        let response_digest = receipt
                            .response_digest
                            .ok_or("server rejection receipt omitted response digest")?;
                        control.reject_native_before_start(
                            request_id,
                            NativeDispatchRejection {
                                status,
                                reason: reason.clone(),
                                response_digest: response_digest.to_string(),
                                retry_safe_before_admission,
                            },
                        )?;
                        thread_guard.cleanup().await;
                        let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                        return Err(format!("turn/start rejected by App Server: {reason}").into());
                    }
                    AdapterStatus::Indeterminate => {
                        if let Some(turn) =
                            reconcile_turn_start(&mut client, &started.thread.id).await?
                        {
                            turn
                        } else {
                            thread_guard.cleanup().await;
                            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                            return Ok(reconcile_intelligence_start_unknown(&owner, intelligence, intelligence_revision, indeterminate_start_output(
                                started,
                                format!(
                                    "turn/start returned an accepted-or-unknown JSON-RPC error ({reason}); reconciliation found no exact turn; do not replay"
                                ),
                            )).await);
                        }
                    }
                    _ => return Err("unexpected adapter server-error status".into()),
                }
            }
            Ok(Err(error)) => {
                if let Some(turn) = reconcile_turn_start(&mut client, &started.thread.id).await? {
                    turn
                } else {
                    thread_guard.cleanup().await;
                    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                    return Ok(reconcile_intelligence_start_unknown(&owner, intelligence, intelligence_revision, indeterminate_start_output(
                        started,
                        format!(
                            "turn/start transport outcome unknown ({error}); reconciliation found no exact turn; do not replay"
                        ),
                    )).await);
                }
            }
            Err(_) => {
                if let Some(turn) = reconcile_turn_start(&mut client, &started.thread.id).await? {
                    turn
                } else {
                    thread_guard.cleanup().await;
                    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                    return Ok(reconcile_intelligence_start_unknown(&owner, intelligence, intelligence_revision, indeterminate_start_output(
                        started,
                        "turn/start timed out; reconciliation found no exact turn; do not replay"
                            .to_string(),
                    )).await);
                }
            }
        };
        let binding = CodexTurnBinding {
            intent: adapter_intent,
            turn_id: StableId::new(turn.id.clone())?,
        };
        let attempt = attempt.started(StableId::new(turn.id.clone())?)?;
        let mut output = NativeRunOutput {
            thread_id: started.thread.id,
            turn_id: turn.id,
            model: started.model,
            model_provider: started.model_provider,
            status: NativeRunStatus::Indeterminate,
            boundary_status: NativeBoundaryStatus::Indeterminate,
            output: String::new(),
            observed_output_tokens: None,
            terminal_observed: false,
            owner_authority: NativeOwnerAuthority::Unverified,
            stop_reason: None,
            codex_terminal_correlation_digest: None,
        };
        if let Err(error) = control.native_started(request_id, output.turn_id.clone()) {
            if let (Some(binding), Some(revision)) = (intelligence, intelligence_revision) {
                let _ = owner
                    .run_cancel(
                        binding.run_id.clone(),
                        revision,
                        "native start journal update failed".to_string(),
                    )
                    .await;
            }
            interrupt(&mut client, &output).await;
            thread_guard.cleanup().await;
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err(error.into());
        }
        let deadline = Instant::now()
            + execution_clock
                .remaining(unix_time_ms()?)
                .unwrap_or(Duration::ZERO);
        let result = self
            .observe(
                &mut client,
                &mut output,
                deadline,
                cancellation,
                Some(&owner),
                &binding,
            )
            .await;
        if let Err(reason) = result {
            output.boundary_status = classify_observation_failure(&reason);
            output.stop_reason = Some(reason.clone());
            if let (Some(binding), Some(revision)) = (intelligence, intelligence_revision) {
                if let Ok(cancelled) = owner
                    .run_cancel(
                        binding.run_id.clone(),
                        revision,
                        reason.chars().take(512).collect(),
                    )
                    .await
                {
                    intelligence_revision = Some(cancelled.receipt.revision);
                }
            }
            // Persist cancellation intent, but still interrupt if that write
            // fails. A failed journal write fences later admission/settlement.
            // Commit observed authority loss before waiting for interruption:
            // a process crash must not erase it from a later settlement.
            let loss_recorded =
                if matches!(output.owner_authority, NativeOwnerAuthority::Lost { .. }) {
                    control
                        .settle_native(request_id, output.clone())
                        .map(|_| ())
                } else {
                    Ok(())
                };
            let cancel_recorded = control.cancel_native(request_id);
            interrupt(&mut client, &output).await;
            let grace = CancellationToken::new();
            let _ = self
                .observe(
                    &mut client,
                    &mut output,
                    Instant::now() + INTERRUPT_GRACE,
                    &grace,
                    /*owner*/ None,
                    &binding,
                )
                .await;
            loss_recorded?;
            cancel_recorded?;
            if !output.terminal_observed
                && let (Some(binding), Some(revision)) = (intelligence, intelligence_revision)
                && let Err(error) = owner
                    .run_observe_terminal(
                        binding.run_id.clone(),
                        revision,
                        AgentRunPhase::Indeterminate,
                        /*terminal_observed*/ false,
                    )
                    .await
            {
                let note = format!("Agentd indeterminate reconciliation required: {error}");
                output.stop_reason = Some(match output.stop_reason.take() {
                    Some(existing) => format!("{existing}; {note}"),
                    None => note,
                });
            }
        }
        if output.terminal_observed {
            let _ = verify_owner_health(&mut output, owner.health(), Instant::now() + RPC_TIMEOUT)
                .await;
            downgrade_for_owner_loss(&mut output);
            if let (Some(binding), Some(revision)) = (intelligence, intelligence_revision)
                && let Err(error) =
                    commit_intelligence_terminal(&owner, binding, revision, &output).await
            {
                let note = format!("Agentd terminal reconciliation required: {error}");
                output.stop_reason = Some(
                    match output.stop_reason.take() {
                        Some(existing) => format!("{existing}; {note}"),
                        None => note,
                    }
                    .chars()
                    .take(1024)
                    .collect(),
                );
            }
            // If this write fails, keep App Server history for reconciliation.
            // Never unsubscribe while the terminal fact exists only in RAM.
            let settled = control.settle_native(request_id, output)?;
            output = settled
                .observation
                .ok_or("durable terminal observation missing")?;
            let _terminal = attempt.terminal(
                output
                    .codex_terminal_correlation_digest
                    .as_ref()
                    .ok_or("terminal correlation missing")?
                    .parse()?,
            )?;
            thread_guard.terminal_persisted();
            thread_guard.cleanup().await;
        }
        thread_guard.cleanup().await;
        let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
        Ok(output)
    }
}
