//! Failure-only observations for the real Evaluation service fixture.
//! Capture does no I/O. The original service returns before flush writes stderr.
//! Only enum categories, discriminants and static binding reasons are retained.
//! No request, response, receipt, payload or signature body is formatted.

use std::cell::Cell;
use std::cell::RefCell;
use std::time::Duration;

use codex_hepta_types::Digest32;

use super::Error;
use super::wire;
use crate::OriginalCellEvaluationPanelErrorV1 as PanelError;
use crate::OriginalCellEvaluationQualificationErrorV1 as QualificationError;

struct Failure {
    request_id: u64,
    action: wire::Action,
    binding: Digest32,
    elapsed: Duration,
    error: String,
}

std::thread_local! {
    static REQUEST_ID: Cell<u64> = const { Cell::new(0) };
    static FAILURE: RefCell<Option<Failure>> = const { RefCell::new(None) };
}

pub(super) fn begin_request(request_id: u64) {
    REQUEST_ID.set(request_id);
}

pub(super) fn capture(action: wire::Action, binding: Digest32, elapsed: Duration, error: &Error) {
    let error = match error {
        Error::Panel(error) => match error {
            PanelError::Binding(reason) => format!("Panel::Binding({reason})"),
            PanelError::CommitUncertain => "Panel::CommitUncertain".into(),
            PanelError::Qualification(error) => {
                format!("Panel::Qualification::{}", qualification_category(error))
            }
            PanelError::Cell(error) => {
                format!("Panel::Cell::{:?}", std::mem::discriminant(error))
            }
            PanelError::Cohort(crate::OriginalCircuitEvaluationProviderErrorV1::Binding(
                reason,
            )) => format!("Panel::Cohort::Binding({reason})"),
            PanelError::Cohort(error) => {
                format!("Panel::Cohort::{:?}", std::mem::discriminant(error))
            }
        },
        Error::Qualification(error) => {
            format!("Qualification::{}", qualification_category(error))
        }
        Error::PredecessorUnavailable => "PredecessorUnavailable".into(),
        _ => return,
    };
    let request_id = REQUEST_ID.get();
    if request_id == 0 {
        return;
    }
    FAILURE.with(|slot| {
        let mut slot = slot.borrow_mut();
        if slot.is_none() {
            *slot = Some(Failure {
                request_id,
                action,
                binding,
                elapsed,
                error,
            });
        }
    });
}

pub(super) fn flush() {
    REQUEST_ID.set(0);
    let failure = FAILURE.with(RefCell::take);
    if let Some(Failure {
        request_id,
        action,
        binding,
        elapsed,
        error,
    }) = failure
    {
        eprintln!(
            "ORIGINAL_EVALUATION_PREDECESSOR_FAILURE request_id={request_id} action={action:?} binding={binding} completion_elapsed={elapsed:?} original_error={error}"
        );
    }
}

fn qualification_category(error: &QualificationError) -> String {
    match error {
        QualificationError::Binding(reason) => format!("Binding({reason})"),
        QualificationError::Pending => "Pending".into(),
        QualificationError::CommitUncertain => "CommitUncertain".into(),
        QualificationError::Owner(error) => {
            format!("Owner::{:?}", std::mem::discriminant(error))
        }
        QualificationError::Store(error) => {
            format!("Store::{:?}", std::mem::discriminant(error))
        }
        QualificationError::Cell(error) => {
            format!("Cell::{:?}", std::mem::discriminant(error))
        }
        QualificationError::Product(error) => {
            format!("Product::{:?}", std::mem::discriminant(error))
        }
        QualificationError::Iteration(error) => {
            format!("Iteration::{:?}", std::mem::discriminant(error))
        }
        QualificationError::Trainer(crate::LearningIterationRuntimeErrorV1::OwnerUnavailable(
            reason,
        )) => format!("Trainer::OwnerUnavailable({reason})"),
        QualificationError::Trainer(error) => {
            format!("Trainer::{:?}", std::mem::discriminant(error))
        }
        QualificationError::Evidence(error) => {
            format!("Evidence::{:?}", std::mem::discriminant(error))
        }
    }
}
