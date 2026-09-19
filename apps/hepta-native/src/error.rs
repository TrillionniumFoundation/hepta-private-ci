use thiserror::Error;

#[derive(Debug, Error)]
pub enum ShellError {
    #[error("invalid native-shell input: {0}")]
    InvalidInput(String),
    #[error("native-shell state violation: {0}")]
    State(String),
    #[error("native-shell security verification failed: {0}")]
    Security(String),
    #[error("native platform adapter failed: {0}")]
    Platform(String),
    #[error("native backend adapter failed: {0}")]
    Backend(String),
    #[error("native updater failed: {0}")]
    Update(String),
    #[error("native operation remains indeterminate: {0}")]
    Indeterminate(String),
    #[error("native-shell I/O failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("native-shell JSON failed: {0}")]
    Json(#[from] serde_json::Error),
}
