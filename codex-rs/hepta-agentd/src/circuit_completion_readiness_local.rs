//! Bind completion readiness to the same sealed local C capability.
//! The original Material/D/S checks remain mandatory. This creates no
//! connection, permit, request counter or new lifetime.

use std::sync::Mutex;

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;

use super::super::OriginalCircuitEvaluatedLearningReadContextV1;
use super::super::OriginalCircuitLearningReadClientV1;
use super::super::profile::ReadProfile;
use super::Error;
use super::OriginalCircuitCompletionReadinessClientV1;
use super::now;
use super::original;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;

impl OriginalCircuitCompletionReadinessClientV1 {
    pub(crate) fn bind_original_evaluated_local_read(
        client: &OriginalCircuitLearningReadClientV1,
        material: &OriginalCellQ24MaterialReceiptConfigV1,
        dataset: &OriginalCellQ24MaterialCommandReceiptV1,
        selection: &OriginalCircuitEvaluatedSelectionReceiptV1,
    ) -> Result<Self, Error> {
        OriginalCircuitLearningReadClientV1::require_original_local_evaluated_next_use(
            client, selection,
        )?;
        let (scope, verifier, _) = selection.original_context().receipt_configuration();
        if scope != material.scope
            || verifier.trust_digest() != material.verifier.trust_digest()
            || verifier.scope_digest() != material.verifier.scope_digest()
            || verifier.objective_digest() != material.verifier.objective_digest()
        {
            return Err(Error::Binding(
                "same original evaluated Material readiness context",
            ));
        }
        let context = ReadProfile::Evaluated(
            OriginalCircuitEvaluatedLearningReadContextV1::for_original_next_use(
                selection.clone(),
            )?,
        );
        let started_at = now()?;
        let binding = context.binding(started_at)?;
        if context.mode()? != original::Mode::NextUse {
            return Err(Error::Binding(
                "local readiness requires original Selection",
            ));
        }
        let initial = LearningIterationCoordinatorV1::new(
            context.prefix().request.clone(),
            context.prefix().owners.clone(),
        )?;
        let mut original_dataset = context.prefix().clone();
        original_dataset.head_digest = original_dataset.receipts[2].predecessor;
        original_dataset.receipts.truncate(2);
        if initial.snapshot() != &material.initial || &original_dataset != dataset.snapshot() {
            return Err(Error::Binding(
                "same initial and original Dataset before readiness",
            ));
        }
        let fresh = OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(
            dataset, material,
        )
        .map_err(|_| Error::Binding("same original Material readiness context"))?;
        if fresh < started_at || context.binding(fresh)? != binding {
            return Err(Error::Binding("original readiness binding and clock"));
        }
        OriginalCircuitLearningReadClientV1::require_original_local_evaluated_next_use(
            client, selection,
        )?;
        let local = client
            .local
            .as_ref()
            .ok_or(Error::Binding("same local NextUse readiness capability"))?
            .clone();
        Ok(Self {
            context,
            binding,
            channel: Mutex::new(None),
            retained: Mutex::new(None),
            local: Some(local),
        })
    }
}
