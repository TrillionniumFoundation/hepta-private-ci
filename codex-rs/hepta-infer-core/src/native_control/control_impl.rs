impl DurableInferenceControl {
    /// The first admission pins the local slot limit for this journal. A
    /// duplicate binds every request field and never reserves a second slot.
    pub fn reserve_native(
        &mut self,
        request: NativeRequest,
        maximum_in_flight: usize,
    ) -> Result<NativeRunRecord, Error> {
        if self.poisoned {
            return Err(Error::WriterUnavailable);
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            if self.file.metadata()?.permissions().mode() & 0o077 != 0 {
                return Err(Error::InvalidIdentity("native journal must be owner-only"));
            }
        }
        if self
            .native
            .maximum_in_flight
            .is_some_and(|limit| limit != maximum_in_flight)
            || self.records.contains_key(&request.request_id)
        {
            return Err(Error::Conflict);
        }
        if let Some(record) = self.native.records.get(&request.request_id) {
            return if record.request == request {
                Ok(record.clone())
            } else {
                Err(Error::Conflict)
            };
        }
        if self.records.len() + self.native.records.len() >= self.capacity {
            return Err(Error::CapacityExceeded);
        }
        self.ensure_native_dispatch_space()?;
        let id = request.request_id.clone();
        self.commit_native(
            &id,
            Event::Reserve {
                request,
                maximum_in_flight,
            },
        )
    }

    /// Must commit before the physical provider or local-model effect.
    pub fn dispatch_native(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
    ) -> Result<NativeRunRecord, Error> {
        self.ensure_native_dispatch_space()?;
        self.commit_native(
            request_id,
            Event::Dispatch {
                request_id: request_id.to_string(),
                dispatch,
            },
        )
    }

    pub fn dispatch_native_with_pre_effect_abort(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
    ) -> Result<(NativeRunRecord, NativePreEffectAbortToken), Error> {
        let record = self.dispatch_native(request_id, dispatch)?;
        Ok((
            record.clone(),
            NativePreEffectAbortToken {
                request_id: request_id.to_string(),
                dispatch_revision: record.revision,
            },
        ))
    }

    pub fn abort_native_before_effect(
        &mut self,
        token: NativePreEffectAbortToken,
        reason: String,
    ) -> Result<NativeRunRecord, Error> {
        let record = self
            .native
            .records
            .get(&token.request_id)
            .ok_or(Error::RequestNotFound)?;
        if record.state != NativeReservationState::Dispatching
            || record.revision != token.dispatch_revision
            || record.turn_id.is_some()
            || record.observation.is_some()
            || record.dispatch_rejection.is_some()
            || record.cancel_requested
        {
            return Err(Error::InvalidTransition);
        }
        self.commit_native(
            &token.request_id,
            Event::AbortBeforeEffect {
                request_id: token.request_id.clone(),
                reason,
            },
        )
    }

    pub fn native_started(
        &mut self,
        request_id: &str,
        turn_id: String,
    ) -> Result<NativeRunRecord, Error> {
        self.native_started_at(request_id, turn_id, host_unix_time_ms()?)
    }

    pub fn native_started_at(
        &mut self,
        request_id: &str,
        turn_id: String,
        effect_entered_at_unix_ms: u64,
    ) -> Result<NativeRunRecord, Error> {
        if effect_entered_at_unix_ms == 0 {
            return Err(Error::InvalidTime);
        }
        self.commit_native(
            request_id,
            Event::StartedAt {
                request_id: request_id.to_string(),
                turn_id,
                effect_entered_at_unix_ms,
            },
        )
    }

    pub fn observe_native_authority(
        &mut self,
        request_id: &str,
        observation: NativeAuthorityObservation,
    ) -> Result<NativeRunRecord, Error> {
        let record = self
            .native
            .records
            .get(request_id)
            .ok_or(Error::RequestNotFound)?;
        if record.authority_observation.as_ref() == Some(&observation) {
            return Ok(record.clone());
        }
        self.commit_native(
            request_id,
            Event::AuthorityObserved {
                request_id: request_id.to_string(),
                observation,
            },
        )
    }

    pub fn record_native_interrupt_intent(
        &mut self,
        request_id: &str,
        reason: String,
        requested_at_unix_ms: u64,
    ) -> Result<NativeRunRecord, Error> {
        self.commit_native(
            request_id,
            Event::InterruptIntent {
                request_id: request_id.to_string(),
                observation: NativeInterruptObservation {
                    reason,
                    requested_at_unix_ms,
                    observed_at_unix_ms: None,
                    outcome: NativeInterruptOutcome::Requested,
                    evidence_digest: None,
                },
            },
        )
    }

    pub fn record_native_interrupt_outcome(
        &mut self,
        request_id: &str,
        observation: NativeInterruptObservation,
    ) -> Result<NativeRunRecord, Error> {
        self.commit_native(
            request_id,
            Event::InterruptOutcome {
                request_id: request_id.to_string(),
                observation,
            },
        )
    }

    /// A typed JSON-RPC error proves a returned rejection only before start.
    pub fn reject_native_before_start(
        &mut self,
        request_id: &str,
        rejection: NativeDispatchRejection,
    ) -> Result<NativeRunRecord, Error> {
        self.commit_native(
            request_id,
            Event::RejectBeforeStart {
                request_id: request_id.to_string(),
                rejection,
            },
        )
    }

    /// Records cancellation intent only. It never frees a slot.
    pub fn cancel_native(&mut self, request_id: &str) -> Result<NativeRunRecord, Error> {
        let record = self
            .native
            .records
            .get(request_id)
            .ok_or(Error::RequestNotFound)?;
        if record.cancel_requested {
            return Ok(record.clone());
        }
        self.commit_native(
            request_id,
            Event::Cancel {
                request_id: request_id.to_string(),
            },
        )
    }

    pub fn stop_native_before_dispatch(
        &mut self,
        request_id: &str,
        reason: String,
    ) -> Result<NativeRunRecord, Error> {
        self.commit_native(
            request_id,
            Event::Stop {
                request_id: request_id.to_string(),
                reason,
            },
        )
    }

    pub fn stop_native_before_turn_start(
        &mut self,
        token: NativePreEffectAbortToken,
        reason: String,
    ) -> Result<NativeRunRecord, Error> {
        self.abort_native_before_effect(token, reason)
    }

    pub fn settle_native(
        &mut self,
        request_id: &str,
        output: NativeRunOutput,
    ) -> Result<NativeRunRecord, Error> {
        self.settle_native_with_usage_at(request_id, output, None, host_unix_time_ms()?)
    }

    pub fn settle_native_with_usage_at(
        &mut self,
        request_id: &str,
        output: NativeRunOutput,
        usage_units: Option<u64>,
        observed_at_unix_ms: u64,
    ) -> Result<NativeRunRecord, Error> {
        if observed_at_unix_ms == 0 {
            return Err(Error::InvalidTime);
        }
        let record = self
            .native
            .records
            .get(request_id)
            .ok_or(Error::RequestNotFound)?;
        if record.observation.as_ref() == Some(&output)
            && usage_units.is_none_or(|usage| record.observed_usage_units == Some(usage))
            && record.last_observed_at_unix_ms == Some(observed_at_unix_ms)
        {
            return Ok(record.clone());
        }
        self.commit_native(
            request_id,
            Event::Observe {
                request_id: request_id.to_string(),
                output,
                observed_at_unix_ms,
                usage_units,
            },
        )
    }

    pub fn settle_native_with_evidence(
        &mut self,
        request_id: &str,
        output: NativeRunOutput,
        evidence: NativeObservationEvidence,
    ) -> Result<NativeRunRecord, Error> {
        if evidence.observed_at_unix_ms == 0 {
            return Err(Error::InvalidTime);
        }
        self.commit_native(
            request_id,
            Event::ObserveV2 {
                request_id: request_id.to_string(),
                output,
                evidence,
            },
        )
    }

    /// Releases a local-model quarantined terminal only after independently
    /// authenticated stop/zero-residency evidence. It never rewrites terminal
    /// truth or upgrades the quarantined outcome to success.
    pub fn release_native_quarantine(
        &mut self,
        request_id: &str,
        evidence: NativeCapacityReleaseEvidence,
    ) -> Result<NativeRunRecord, Error> {
        self.commit_native(
            request_id,
            Event::ReleaseQuarantine {
                request_id: request_id.to_string(),
                evidence,
            },
        )
    }

    pub fn native_record(&self, request_id: &str) -> Option<&NativeRunRecord> {
        self.native.records.get(request_id)
    }

    pub fn native_records(&self) -> impl Iterator<Item = &NativeRunRecord> {
        self.native.records.values()
    }

    pub fn native_maximum_in_flight(&self) -> Option<usize> {
        self.native.maximum_in_flight
    }

    pub fn native_journal_bytes(&self) -> u64 {
        self.journal_bytes
    }

    pub fn journal_record_capacity(&self) -> usize {
        self.capacity
    }

    fn ensure_native_dispatch_space(&self) -> Result<(), Error> {
        if self.journal_bytes > super::MAX_JOURNAL_BYTES - 2 * super::MAX_JOURNAL_LINE_BYTES as u64
        {
            return Err(Error::CapacityExceeded);
        }
        Ok(())
    }

    fn commit_native(&mut self, request_id: &str, event: Event) -> Result<NativeRunRecord, Error> {
        let mut next = self.native.clone();
        next.apply(event.clone())?;
        let json =
            serde_json::to_string(&event).map_err(|_| Error::CorruptJournal("native encode"))?;
        self.append(&format!("{JOURNAL_PREFIX}{json}\n"))?;
        self.native = next;
        self.native
            .records
            .get(request_id)
            .cloned()
            .ok_or(Error::RequestNotFound)
    }
}
