impl<'a, A, E, R> PlannerExecutionCoordinatorV1<'a, A, E, R>
where
    A: IndependentPlannerAuthorityV1,
    E: PlannerEffectExecutorV1,
    R: PlannerTerminalReconcilerV1,
{
    pub fn new(store: &'a mut PlannerStoreV1, authority: A, executor: E, reconciler: R) -> Self {
        Self {
            store,
            authority,
            executor,
            reconciler,
        }
    }

    pub fn execute_request_set(
        &mut self,
        request_set: &GrantRequestSetV1,
        now_micros: u64,
    ) -> Result<PlannerExecutionBatchV1, PlannerExecutionError> {
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

        let mut outcomes = Vec::with_capacity(request_set.requests().len());
        let mut completed_effects = 0_usize;
        for request in request_set.requests() {
            if now_micros >= request.expires_at_micros {
                return Err(PlannerExecutionError::RequestExpired);
            }
            let request_body = canonical_grant_request_body(request);
            let request_digest = evidence_digest(b"hepta.control.authority-request.v1", &request_body);
            self.store.record_evidence(
                PlannerBodyKindV1::AuthorityRequest,
                request_digest,
                request_set.plan_receipt_digest(),
                &request_body,
            )?;

            let decision = self
                .authority
                .authorize(request, request_digest, now_micros)
                .map_err(|message| PlannerExecutionError::PortFailure {
                    stage: "authority",
                    message,
                })?;
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
                        AuthorityDispositionV1::Denied => outcomes.push(
                            PlannerRequestOutcomeV1::Denied {
                                request_digest,
                                terminal_digest: observation.observation_digest,
                            },
                        ),
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
                    return Ok(PlannerExecutionBatchV1 {
                        plan_receipt_digest: request_set.plan_receipt_digest(),
                        request_set_digest: request_set.request_set_digest(),
                        outcomes,
                        complete: false,
                        partial_execution: completed_effects > 0,
                    });
                }
                IndependentAuthorityDecisionV1::Granted(grant) => {
                    validate_grant(&grant, request, request_digest, now_micros)?;
                    self.store.record_evidence(
                        PlannerBodyKindV1::AuthorityGrant,
                        grant.grant_digest,
                        request_digest,
                        &grant.canonical_body,
                    )?;
                    let terminal = self
                        .executor
                        .execute(request, &grant, now_micros)
                        .map_err(|message| PlannerExecutionError::PortFailure {
                            stage: "executor",
                            message,
                        })?;
                    validate_terminal(&terminal, request, &grant, request_digest)?;
                    self.store.record_evidence(
                        PlannerBodyKindV1::TerminalReceipt,
                        terminal.terminal_digest,
                        grant.grant_digest,
                        &terminal.canonical_body,
                    )?;
                    match terminal.disposition {
                        TerminalDispositionV1::Succeeded => {
                            completed_effects += 1;
                            outcomes.push(PlannerRequestOutcomeV1::Succeeded {
                                request_digest,
                                grant_digest: grant.grant_digest,
                                terminal_digest: terminal.terminal_digest,
                            });
                        }
                        TerminalDispositionV1::Failed => {
                            outcomes.push(PlannerRequestOutcomeV1::Failed {
                                request_digest,
                                grant_digest: grant.grant_digest,
                                terminal_digest: terminal.terminal_digest,
                            });
                            return Ok(PlannerExecutionBatchV1 {
                                plan_receipt_digest: request_set.plan_receipt_digest(),
                                request_set_digest: request_set.request_set_digest(),
                                outcomes,
                                complete: false,
                                partial_execution: completed_effects > 0,
                            });
                        }
                        TerminalDispositionV1::Indeterminate => {
                            outcomes.push(PlannerRequestOutcomeV1::Indeterminate(
                                PlannerIndeterminateV1 {
                                    stage: IndeterminateStageV1::Effect,
                                    request_digest,
                                    grant_digest: Some(grant.grant_digest),
                                    final_payload_digest: request.final_payload_digest,
                                    observation_digest: terminal.terminal_digest,
                                    expires_at_micros: request.expires_at_micros,
                                },
                            ));
                            return Ok(PlannerExecutionBatchV1 {
                                plan_receipt_digest: request_set.plan_receipt_digest(),
                                request_set_digest: request_set.request_set_digest(),
                                outcomes,
                                complete: false,
                                partial_execution: completed_effects > 0,
                            });
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
        if now_micros >= pending.expires_at_micros {
            return Err(PlannerExecutionError::RequestExpired);
        }
        if self.store.body(pending.observation_digest)?.is_none() {
            return Err(PlannerExecutionError::ReconciliationBindingMismatch);
        }
        let receipt = self
            .reconciler
            .reconcile(pending, now_micros)
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

    pub fn into_ports(self) -> (A, E, R) {
        (self.authority, self.executor, self.reconciler)
    }
}
