impl<'a, A, E, R> PlannerExecutionCoordinatorV1<'a, A, E, R>
where
    A: IndependentPlannerAuthorityV1,
    E: PlannerEffectExecutorV1,
    R: PlannerTerminalReconcilerV1,
{
    pub fn new(store: &'a mut PlannerStoreV1, authority: A, executor: E, reconciler: R) -> Self {
        Self { store, authority, executor, reconciler }
    }

    pub fn execute_request_set(
        &mut self,
        request_set: &GrantRequestSetV1,
        now_micros: u64,
    ) -> Result<PlannerExecutionBatchV1, PlannerExecutionError> {
        let started = std::time::Instant::now();
        self.execute_request_set_with_clock(request_set, || {
            let elapsed = u64::try_from(started.elapsed().as_micros())
                .map_err(|_| PlannerExecutionError::RequestExpired)?;
            now_micros.checked_add(elapsed).ok_or(PlannerExecutionError::RequestExpired)
        })
    }

    /// The selected host supplies one current monotonic domain. The same clock
    /// is re-read after authority and persistence and before every dispatch.
    pub fn execute_request_set_with_clock<F>(
        &mut self,
        request_set: &GrantRequestSetV1,
        mut current_time: F,
    ) -> Result<PlannerExecutionBatchV1, PlannerExecutionError>
    where
        F: FnMut() -> Result<u64, PlannerExecutionError>,
    {
        let now_micros = current_time()?;
        let mut last_time = now_micros;
        let mut checked_time = || {
            let now = current_time()?;
            if now < last_time {
                return Err(PlannerExecutionError::RequestExpired);
            }
            last_time = now;
            Ok(now)
        };
        if request_set.authority().grants_any() {
            return Err(PlannerExecutionError::AuthorityViolation);
        }
        if request_set.requests().is_empty() {
            return Err(PlannerExecutionError::EmptyRequestSet);
        }
        if request_set.requests().len() > MAX_EXECUTION_REQUESTS {
            return Err(PlannerExecutionError::RequestLimitExceeded);
        }
        let Some(decision) = self.store.body(request_set.plan_receipt_digest())? else {
            return Err(PlannerExecutionError::DecisionBodyMissing);
        };
        if decision.kind() != PlannerBodyKindV1::Decision {
            return Err(PlannerExecutionError::DecisionBodyMissing);
        }
        // Preflight the entire batch before any port invocation. Existing
        // durable intent means a previous process may already have dispatched;
        // it is never permission to retry the executor.
        for request in request_set.requests() {
            if now_micros >= request.expires_at_micros {
                return Err(PlannerExecutionError::RequestExpired);
            }
            let request_digest = grant_request_digest(request);
            if self.store.body(request_digest)?.is_some() {
                return Err(PlannerExecutionError::RecoveryRequired { request_digest });
            }
        }
        let mut outcomes = Vec::with_capacity(request_set.requests().len());
        let mut attempted_effects = 0_usize;
        for request in request_set.requests() {
            let now = checked_time()?;
            if now >= request.expires_at_micros {
                return Err(PlannerExecutionError::RequestExpired);
            }
            let request_body = canonical_grant_request_body(request);
            let request_digest = grant_request_digest(request);
            self.store.record_evidence(
                PlannerBodyKindV1::AuthorityRequest,
                request_digest,
                request_set.plan_receipt_digest(),
                &request_body,
            )?;
            let authority_time = checked_time()?;
            if authority_time >= request.expires_at_micros {
                return Err(PlannerExecutionError::RequestExpired);
            }
            let decision = match self.authority.authorize(request, request_digest, authority_time) {
                Ok(decision) => decision,
                Err(_) => {
                    // The durable request is an intent, not a fabricated
                    // signed observation. A transport error cannot prove that
                    // the authority did not process the request.
                    outcomes.push(PlannerRequestOutcomeV1::Indeterminate(PlannerIndeterminateV1 {
                        stage: IndeterminateStageV1::Authority,
                        request_digest,
                        grant_digest: None,
                        final_payload_digest: request.final_payload_digest,
                        observation_digest: request_digest,
                        expires_at_micros: request.expires_at_micros,
                    }));
                    return Ok(interrupted_batch(request_set, outcomes, attempted_effects));
                }
            };
            match decision {
                IndependentAuthorityDecisionV1::Observation(observation) => {
                    validate_authority_observation(&observation, request_digest)?;
                    self.store.record_evidence(
                        PlannerBodyKindV1::TerminalReceipt,
                        observation.observation_digest,
                        request_digest,
                        &observation.canonical_body,
                    )?;
                    match observation.disposition {
                        AuthorityDispositionV1::Denied => outcomes.push(PlannerRequestOutcomeV1::Denied {
                            request_digest,
                            terminal_digest: observation.observation_digest,
                        }),
                        AuthorityDispositionV1::Indeterminate => outcomes.push(
                            PlannerRequestOutcomeV1::Indeterminate(PlannerIndeterminateV1 {
                                stage: IndeterminateStageV1::Authority,
                                request_digest,
                                grant_digest: None,
                                final_payload_digest: request.final_payload_digest,
                                observation_digest: observation.observation_digest,
                                expires_at_micros: request.expires_at_micros,
                            }),
                        ),
                    }
                    return Ok(interrupted_batch(request_set, outcomes, attempted_effects));
                }
                IndependentAuthorityDecisionV1::Granted(grant) => {
                    validate_grant(&grant, request, request_digest, checked_time()?)?;
                    self.store.record_evidence(
                        PlannerBodyKindV1::AuthorityGrant,
                        grant.grant_digest,
                        request_digest,
                        &grant.canonical_body,
                    )?;
                    // Persistence may have consumed the remaining lease.
                    let dispatch_time = checked_time()?;
                    validate_grant(&grant, request, request_digest, dispatch_time)?;
                    attempted_effects += 1;
                    let terminal = match self.executor.execute(request, &grant, dispatch_time) {
                        Ok(terminal) => terminal,
                        Err(_) => {
                            outcomes.push(PlannerRequestOutcomeV1::Indeterminate(PlannerIndeterminateV1 {
                                stage: IndeterminateStageV1::Effect,
                                request_digest,
                                grant_digest: Some(grant.grant_digest),
                                final_payload_digest: request.final_payload_digest,
                                observation_digest: grant.grant_digest,
                                expires_at_micros: request.expires_at_micros,
                            }));
                            return Ok(interrupted_batch(request_set, outcomes, attempted_effects));
                        }
                    };
                    validate_terminal(&terminal, request, &grant, request_digest)?;
                    self.store.record_evidence(
                        PlannerBodyKindV1::TerminalReceipt,
                        terminal.terminal_digest,
                        grant.grant_digest,
                        &terminal.canonical_body,
                    )?;
                    match terminal.disposition {
                        TerminalDispositionV1::Succeeded => outcomes.push(PlannerRequestOutcomeV1::Succeeded {
                            request_digest,
                            grant_digest: grant.grant_digest,
                            terminal_digest: terminal.terminal_digest,
                        }),
                        TerminalDispositionV1::Failed => {
                            outcomes.push(PlannerRequestOutcomeV1::Failed {
                                request_digest,
                                grant_digest: grant.grant_digest,
                                terminal_digest: terminal.terminal_digest,
                            });
                            return Ok(interrupted_batch(request_set, outcomes, attempted_effects));
                        }
                        TerminalDispositionV1::Indeterminate => {
                            outcomes.push(PlannerRequestOutcomeV1::Indeterminate(PlannerIndeterminateV1 {
                                stage: IndeterminateStageV1::Effect,
                                request_digest,
                                grant_digest: Some(grant.grant_digest),
                                final_payload_digest: request.final_payload_digest,
                                observation_digest: terminal.terminal_digest,
                                expires_at_micros: request.expires_at_micros,
                            }));
                            return Ok(interrupted_batch(request_set, outcomes, attempted_effects));
                        }
                    }
                }
            }
        }
        Ok(PlannerExecutionBatchV1 {
            plan_receipt_digest: request_set.plan_receipt_digest(),
            request_set_digest: request_set.request_set_digest(),
            outcomes,
            complete: true,
            partial_execution: false,
        })
    }

    pub fn reconcile(
        &mut self,
        pending: &PlannerIndeterminateV1,
        now_micros: u64,
    ) -> Result<SignedReconciliationReceiptV1, PlannerExecutionError> {
        // Expiry forbids new effects, not observation of an earlier effect.
        // Validate the request and complete durable ancestry before handing
        // caller-provided pending fields to the independent read-only port.
        validate_pending(self.store, pending)?;
        let receipt = self.reconciler.reconcile(pending, now_micros)
            .map_err(|message| PlannerExecutionError::PortFailure {
                stage: "reconciler",
                message,
            })?;
        validate_reconciliation(&receipt, pending)?;
        self.store.record_evidence(
            PlannerBodyKindV1::Reconciliation,
            receipt.reconciliation_digest,
            pending.observation_digest,
            &receipt.canonical_body,
        )?;
        Ok(receipt)
    }

    /// Rebuild a bounded reconciliation inventory from durable requests after
    /// restart. This intentionally includes previously completed requests;
    /// the independent reconciler determines their terminal state. Discovery
    /// never invokes authority/executor or treats missing acknowledgement as
    /// permission to dispatch again.
    pub fn discover_reconciliation_candidates(
        &self,
    ) -> Result<Vec<PlannerIndeterminateV1>, PlannerExecutionError> {
        let mut pending = Vec::new();
        for body in self.store.evidence_bodies()? {
            if body.kind() != PlannerBodyKindV1::AuthorityRequest {
                continue;
            }
            let request = decode_grant_request_body(body.bytes())?;
            if grant_request_digest(&request) != body.semantic_digest() {
                return Err(PlannerExecutionError::ReconciliationBindingMismatch);
            }
            let grants = self.store.evidence_bodies()?.filter(|candidate| {
                candidate.kind() == PlannerBodyKindV1::AuthorityGrant
                    && candidate.parent_digest() == Some(body.semantic_digest())
            }).collect::<Vec<_>>();
            if grants.len() > 1 {
                return Err(PlannerExecutionError::ReconciliationBindingMismatch);
            }
            let grant_digest = grants.first().map(|grant| grant.semantic_digest());
            pending.push(PlannerIndeterminateV1 {
                stage: if grant_digest.is_some() {
                    IndeterminateStageV1::Effect
                } else {
                    IndeterminateStageV1::Authority
                },
                request_digest: body.semantic_digest(),
                grant_digest,
                final_payload_digest: request.final_payload_digest,
                observation_digest: grant_digest.unwrap_or(body.semantic_digest()),
                expires_at_micros: request.expires_at_micros,
            });
        }
        Ok(pending)
    }

    pub fn into_ports(self) -> (A, E, R) {
        (self.authority, self.executor, self.reconciler)
    }
}

fn interrupted_batch(
    requests: &GrantRequestSetV1,
    outcomes: Vec<PlannerRequestOutcomeV1>,
    attempted_effects: usize,
) -> PlannerExecutionBatchV1 {
    PlannerExecutionBatchV1 {
        plan_receipt_digest: requests.plan_receipt_digest(),
        request_set_digest: requests.request_set_digest(),
        outcomes,
        complete: false,
        partial_execution: attempted_effects > 0,
    }
}
