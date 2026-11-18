//! Fixed, value-free error stages for the complete historical task reader.
//! The private parent module is the only caller; no task or error data is accepted.

pub(super) enum HistoricalTaskDiagnosticStage {
    RecipientAction,
    Ledger,
    RunStart,
    SourceCell,
    Handoff,
    SourceObservation,
    RunStartPublisher,
    RunStartDeployment,
    RunStartObservation,
    LedgerObservation,
    RunStartDigest,
    LedgerDigest,
    PublicationProjection,
    PublicationValidation,
}

pub(super) fn log_historical_task_diagnostic(stage: HistoricalTaskDiagnosticStage) {
    let bytes: &[u8] = match stage {
        HistoricalTaskDiagnosticStage::RecipientAction => {
            b"root_stage=historical_task.recipient_action\n"
        }
        HistoricalTaskDiagnosticStage::Ledger => b"root_stage=historical_task.ledger\n",
        HistoricalTaskDiagnosticStage::RunStart => b"root_stage=historical_task.run_start\n",
        HistoricalTaskDiagnosticStage::SourceCell => b"root_stage=historical_task.source_cell\n",
        HistoricalTaskDiagnosticStage::Handoff => b"root_stage=historical_task.handoff\n",
        HistoricalTaskDiagnosticStage::SourceObservation => {
            b"root_stage=historical_task.source_observation\n"
        }
        HistoricalTaskDiagnosticStage::RunStartPublisher => {
            b"root_stage=historical_task.run_start_publisher\n"
        }
        HistoricalTaskDiagnosticStage::RunStartDeployment => {
            b"root_stage=historical_task.run_start_deployment\n"
        }
        HistoricalTaskDiagnosticStage::RunStartObservation => {
            b"root_stage=historical_task.run_start_observation\n"
        }
        HistoricalTaskDiagnosticStage::LedgerObservation => {
            b"root_stage=historical_task.ledger_observation\n"
        }
        HistoricalTaskDiagnosticStage::RunStartDigest => {
            b"root_stage=historical_task.run_start_digest\n"
        }
        HistoricalTaskDiagnosticStage::LedgerDigest => {
            b"root_stage=historical_task.ledger_digest\n"
        }
        HistoricalTaskDiagnosticStage::PublicationProjection => {
            b"root_stage=historical_task.publication_projection\n"
        }
        HistoricalTaskDiagnosticStage::PublicationValidation => {
            b"root_stage=historical_task.publication_validation\n"
        }
    };
    let _ = std::io::Write::write_all(&mut std::io::stderr(), bytes);
}
