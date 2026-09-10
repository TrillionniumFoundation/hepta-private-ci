#![forbid(unsafe_code)]

mod child;
#[cfg(test)]
mod child_tests;
mod closure;
mod digest;
mod driver;
#[cfg(test)]
mod driver_tests;
mod durable;
#[cfg(test)]
mod durable_tests;
mod importer;
#[cfg(test)]
mod importer_tests;
#[cfg(test)]
mod lane_e_closure_tests;
mod loopback;
#[cfg(test)]
mod loopback_tests;
mod observer;
#[cfg(test)]
mod observer_tests;
mod oracle;
#[cfg(test)]
mod oracle_tests;
mod product_database;
mod product_receipts;
#[cfg(test)]
mod product_receipts_tests;
mod report;
#[cfg(test)]
mod report_tests;
mod request;
#[cfg(test)]
mod request_tests;
mod runtime;
#[cfg(test)]
mod runtime_tests;
mod sealer;
#[cfg(test)]
mod sealer_tests;
mod semantic_verifier;
#[cfg(test)]
mod semantic_verifier_tests;
mod session;
#[cfg(test)]
mod session_tests;
#[cfg(test)]
mod test_support;
mod transport;
#[cfg(test)]
mod transport_tests;
mod trial;
#[cfg(test)]
mod trial_tests;
#[cfg(test)]
#[path = "value_learning_tests.rs"]
mod value_learning_tests;
mod verification_primitives;

#[derive(Debug, thiserror::Error)]
pub enum QualificationError {
    #[error("invalid qualification input: {0}")]
    Invalid(String),
    #[error("failed to serialize qualification evidence: {0}")]
    Serialization(String),
    #[error("qualification evidence I/O failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("qualification evidence database failed: {0}")]
    Database(#[from] sqlx::Error),
    #[error("invalid observer state: {0}")]
    State(String),
}

pub use child::ChildOutcome;
pub use child::ProductChild;
pub use closure::QualificationClosure;
pub use closure::QualificationClosureOutcome;
pub use driver::AppServerDriver;
pub use driver::McpDriver;
pub use driver::QualificationDriverRun;
pub use importer::ImportCheckpoint;
pub use importer::ImportFailure;
pub use loopback::HttpAuditRecord;
pub use loopback::LoopbackHandle;
pub use observer::CompletedPreSend;
pub use observer::DurablePreSendObserver;
pub use observer::DurablePreSendToken;
pub use oracle::FrozenOracle;
pub use product_receipts::ProductReceiptSet;
pub use report::QualificationManifest;
pub use report::QualificationReport;
pub use report::ReportFailure;
pub use report::SemanticSampleReport;
pub use request::Surface;
pub use runtime::FrozenProductBinary;
pub use runtime::QualificationRuntimeLayout;
pub use runtime::SurfaceRuntimeLayout;
pub use sealer::TerminalSeal;
pub use sealer::TerminalStatus;
pub use semantic_verifier::SemanticVerifier;
pub use semantic_verifier::VerifiedSemanticReceipt;
pub use trial::QualificationTrial;
pub use trial::QualificationTrialOutcome;
