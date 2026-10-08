//! Lifecycle step implementation for the production runtime.

use sha2::Digest;

use super::ProductionTargetHostRuntime;
use super::cell_split_production_contract::*;

impl ProductionTargetHostRuntime {
    pub(crate) fn owner_request(&self) -> ProductionOwnerRequestV1 {
        ProductionOwnerRequestV1 {
            split_id: self.config.split_id.clone(),
            namespace: self.config.namespace.clone(),
            parent_generation: self.config.parent_generation,
            child_generation: self.config.child_generation,
            parent_artifact_digest: self.config.parent_artifact_digest.clone(),
            child_artifact_digest: self.config.child_artifact_digest.clone(),
            parameter_bundle_digest: self.config.parameter_bundle_digest.clone(),
            migration_digest: self.config.migration_digest.clone(),
            predecessor_receipt_digest: self.last_receipt_digest(),
        }
    }

    pub(crate) fn ensure_bindings(&self) -> Result<(), CellSplitTargetHostRuntimeErrorV1> {
        let c = &self.config;
        if c.split_id.is_empty() {
            return Err(CellSplitTargetHostRuntimeErrorV1::MissingExternalInput {
                input: "split_id",
            });
        }
        if c.namespace.is_empty() {
            return Err(CellSplitTargetHostRuntimeErrorV1::MissingExternalInput {
                input: "namespace",
            });
        }
        if c.target_host_id.is_empty() {
            return Err(CellSplitTargetHostRuntimeErrorV1::MissingExternalInput {
                input: "target_host_id",
            });
        }
        if c.target_host_nonce.is_empty() {
            return Err(CellSplitTargetHostRuntimeErrorV1::MissingExternalInput {
                input: "target_host_nonce",
            });
        }
        if c.parent_generation == 0 || c.child_generation != c.parent_generation.saturating_add(1) {
            return Err(CellSplitTargetHostRuntimeErrorV1::InvalidConfiguration(
                "generation fence",
            ));
        }
        for (name, digest) in [
            ("parent_artifact_digest", c.parent_artifact_digest.as_str()),
            ("child_artifact_digest", c.child_artifact_digest.as_str()),
            (
                "parameter_bundle_digest",
                c.parameter_bundle_digest.as_str(),
            ),
            ("migration_digest", c.migration_digest.as_str()),
            ("trust_root_digest", c.trust_root_digest.as_str()),
        ] {
            if !digest_shape(digest) || digest == ZERO_DIGEST {
                return Err(CellSplitTargetHostRuntimeErrorV1::MissingExternalInput {
                    input: name,
                });
            }
        }
        if c.minimum_future_window_samples == 0 {
            return Err(CellSplitTargetHostRuntimeErrorV1::MissingExternalInput {
                input: "minimum_future_window_samples",
            });
        }
        self.check_binding(
            "artifact",
            c.artifact_owner.as_ref().map(|owner| owner.binding()),
        )?;
        self.check_binding(
            "cns-route",
            c.route_owner.as_ref().map(|owner| owner.binding()),
        )?;
        self.check_binding(
            "fault-injector",
            c.fault_injector.as_ref().map(|owner| owner.binding()),
        )?;
        self.check_binding(
            "tombstone",
            c.tombstone_owner.as_ref().map(|owner| owner.binding()),
        )?;
        self.check_binding(
            "taskflow",
            c.taskflow_owner.as_ref().map(|owner| owner.binding()),
        )?;
        self.check_binding(
            "host-telemetry",
            c.telemetry_owner.as_ref().map(|owner| owner.binding()),
        )?;
        self.check_binding(
            "hardware-attestation",
            c.hardware_attestation_owner
                .as_ref()
                .map(|owner| owner.binding()),
        )?;
        self.check_binding(
            "learning-ledger",
            c.learning_ledger_owner
                .as_ref()
                .map(|owner| owner.binding()),
        )?;
        self.check_binding(
            "future-window-evaluator",
            c.future_window_evaluator_owner
                .as_ref()
                .map(|owner| owner.binding()),
        )?;
        self.check_binding(
            "evidence-signing",
            c.evidence_signing_owner
                .as_ref()
                .map(|owner| owner.binding()),
        )?;
        Ok(())
    }

    pub(crate) fn check_binding(
        &self,
        name: &'static str,
        owner: Option<&ProductionOwnerBindingV1>,
    ) -> Result<(), CellSplitTargetHostRuntimeErrorV1> {
        let owner =
            owner.ok_or(CellSplitTargetHostRuntimeErrorV1::MissingExternalInput { input: name })?;
        if owner.owner_id.is_empty() || owner.namespace != self.config.namespace {
            return Err(CellSplitTargetHostRuntimeErrorV1::UnboundOwner {
                owner: name,
                namespace: self.config.namespace.clone(),
            });
        }
        if owner.trust_root_digest != self.config.trust_root_digest {
            return Err(CellSplitTargetHostRuntimeErrorV1::WrongTrustRoot { owner: name });
        }
        Ok(())
    }

    pub(crate) fn bind_owners(&mut self) -> Result<(), CellSplitTargetHostRuntimeErrorV1> {
        self.advance_without_receipt(CellSplitProductionLifecycleStepV1::OwnersBound)
    }

    pub(crate) fn load_artifacts(&mut self) -> Result<(), CellSplitTargetHostRuntimeErrorV1> {
        if self.already_at(CellSplitProductionLifecycleStepV1::ArtifactsLoaded) {
            return Ok(());
        }
        self.require_previous(CellSplitProductionLifecycleStepV1::OwnersBound)?;
        let owner =
            self.config.artifact_owner.as_ref().ok_or(
                CellSplitTargetHostRuntimeErrorV1::MissingExternalInput { input: "artifact" },
            )?;
        let owner_id = owner.binding().owner_id.clone();
        let receipt = owner
            .load_parent_child(&self.owner_request())
            .map_err(|error| self.external("artifact", error))?;
        if receipt.artifact_digest != self.config.child_artifact_digest {
            return Err(CellSplitTargetHostRuntimeErrorV1::ReceiptMismatch {
                step: CellSplitProductionLifecycleStepV1::ArtifactsLoaded,
                detail: "child artifact digest",
            });
        }
        self.record(
            CellSplitProductionLifecycleStepV1::ArtifactsLoaded,
            receipt.clone(),
        )?;
        self.packet.artifact_cas_registry = Some(ArtifactCasRegistryPacketV1 {
            owner_id,
            namespace: self.config.namespace.clone(),
            parent_generation: self.config.parent_generation,
            child_generation: self.config.child_generation,
            parent_artifact_digest: self.config.parent_artifact_digest.clone(),
            child_artifact_digest: self.config.child_artifact_digest.clone(),
            parameter_bundle_digest: self.config.parameter_bundle_digest.clone(),
            registry_head_digest: receipt.witness_digest,
            cas_read_receipt_digest: receipt.receipt_digest,
        });
        Ok(())
    }

    pub(crate) fn measure_resources(&mut self) -> Result<(), CellSplitTargetHostRuntimeErrorV1> {
        if self.packet.resources.is_some() {
            return Ok(());
        }
        self.require_previous(CellSplitProductionLifecycleStepV1::ArtifactsLoaded)?;
        let telemetry = self.config.telemetry_owner.as_ref().ok_or(
            CellSplitTargetHostRuntimeErrorV1::MissingExternalInput {
                input: "host-telemetry",
            },
        )?;
        let attestation = self.config.hardware_attestation_owner.as_ref().ok_or(
            CellSplitTargetHostRuntimeErrorV1::MissingExternalInput {
                input: "hardware-attestation",
            },
        )?;
        let measurements = telemetry
            .sample(&self.owner_request())
            .map_err(|error| self.external("host-telemetry", error))?;
        if measurements.is_empty() {
            return Err(CellSplitTargetHostRuntimeErrorV1::ResourceSampleMissing);
        }
        let attestation = attestation
            .attest(&self.owner_request())
            .map_err(|error| self.external("hardware-attestation", error))?;
        if attestation.attestation_digest.is_empty() {
            return Err(CellSplitTargetHostRuntimeErrorV1::ResourceSampleMissing);
        }
        for measurement in &measurements {
            if measurement.sample.hardware_attestation_digest != attestation.attestation_digest
                || measurement.sample.sample_count == 0
            {
                return Err(CellSplitTargetHostRuntimeErrorV1::ReceiptMismatch {
                    step: CellSplitProductionLifecycleStepV1::ArtifactsLoaded,
                    detail: "resource attestation/sample",
                });
            }
        }
        self.measurements = measurements;
        self.packet.resources = Some(ProductionResourceSamplesPacketV1 {
            samples: self
                .measurements
                .iter()
                .map(|measurement| measurement.sample.clone())
                .collect(),
            hardware_attestation_digest: attestation.attestation_digest,
            telemetry_receipt_digest: self.measurements[0].operation.receipt_digest.clone(),
        });
        Ok(())
    }

    pub(crate) fn cutover_route(&mut self) -> Result<(), CellSplitTargetHostRuntimeErrorV1> {
        if self.already_at(CellSplitProductionLifecycleStepV1::RouteCutover) {
            return Ok(());
        }
        self.require_previous(CellSplitProductionLifecycleStepV1::ArtifactsLoaded)?;
        let owner = self.config.route_owner.as_ref().ok_or(
            CellSplitTargetHostRuntimeErrorV1::MissingExternalInput { input: "cns-route" },
        )?;
        let receipt = owner
            .cutover(&self.owner_request())
            .map_err(|error| self.external("cns-route", error))?;
        self.record(CellSplitProductionLifecycleStepV1::RouteCutover, receipt)?;
        Ok(())
    }

    pub(crate) fn dispatch(&mut self) -> Result<(), CellSplitTargetHostRuntimeErrorV1> {
        if self.already_at(CellSplitProductionLifecycleStepV1::Dispatched) {
            return Ok(());
        }
        self.require_previous(CellSplitProductionLifecycleStepV1::RouteCutover)?;
        let owner = self.config.route_owner.as_ref().ok_or(
            CellSplitTargetHostRuntimeErrorV1::MissingExternalInput { input: "cns-route" },
        )?;
        let owner_id = owner.binding().owner_id.clone();
        let receipt = owner
            .dispatch(&self.owner_request())
            .map_err(|error| self.external("cns-route", error))?;
        let predecessor = self
            .receipt(CellSplitProductionLifecycleStepV1::RouteCutover)?
            .receipt_digest
            .clone();
        self.record(
            CellSplitProductionLifecycleStepV1::Dispatched,
            receipt.clone(),
        )?;
        self.packet.cns_dispatch = Some(CnsDispatchPacketV1 {
            owner_id,
            namespace: self.config.namespace.clone(),
            predecessor_route_digest: predecessor,
            successor_route_digest: receipt.route_digest.clone(),
            dispatch_receipt_digest: receipt.receipt_digest,
            route_fence_digest: receipt.witness_digest,
            parent_generation: self.config.parent_generation,
            child_generation: self.config.child_generation,
        });
        Ok(())
    }

    pub(crate) fn clean_restart(&mut self) -> Result<(), CellSplitTargetHostRuntimeErrorV1> {
        if self.already_at(CellSplitProductionLifecycleStepV1::CleanRestarted) {
            return Ok(());
        }
        self.require_previous(CellSplitProductionLifecycleStepV1::Dispatched)?;
        let owner = self.config.fault_injector.as_ref().ok_or(
            CellSplitTargetHostRuntimeErrorV1::MissingExternalInput {
                input: "fault-injector",
            },
        )?;
        let receipt = owner
            .clean_restart(&self.owner_request())
            .map_err(|error| self.external("fault-injector", error))?;
        self.record(CellSplitProductionLifecycleStepV1::CleanRestarted, receipt)?;
        Ok(())
    }

    pub(crate) fn approve_power_loss(&mut self) -> Result<(), CellSplitTargetHostRuntimeErrorV1> {
        if self.already_at(CellSplitProductionLifecycleStepV1::ApprovedPowerLoss) {
            return Ok(());
        }
        self.require_previous(CellSplitProductionLifecycleStepV1::CleanRestarted)?;
        if !self.config.approved_power_loss {
            return Err(CellSplitTargetHostRuntimeErrorV1::PowerLossNotApproved);
        }
        let owner = self.config.fault_injector.as_ref().ok_or(
            CellSplitTargetHostRuntimeErrorV1::MissingExternalInput {
                input: "fault-injector",
            },
        )?;
        let receipt = owner
            .approved_power_loss(&self.owner_request())
            .map_err(|error| self.external("fault-injector", error))?;
        if receipt.witness_digest.is_empty() {
            return Err(CellSplitTargetHostRuntimeErrorV1::ReceiptMismatch {
                step: CellSplitProductionLifecycleStepV1::ApprovedPowerLoss,
                detail: "fault witness",
            });
        }
        self.record(
            CellSplitProductionLifecycleStepV1::ApprovedPowerLoss,
            receipt,
        )?;
        Ok(())
    }

    pub(crate) fn recover(&mut self) -> Result<(), CellSplitTargetHostRuntimeErrorV1> {
        if self.already_at(CellSplitProductionLifecycleStepV1::Recovered) {
            return Ok(());
        }
        self.require_previous(CellSplitProductionLifecycleStepV1::ApprovedPowerLoss)?;
        let owner = self.config.fault_injector.as_ref().ok_or(
            CellSplitTargetHostRuntimeErrorV1::MissingExternalInput {
                input: "fault-injector",
            },
        )?;
        let receipt = owner
            .recover(&self.owner_request())
            .map_err(|error| self.external("fault-injector", error))?;
        let clean = self
            .receipt(CellSplitProductionLifecycleStepV1::CleanRestarted)?
            .receipt_digest
            .clone();
        let power = self
            .receipt(CellSplitProductionLifecycleStepV1::ApprovedPowerLoss)?
            .receipt_digest
            .clone();
        self.record(
            CellSplitProductionLifecycleStepV1::Recovered,
            receipt.clone(),
        )?;
        self.packet.route_fence_restart_replay = Some(RouteFenceRestartReplayPacketV1 {
            route_fence_digest: self
                .packet
                .cns_dispatch
                .as_ref()
                .map_or_else(String::new, |packet| packet.route_fence_digest.clone()),
            clean_restart_receipt_digest: clean,
            recovery_receipt_digest: receipt.receipt_digest,
            replay_chain_digest: power,
            child_generation: self.config.child_generation,
        });
        Ok(())
    }

    pub(crate) fn rollback(&mut self) -> Result<(), CellSplitTargetHostRuntimeErrorV1> {
        if self.already_at(CellSplitProductionLifecycleStepV1::RolledBack) {
            return Ok(());
        }
        self.require_previous(CellSplitProductionLifecycleStepV1::Recovered)?;
        let owner = self.config.route_owner.as_ref().ok_or(
            CellSplitTargetHostRuntimeErrorV1::MissingExternalInput { input: "cns-route" },
        )?;
        let receipt = owner
            .rollback_route(&self.owner_request())
            .map_err(|error| self.external("cns-route", error))?;
        if receipt.generation != self.config.parent_generation {
            return Err(CellSplitTargetHostRuntimeErrorV1::ReceiptMismatch {
                step: CellSplitProductionLifecycleStepV1::RolledBack,
                detail: "rollback generation",
            });
        }
        self.record(CellSplitProductionLifecycleStepV1::RolledBack, receipt)?;
        Ok(())
    }

    pub(crate) fn tombstone(&mut self) -> Result<(), CellSplitTargetHostRuntimeErrorV1> {
        if self.already_at(CellSplitProductionLifecycleStepV1::Tombstoned) {
            return Ok(());
        }
        self.require_previous(CellSplitProductionLifecycleStepV1::RolledBack)?;
        let owner = self.config.tombstone_owner.as_ref().ok_or(
            CellSplitTargetHostRuntimeErrorV1::MissingExternalInput { input: "tombstone" },
        )?;
        let receipt = owner
            .commit_tombstone(&self.owner_request())
            .map_err(|error| self.external("tombstone", error))?;
        if receipt.tombstone_digest.is_empty() {
            return Err(CellSplitTargetHostRuntimeErrorV1::TombstoneMissing);
        }
        self.record(CellSplitProductionLifecycleStepV1::Tombstoned, receipt)?;
        Ok(())
    }

    pub(crate) fn reject_old_generation(
        &mut self,
    ) -> Result<(), CellSplitTargetHostRuntimeErrorV1> {
        if self.already_at(CellSplitProductionLifecycleStepV1::OldGenerationRejected) {
            return Ok(());
        }
        self.require_previous(CellSplitProductionLifecycleStepV1::Tombstoned)?;
        let route = self.config.route_owner.as_ref().ok_or(
            CellSplitTargetHostRuntimeErrorV1::MissingExternalInput { input: "cns-route" },
        )?;
        let tombstone = self.config.tombstone_owner.as_ref().ok_or(
            CellSplitTargetHostRuntimeErrorV1::MissingExternalInput { input: "tombstone" },
        )?;
        let receipt = route
            .reject_old_generation(&self.owner_request())
            .map_err(|error| self.external("cns-route", error))?;
        let no_resurrection = tombstone
            .verify_no_resurrection(&self.owner_request())
            .map_err(|error| self.external("tombstone", error))?;
        if no_resurrection.tombstone_digest.is_empty()
            || receipt.generation != self.config.parent_generation
        {
            return Err(CellSplitTargetHostRuntimeErrorV1::TombstoneMissing);
        }
        self.record(
            CellSplitProductionLifecycleStepV1::OldGenerationRejected,
            receipt.clone(),
        )?;
        self.packet.lifecycle_witness = Some(RestartPowerLossRollbackTombstonePacketV1 {
            clean_restart_digest: self
                .receipt(CellSplitProductionLifecycleStepV1::CleanRestarted)?
                .receipt_digest
                .clone(),
            approved_power_loss_digest: self
                .receipt(CellSplitProductionLifecycleStepV1::ApprovedPowerLoss)?
                .receipt_digest
                .clone(),
            recovery_digest: self
                .receipt(CellSplitProductionLifecycleStepV1::Recovered)?
                .receipt_digest
                .clone(),
            rollback_digest: self
                .receipt(CellSplitProductionLifecycleStepV1::RolledBack)?
                .receipt_digest
                .clone(),
            tombstone_digest: self
                .receipt(CellSplitProductionLifecycleStepV1::Tombstoned)?
                .tombstone_digest
                .clone(),
            no_resurrection_digest: no_resurrection.tombstone_digest,
            old_generation_reject_digest: receipt.receipt_digest,
        });
        Ok(())
    }

    pub(crate) fn evaluate_future_window(
        &mut self,
    ) -> Result<(), CellSplitTargetHostRuntimeErrorV1> {
        if self.already_at(CellSplitProductionLifecycleStepV1::FutureWindowEvaluated) {
            return Ok(());
        }
        self.require_previous(CellSplitProductionLifecycleStepV1::OldGenerationRejected)?;
        let owner = self.config.future_window_evaluator_owner.as_ref().ok_or(
            CellSplitTargetHostRuntimeErrorV1::MissingExternalInput {
                input: "future-window-evaluator",
            },
        )?;
        let result = owner
            .evaluate(&self.owner_request())
            .map_err(|error| self.external("future-window-evaluator", error))?;
        if result.future_window.observation_count < self.config.minimum_future_window_samples {
            return Err(
                CellSplitTargetHostRuntimeErrorV1::FutureWindowInsufficient {
                    observed: result.future_window.observation_count,
                    minimum: self.config.minimum_future_window_samples,
                },
            );
        }
        self.record(
            CellSplitProductionLifecycleStepV1::FutureWindowEvaluated,
            result.operation.clone(),
        )?;
        self.packet.baseline = Some(result.baseline);
        self.packet.future_window = Some(result.future_window);
        Ok(())
    }

    pub(crate) fn sign_evidence(&mut self) -> Result<(), CellSplitTargetHostRuntimeErrorV1> {
        if self.already_at(CellSplitProductionLifecycleStepV1::EvidenceSigned) {
            return Ok(());
        }
        self.require_previous(CellSplitProductionLifecycleStepV1::FutureWindowEvaluated)?;
        let owner = self.config.evidence_signing_owner.as_ref().ok_or(
            CellSplitTargetHostRuntimeErrorV1::MissingExternalInput {
                input: "evidence-signing",
            },
        )?;
        let result = owner
            .sign_host_and_observer(&self.owner_request())
            .map_err(|error| self.external("evidence-signing", error))?;
        if result.evidence.host_signature_digest.is_empty()
            || result.evidence.observer_signature_digest.is_empty()
            || result.evidence.trust_root_digest != self.config.trust_root_digest
        {
            return Err(CellSplitTargetHostRuntimeErrorV1::ObserverSignatureMismatch);
        }
        self.record(
            CellSplitProductionLifecycleStepV1::EvidenceSigned,
            result.operation.clone(),
        )?;
        self.packet.signed_evidence = Some(result.evidence);
        Ok(())
    }

    pub(crate) fn replay_taskflow_and_ledger(
        &mut self,
    ) -> Result<(), CellSplitTargetHostRuntimeErrorV1> {
        if self.already_at(CellSplitProductionLifecycleStepV1::TaskFlowLedgerReplayed) {
            return Ok(());
        }
        self.require_previous(CellSplitProductionLifecycleStepV1::EvidenceSigned)?;
        let taskflow =
            self.config.taskflow_owner.as_ref().ok_or(
                CellSplitTargetHostRuntimeErrorV1::MissingExternalInput { input: "taskflow" },
            )?;
        let ledger = self.config.learning_ledger_owner.as_ref().ok_or(
            CellSplitTargetHostRuntimeErrorV1::MissingExternalInput {
                input: "learning-ledger",
            },
        )?;
        let run = taskflow
            .run(&self.owner_request())
            .map_err(|error| self.external("taskflow", error))?;
        let replay = taskflow
            .replay(&self.owner_request())
            .map_err(|error| self.external("taskflow", error))?;
        let witness = ledger
            .append_witness(&self.owner_request())
            .map_err(|error| self.external("learning-ledger", error))?;
        let ledger_replay = ledger
            .replay(&self.owner_request())
            .map_err(|error| self.external("learning-ledger", error))?;
        if replay.taskflow.event_chain_digest.is_empty()
            || ledger_replay.frontier.witness_frontier_digest.is_empty()
        {
            return Err(CellSplitTargetHostRuntimeErrorV1::ReplayChainGap);
        }
        self.record(
            CellSplitProductionLifecycleStepV1::TaskFlowLedgerReplayed,
            witness,
        )?;
        self.packet.taskflow = Some(replay.taskflow);
        self.packet.learning_ledger = Some(ledger_replay.frontier);
        let _ = run;
        Ok(())
    }

    pub(crate) fn independent_verify(&mut self) -> Result<(), CellSplitTargetHostRuntimeErrorV1> {
        if self.already_at(CellSplitProductionLifecycleStepV1::IndependentlyVerified) {
            return Ok(());
        }
        self.require_previous(CellSplitProductionLifecycleStepV1::TaskFlowLedgerReplayed)?;
        let signing = self.config.evidence_signing_owner.as_ref().ok_or(
            CellSplitTargetHostRuntimeErrorV1::MissingExternalInput {
                input: "evidence-signing",
            },
        )?;
        let evaluator = self.config.future_window_evaluator_owner.as_ref().ok_or(
            CellSplitTargetHostRuntimeErrorV1::MissingExternalInput {
                input: "future-window-evaluator",
            },
        )?;
        let signature_receipt = signing
            .verify_signatures(&self.owner_request())
            .map_err(|error| self.external("evidence-signing", error))?;
        let verified = evaluator
            .independently_verify(&self.owner_request())
            .map_err(|error| self.external("future-window-evaluator", error))?;
        if verified.evaluator.verified_evidence_digest.is_empty()
            || verified.evaluator.verified_taskflow_digest.is_empty()
            || verified
                .evaluator
                .verified_ledger_frontier_digest
                .is_empty()
        {
            return Err(CellSplitTargetHostRuntimeErrorV1::ObserverSignatureMismatch);
        }
        self.record(
            CellSplitProductionLifecycleStepV1::IndependentlyVerified,
            signature_receipt,
        )?;
        self.packet.independent_evaluator = Some(verified.evaluator);
        Ok(())
    }

    pub(crate) fn advance_without_receipt(
        &mut self,
        step: CellSplitProductionLifecycleStepV1,
    ) -> Result<(), CellSplitTargetHostRuntimeErrorV1> {
        if self.step == Some(step) {
            return Ok(());
        }
        if self.step.is_some() {
            return Err(CellSplitTargetHostRuntimeErrorV1::InvalidTransition {
                expected: step,
                actual: self.step,
            });
        }
        self.step = Some(step);
        Ok(())
    }

    pub(crate) fn require_previous(
        &self,
        expected_previous: CellSplitProductionLifecycleStepV1,
    ) -> Result<(), CellSplitTargetHostRuntimeErrorV1> {
        if self.aborted {
            return Err(CellSplitTargetHostRuntimeErrorV1::Aborted {
                step: expected_previous,
            });
        }
        if self.step != Some(expected_previous) {
            return Err(CellSplitTargetHostRuntimeErrorV1::InvalidTransition {
                expected: expected_previous,
                actual: self.step,
            });
        }
        Ok(())
    }

    pub(crate) fn already_at(&self, step: CellSplitProductionLifecycleStepV1) -> bool {
        self.step
            .is_some_and(|current| current.ordinal() >= step.ordinal())
    }

    pub(crate) fn record(
        &mut self,
        step: CellSplitProductionLifecycleStepV1,
        receipt: ProductionOwnerOperationReceiptV1,
    ) -> Result<(), CellSplitTargetHostRuntimeErrorV1> {
        if self.already_at(step) {
            let existing = self.receipt(step)?;
            if existing == &receipt {
                return Ok(());
            }
            return Err(CellSplitTargetHostRuntimeErrorV1::IdempotencyConflict {
                operation_id: receipt.operation_id,
            });
        }
        let expected_previous = self.last_receipt_digest();
        if receipt.predecessor_receipt_digest != expected_previous {
            return Err(CellSplitTargetHostRuntimeErrorV1::PredecessorReceiptMissing { step });
        }
        if receipt.operation_id.is_empty()
            || receipt.receipt_digest.is_empty()
            || receipt.occurred_at_unix_nanos == 0
        {
            return Err(CellSplitTargetHostRuntimeErrorV1::ReceiptMismatch {
                step,
                detail: "identity/timestamp",
            });
        }
        if receipt.step != step {
            return Err(CellSplitTargetHostRuntimeErrorV1::ReceiptMismatch {
                step,
                detail: "step",
            });
        }
        if self.receipts.values().any(|existing| {
            existing.operation_id == receipt.operation_id
                || existing.receipt_digest == receipt.receipt_digest
        }) {
            return Err(CellSplitTargetHostRuntimeErrorV1::IdempotencyConflict {
                operation_id: receipt.operation_id,
            });
        }
        self.receipts.insert(step, receipt);
        self.step = Some(step);
        Ok(())
    }

    pub(crate) fn receipt(
        &self,
        step: CellSplitProductionLifecycleStepV1,
    ) -> Result<&ProductionOwnerOperationReceiptV1, CellSplitTargetHostRuntimeErrorV1> {
        self.receipts
            .get(&step)
            .ok_or(CellSplitTargetHostRuntimeErrorV1::PredecessorReceiptMissing { step })
    }

    pub(crate) fn last_receipt_digest(&self) -> String {
        self.receipts
            .values()
            .max_by_key(|receipt| receipt.step.ordinal())
            .map_or_else(
                || ZERO_DIGEST.to_string(),
                |receipt| receipt.receipt_digest.clone(),
            )
    }

    pub(crate) fn receipt_chain_digest(&self) -> String {
        let mut bytes = Vec::new();
        for receipt in self.receipts.values() {
            bytes.extend_from_slice(receipt.receipt_digest.as_bytes());
        }
        if bytes.is_empty() {
            ZERO_DIGEST.to_string()
        } else {
            let digest = sha2::Sha256::digest(bytes);
            format!("{digest:x}")
        }
    }

    pub(crate) fn external(
        &self,
        owner: &'static str,
        error: ProductionExternalErrorV1,
    ) -> CellSplitTargetHostRuntimeErrorV1 {
        CellSplitTargetHostRuntimeErrorV1::External {
            owner,
            detail: error.detail,
        }
    }
}

fn digest_shape(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}
