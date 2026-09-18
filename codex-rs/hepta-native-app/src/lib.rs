//! Hepta native desktop application shell.
//!
//! This crate owns presentation/session state only. Agentd remains the local
//! runtime owner, kernel authority remains the only final-use verifier, and OS
//! adapters cannot mint the `VerifiedUseToken` they consume.

#![forbid(unsafe_code)]

pub mod backend;
pub mod persistence;
pub mod platform;
pub mod runtime;
pub mod update;
pub mod ui;

pub use backend::AgentdBackend;
pub use persistence::KeyringOperationStore;
pub use platform::SecurePlatformAdapter;
pub use runtime::BackendPort;
pub use runtime::BackendSession;
pub use runtime::BackendView;
pub use runtime::EndpointManifest;
pub use runtime::NativeError;
pub use runtime::NativePresentationState;
pub use runtime::NativeSession;
pub use runtime::NativeShellRuntime;
pub use runtime::OperationRecord;
pub use runtime::OperationReceipt;
pub use runtime::OperationStatus;
pub use runtime::OperationStore;
pub use runtime::PlatformAction;
pub use runtime::PlatformActionKind;
pub use runtime::PlatformEffectPort;
pub use runtime::PlatformObservation;
pub use runtime::PlatformRequest;
pub use runtime::SessionFence;
pub use update::SignedUpdater;
pub use ui::run_native_ui;
