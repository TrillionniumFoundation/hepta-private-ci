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
        deadline: control::NativeDeadlinePolicy,
        cancellation: &CancellationToken,
    ) -> Result<NativeRunOutput> {
        if prompt.is_empty() || prompt.len() > MAX_PROMPT_BYTES {
            return Err("prompt must contain 1..32768 bytes".into());
        }
        if cancellation.is_cancelled() {
            return Err("cancelled before admission".into());
        }
        let wall_at_anchor_ms = unix_time_ms()?;
        let execution_clock = match (intelligence, deadline) {
            (Some(binding), control::NativeDeadlinePolicy::Profile) => {
                crate::native_deadline::NativeDeadline::from_absolute(
                    wall_at_anchor_ms,
                    binding.absolute_deadline_ms,
                    self.config.timeout,
                )?
            }
            (None, control::NativeDeadlinePolicy::Absolute(deadline_ms)) => {
                crate::native_deadline::NativeDeadline::from_absolute(
                    wall_at_anchor_ms,
                    deadline_ms,
                    self.config.timeout,
                )?
            }
            (Some(_), control::NativeDeadlinePolicy::Absolute(_)) => {
                return Err("intelligence deadline is owned by its admitted binding".into());
            }
            (None, control::NativeDeadlinePolicy::Profile) => {
                crate::native_deadline::NativeDeadline::from_budget(
                    wall_at_anchor_ms,
                    self.config.timeout,
                )?
            }
        };
        let owner = AgentdClient::new(
            self.config.agentd_socket.clone(),
            self.config.agent_id.clone(),
            self.config.generation,
        )?;
        let health = await_before_effect(
            &execution_clock,
            RPC_TIMEOUT,
            "Agentd health",
            owner.health(),
        )
        .await?;
        if !health.ready || health.fenced {
            return Err("Agent is not ready".into());
        }
        if context_query.is_some() {
            let capabilities = await_before_effect(
                &execution_clock,
                RPC_TIMEOUT,
                "Agentd capabilities",
                owner.capabilities(),
            )
            .await?;
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
            Some(binding) => {
                Some(require_intelligence_handoff(&execution_clock, &owner, binding).await?)
            }
            None => None,
        };
        let ingress = await_before_effect(
            &execution_clock,
            RPC_TIMEOUT,
            "Agentd session ingress",
            owner.session_ingress(),
        )
        .await?;
        let ingress_socket_path = ingress.socket_path;
        let socket_path = AbsolutePathBuf::from_absolute_path(ingress_socket_path.clone())?;
        let mut client = await_before_effect(
            &execution_clock,
            RPC_TIMEOUT,
            "App Server connect",
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
        .await?;
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
        let started: ThreadStartResponse = await_before_effect(
            &execution_clock,
            RPC_TIMEOUT,
            "App Server thread/start",
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
        .await?;
        let cleanup_store = await_before_effect(
            &execution_clock,
            RPC_TIMEOUT,
            "durable cleanup store open",
            self.cleanup_owner.get(),
        )
        .await?;
        let recovery_budget = execution_clock
            .remaining(unix_time_ms()?)?
            .min(Duration::from_millis(500));
        crate::native_thread_lifecycle::NativeThreadGuard::recover_pending(
            &cleanup_store,
            client.request_handle(),
            Instant::now() + recovery_budget,
        )
        .await?;
        let cleanup_operation_id = format!("native:{}", Digest32::of_bytes(request_id.as_bytes()));
        let mut thread_guard = await_before_effect(
            &execution_clock,
            RPC_TIMEOUT,
            "durable cleanup obligation enqueue",
            crate::native_thread_lifecycle::NativeThreadGuard::create(
                cleanup_store,
                client.request_handle(),
                cleanup_operation_id,
                started.thread.id.clone(),
                started.thread.session_id.clone(),
            ),
        )
        .await?;
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
        await_before_effect(
            &execution_clock,
            RPC_TIMEOUT,
            "Agentd ingress recheck",
            owner.session_ingress(),
        )
        .await?;
        let context = match context_query {
            Some(query) => Some(
                await_before_effect(
                    &execution_clock,
                    RPC_TIMEOUT,
                    "Agentd cognitive context",
                    owner.cognitive_context(query, /*limit*/ 4),
                )
                .await?,
            ),
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
            let current_revision =
                require_intelligence_handoff(&execution_clock, &owner, binding).await?;
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

        // runtime.codex-bound-dispatch-v1: this is the only cross-owner
        // dispatch identity. The live native token supplies the commitment and
        // Agentd stores that commitment with the same Dispatched transition.
        let dispatch_binding_digest = request_receipt.request_digest.to_string();
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
        let terminal_owner = if let Some(binding) = intelligence {
            Some(NativeTerminalOwnerBinding {
                run_id: binding.run_id.clone(),
                owner_dispatch_revision: binding
                    .expected_revision
                    .checked_add(1)
                    .ok_or("Agentd dispatch revision overflow")?,
                context_digest: binding.context_digest.clone(),
                envelope_digest: binding.envelope_digest.clone(),
            })
        } else {
            None
        };
        let (_, pre_effect_abort) = match terminal_owner {
            Some(owner_binding) => control.dispatch_native_with_pre_effect_abort_bound(
                request_id,
                dispatch,
                owner_binding,
            )?,
            None => control.dispatch_native_with_pre_effect_abort(request_id, dispatch)?,
        };
        let prepared_revision = control
            .native_record(request_id)
            .ok_or("native prepared dispatch missing")?
            .revision;
        let pre_effect_abort_commitment = intelligence
            .map(|binding| {
                pre_effect_abort.commitment_digest(&binding.run_id, &dispatch_binding_digest)
            })
            .transpose()?;
        // Once the bound dispatch RPC is attempted, expected_revision + 1 is
        // the only legal Agentd dispatch revision. A lost acknowledgement is
        // therefore abortable without guessing; if Agentd did not commit, its
        // CAS rejects the abort and the native AbortPending record stays held
        // for recovery rather than releasing capacity unsafely.
        let mut owner_abort_revision = None;
        let preparation: Result<(
            crate::runtime_codex_attempt::Attempt<crate::runtime_codex_attempt::OwnerCommitted>,
            EnteredUseToken,
            Duration,
        )> = async {
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
                let expected_dispatch_revision = binding
                    .expected_revision
                    .checked_add(1)
                    .ok_or("Agentd dispatch revision overflow")?;
                owner_abort_revision = Some(expected_dispatch_revision);
                let commitment = pre_effect_abort_commitment
                    .as_ref()
                    .ok_or("bound Agentd dispatch omitted its abort commitment")?;
                let dispatched = await_before_effect(
                    &execution_clock,
                    RPC_TIMEOUT,
                    "Agentd bound dispatch commit",
                    owner.run_mark_dispatched_bound(
                        binding.run_id.clone(),
                        binding.expected_revision,
                        dispatch_binding_digest.clone(),
                        commitment.clone(),
                    ),
                )
                .await?;
                if dispatched.phase != AgentRunPhase::Dispatched
                    || dispatched.revision != expected_dispatch_revision
                    || dispatched.dispatch_binding_digest.as_deref()
                        != Some(dispatch_binding_digest.as_str())
                    || dispatched.pre_effect_abort_commitment_digest.as_deref()
                        != Some(commitment.as_str())
                    || dispatched.pre_effect_abort_proof_digest.is_some()
                    || dispatched.generation != self.config.generation
                    || dispatched.terminal_observed
                    || dispatched.context_digest.as_deref() != Some(binding.context_digest.as_str())
                    || dispatched.compilation_receipt_digest.as_deref()
                        != Some(binding.envelope_digest.as_str())
                {
                    return Err(
                        "Agentd did not commit the exact bound intelligence dispatch".into(),
                    );
                }
                intelligence_revision = Some(dispatched.revision);
            }
            let post_health = await_before_effect(
                &execution_clock,
                RPC_TIMEOUT,
                "Agentd final health",
                owner.health(),
            )
            .await?;
            let current_ingress = await_before_effect(
                &execution_clock,
                RPC_TIMEOUT,
                "Agentd final ingress",
                owner.session_ingress(),
            )
            .await?;
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
                let revalidated = await_before_effect(
                    &execution_clock,
                    RPC_TIMEOUT,
                    "Agentd cognitive final-use revalidation",
                    owner.revalidate_cognitive_context(snapshot),
                )
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
            let attempt = attempt
                .prepare_durable(request_receipt.request_digest)?
                .commit_owner(
                    intelligence_revision.unwrap_or(prepared_revision),
                    request_receipt.request_digest,
                )?;
            thread_guard.effect_entered().await?;
            if cancellation.is_cancelled() {
                return Err("cancelled after durable preparation before model dispatch".into());
            }
            let send_budget = execution_clock.remaining(unix_time_ms()?)?.min(RPC_TIMEOUT);
            let entered_use = verified_use.enter(&authority_binding)?;
            if !entered_use.matches(&authority_binding) {
                return Err("kernel.authority final-use binding mismatch at entry".into());
            }
            Ok((attempt, entered_use, send_budget))
        }
        .await;
        let (attempt, entered_use, send_budget) = match preparation {
            Ok(value) => value,
            Err(error) => {
                let reason: String = error.to_string().chars().take(512).collect();
                let stopped = match (intelligence, owner_abort_revision) {
                    (Some(binding), Some(owner_dispatch_revision)) => {
                        abort_pre_effect_consistently(
                            control,
                            &owner,
                            binding,
                            owner_dispatch_revision,
                            pre_effect_abort,
                            request_receipt.request_digest,
                            reason,
                        )
                        .await
                    }
                    _ => control
                        .abort_native_before_effect(pre_effect_abort, reason)
                        .map(|_| ())
                        .map_err(Into::into),
                };
                stopped?;
                thread_guard.terminal_persisted().await?;
                thread_guard.cleanup().await;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err(error);
            }
        };
        // From here on, a missing acknowledgement is reconcile-only. Recovery
        // cannot recreate either the local abort proof or the linear send permit.
        drop(pre_effect_abort);
        let (attempt, send_permit) = attempt.enter_effect_with_permit();
        let app_server_session_id = started.thread.session_id.clone();
        let response = timeout(
            send_budget,
            send_authorized_turn_start(&mut client, entered_use, send_permit, turn_params),
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
                        thread_guard.terminal_persisted().await?;
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
                            let unknown_reason = format!(
                                "turn/start returned an accepted-or-unknown JSON-RPC error ({reason}); reconciliation found no exact turn; do not replay"
                            );
                            let output = reconcile_intelligence_start_unknown(
                                &owner,
                                intelligence,
                                intelligence_revision,
                                indeterminate_start_output(started, unknown_reason.clone()),
                            )
                            .await;
                            persist_unknown_turn_start(
                                self,
                                control,
                                request_id,
                                &adapter_intent,
                                request_receipt.request_digest,
                                payload_digest,
                                source_admission_digest,
                                user_input_digest,
                                authority_epoch,
                                revocation_revision,
                                &revocation_head_digest,
                                &authority_witness,
                                codex_home_digest,
                                connection_id,
                                &app_server_session_id,
                                &app_server_version,
                                intelligence,
                                intelligence_revision,
                                prepared_revision,
                                &output,
                                &unknown_reason,
                            )
                            .await?;
                            thread_guard.cleanup().await;
                            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                            return Ok(output);
                        }
                    }
                    _ => return Err("unexpected adapter server-error status".into()),
                }
            }
            Ok(Err(error)) => {
                if let Some(turn) = reconcile_turn_start(&mut client, &started.thread.id).await? {
                    turn
                } else {
                    let unknown_reason = format!(
                        "turn/start transport outcome unknown ({error}); reconciliation found no exact turn; do not replay"
                    );
                    let output = reconcile_intelligence_start_unknown(
                        &owner,
                        intelligence,
                        intelligence_revision,
                        indeterminate_start_output(started, unknown_reason.clone()),
                    )
                    .await;
                    persist_unknown_turn_start(
                        self,
                        control,
                        request_id,
                        &adapter_intent,
                        request_receipt.request_digest,
                        payload_digest,
                        source_admission_digest,
                        user_input_digest,
                        authority_epoch,
                        revocation_revision,
                        &revocation_head_digest,
                        &authority_witness,
                        codex_home_digest,
                        connection_id,
                        &app_server_session_id,
                        &app_server_version,
                        intelligence,
                        intelligence_revision,
                        prepared_revision,
                        &output,
                        &unknown_reason,
                    )
                    .await?;
                    thread_guard.cleanup().await;
                    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                    return Ok(output);
                }
            }
            Err(_) => {
                if let Some(turn) = reconcile_turn_start(&mut client, &started.thread.id).await? {
                    turn
                } else {
                    let unknown_reason =
                        "turn/start timed out; reconciliation found no exact turn; do not replay"
                            .to_string();
                    let output = reconcile_intelligence_start_unknown(
                        &owner,
                        intelligence,
                        intelligence_revision,
                        indeterminate_start_output(started, unknown_reason.clone()),
                    )
                    .await;
                    persist_unknown_turn_start(
                        self,
                        control,
                        request_id,
                        &adapter_intent,
                        request_receipt.request_digest,
                        payload_digest,
                        source_admission_digest,
                        user_input_digest,
                        authority_epoch,
                        revocation_revision,
                        &revocation_head_digest,
                        &authority_witness,
                        codex_home_digest,
                        connection_id,
                        &app_server_session_id,
                        &app_server_version,
                        intelligence,
                        intelligence_revision,
                        prepared_revision,
                        &output,
                        &unknown_reason,
                    )
                    .await?;
                    thread_guard.cleanup().await;
                    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                    return Ok(output);
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
                let _ = owner
                    .run_cancel(
                        binding.run_id.clone(),
                        revision,
                        reason.chars().take(512).collect(),
                    )
                    .await;
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
            // Agentd terminal publication is never performed from volatile
            // execution state. The outer durable settlement creates the exact
            // pending outbox entry and recovery publishes that entry.
        }
        if output.terminal_observed {
            let _ = verify_owner_health(&mut output, owner.health(), Instant::now() + RPC_TIMEOUT)
                .await;
            downgrade_for_owner_loss(&mut output);
            // Local settlement below atomically creates the durable Agentd
            // terminal-publication outbox. No direct cross-owner write occurs
            // before that journal transition.
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
            thread_guard.terminal_persisted().await?;
            thread_guard.cleanup().await;
        }
        thread_guard.cleanup().await;
        let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
        Ok(output)
    }
}
