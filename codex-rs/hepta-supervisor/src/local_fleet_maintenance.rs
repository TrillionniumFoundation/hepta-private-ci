//! Bounded upkeep of the existing durable resource owner.

use super::*;

// Retire the admitted host reference before releasing its original flock,
// including a panic or a detached async waiter dropping a completed job.
struct AdmittedMaintenance {
    host: Arc<LocalFleetHost>,
    _instance: Arc<crate::daemon::owner::SingleInstanceLock>,
}

impl LocalFleetHost {
    pub(crate) async fn maintain(&self) -> Result<(), ProcessDriverError> {
        let _launch = self.launch_gate.lock().await;
        self.roll_resource_epoch_if_needed()?;
        let (observation, _) = self
            .store
            .refresh_local_capacity(&self.observer)
            .await
            .map_err(host_error)?;
        self.store.collect_expired().await.map_err(host_error)?;
        for hold in self.store.pending_executions().await.map_err(host_error)? {
            if self
                .store
                .confirm_local_exit(&hold.context.execution_id)
                .await
                .is_ok()
            {
                let _ = containment::remove_empty_execution(&hold.context.containment);
                continue;
            }
            if hold.state == "stop_requested" {
                self.store
                    .kill_local_containment(&hold.context.execution_id)
                    .await
                    .map_err(host_error)?;
                continue;
            }
            // The next generation is read from the actual durable grant. A
            // revoked/expired grant is never recreated from the hold DTO.
            if hold.state == "running" {
                // Reopen/lost reply reads the exact original committed
                // witness. Its acknowledgement and the next renewal share
                // one transaction; no extra per-tick fsync is introduced.
                let observed = self
                    .store
                    .pending_local_renewal(&hold.context.execution_id)
                    .await
                    .map_err(host_error)?;
                let grant = self
                    .store
                    .allocation_grant(&hold.context.allocation_id)
                    .await
                    .map_err(host_error)?;
                if let Some(grant) = grant {
                    let lease_id = &grant.allocation_id;
                    let revision = self.authorize(
                        lease_id,
                        FleetAuthorityPort::binding_for_renew(
                            &grant,
                            observation.host.valid_until_ms,
                        )
                        .map_err(host_error)?,
                        observation.host.valid_until_ms,
                    )?;
                    self.store
                        .stage_local_renewal_authorized(
                            &FleetAuthorityPort::new(self.authority.verifier()),
                            lease_id,
                            revision,
                            &hold.context.execution_id,
                            codex_hepta_fleet::LocalRenewalRequestV1 {
                                expected_grant: &grant,
                                expires_at_ms: observation.host.valid_until_ms,
                                observed_pending: observed.as_ref(),
                            },
                        )
                        .await
                        .map_err(host_error)?;
                }
            }
        }
        self.store.collect_expired().await.map_err(host_error)?;
        self.store.compact_history(1024).await.map_err(host_error)?;
        self.authority
            .prune_expired_leases(1024)
            .map_err(host_error)?;
        Ok(())
    }

    pub(crate) async fn run_maintenance(
        self: Arc<Self>,
        cancellation: CancellationToken,
        instance: Arc<crate::daemon::owner::SingleInstanceLock>,
    ) -> Result<(), ProcessDriverError> {
        let mut interval = tokio::time::interval(Duration::from_secs(10));
        interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        loop {
            tokio::select! { _ = cancellation.cancelled() => return Ok(()), _ = interval.tick() => {} }
            // An admitted durable owner operation retires before cancellation.
            let owner = AdmittedMaintenance {
                host: Arc::clone(&self),
                _instance: Arc::clone(&instance),
            };
            let outcome = tokio::task::spawn_blocking(move || {
                // A detached/aborted async waiter cannot release the fleet
                // while this original admitted durable operation is running.
                let outcome = owner.host.runtime.block_on(owner.host.maintain());
                drop(owner);
                outcome
            })
            .await
            .map_err(host_error)
            .and_then(|outcome| outcome);
            if let Err(error) = outcome {
                // Startup recovery may still be waiting for its original
                // blocking worker. It must never publish readiness after this
                // sole resource owner has stopped maintaining live grants.
                cancellation.cancel();
                return Err(error);
            }
        }
    }

    pub(super) fn roll_resource_epoch_if_needed(&self) -> Result<(), ProcessDriverError> {
        if self
            .authority
            .capacity()
            .map_err(host_error)?
            .rollover_required_with_reserve(1024)
        {
            let frontier = self.authority.frontier().map_err(host_error)?;
            let next_epoch = frontier
                .authority_epoch
                .checked_add(1)
                .ok_or_else(|| ProcessDriverError::new("resource authority epoch exhausted"))?;
            // Existing Fleet holds remain occupied. Live grants receive fresh
            // exact bindings in the new kernel epoch during this same upkeep;
            // revoked grants are absent from SQLite and cannot be resurrected.
            self.authority
                .advance_epoch(frontier.store_revision, next_epoch)
                .map_err(host_error)?;
        }
        Ok(())
    }
}
