//! Headless, read-only console admission for the Robrix/Makepad frontend.
//! This facade intentionally exposes no platform effect or updater entrypoints.
use std::path::{Path, PathBuf};

use serde::Deserialize;

use crate::{
    backend::LoopbackGatewayBackend,
    error::ShellError,
    journal::{OperationJournal, OperationRecord},
    model::{
        EndpointManifest, OperationKey, PlatformObservation, PlatformPayload, PresentationState,
        SessionIncarnation,
    },
    platform::{PermissionDecision, PlatformAdapter},
    private_state::PrivateStateRoot,
    runtime::{NativeShellRuntime, RuntimeConnectionFailure},
    security::{SignedEndpointManifestV1, TrustedKeySet},
    session_store::GatewayCredentialStore,
};

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ConsoleConfig {
    pub schema: String,
    pub endpoint_manifest: PathBuf,
    pub trusted_keys: PathBuf,
    /// Dedicated read-only console state; never an installed updater directory.
    pub state_dir: PathBuf,
}

impl ConsoleConfig {
    pub fn load(path: &Path) -> Result<Self, ShellError> {
        if !path.is_absolute() {
            return Err(ShellError::InvalidInput(
                "console config path must be absolute".into(),
            ));
        }
        let config: Self = crate::file_input::read_json_file(path, 64 * 1024)?;
        config.validate()?;
        Ok(config)
    }

    fn validate(&self) -> Result<(), ShellError> {
        if self.schema != "hepta.robrix-read-console.v1"
            || !self.endpoint_manifest.is_absolute()
            || !self.trusted_keys.is_absolute()
            || !self.state_dir.is_absolute()
        {
            return Err(ShellError::InvalidInput("expected hepta.robrix-read-console.v1 and absolute endpoint, trust and dedicated state paths".into()));
        }
        Ok(())
    }
}

#[derive(Debug, thiserror::Error)]
pub enum ConsoleError {
    #[error("console connection failed: {0}")]
    Connection(ShellError),
    #[error("console initialization failed: {0}")]
    Initialization(#[from] ShellError),
}

#[derive(Debug, Clone)]
pub struct ConsoleSnapshot {
    pub session: SessionIncarnation,
    pub presentation: PresentationState,
    pub status: serde_json::Value,
}

pub struct ConsoleRuntime {
    runtime: NativeShellRuntime,
}

impl ConsoleRuntime {
    pub fn open(config: ConsoleConfig) -> Result<Self, ConsoleError> {
        config.validate()?;
        let keys = TrustedKeySet::from_path(&config.trusted_keys)?;
        let signed: SignedEndpointManifestV1 =
            crate::file_input::read_json_file(&config.endpoint_manifest, 64 * 1024)?;
        let verified = signed.verify(&keys)?;
        let address = verified.manifest.address.parse().map_err(|error| {
            ShellError::InvalidInput(format!("console endpoint address: {error}"))
        })?;
        let token = GatewayCredentialStore::default().load(&verified.gateway_credential_account)?;
        let backend = LoopbackGatewayBackend::new(address, token)?;
        let _root = PrivateStateRoot::open(config.state_dir.clone())?;
        let journal = OperationJournal::open(config.state_dir.join("read-console-journal.json"))?;
        let runtime =
            NativeShellRuntime::new(Box::new(backend), Box::new(ReadOnlyPlatform), None, journal);
        Self::connect(runtime, &verified.manifest)
    }

    /// Admit an existing owner with the same connection provenance as the legacy
    /// frontend. State recovery failures must never be treated as network outages.
    pub fn connect(
        mut runtime: NativeShellRuntime,
        manifest: &EndpointManifest,
    ) -> Result<Self, ConsoleError> {
        if !runtime.pending_operations().is_empty() {
            return Err(ShellError::State(
                "read-only console cannot take ownership of pending platform effects".into(),
            )
            .into());
        }
        runtime
            .connect_runtime_classified(manifest)
            .map_err(|error| match error {
                RuntimeConnectionFailure::Backend(error) => ConsoleError::Connection(error),
                RuntimeConnectionFailure::State(error) => ConsoleError::Initialization(error),
            })?;
        Ok(Self { runtime })
    }

    pub fn refresh(&mut self) -> Result<ConsoleSnapshot, ShellError> {
        let (presentation, status) = self.runtime.refresh_runtime_view()?;
        let session = self
            .runtime
            .session()
            .cloned()
            .ok_or_else(|| ShellError::State("console session disappeared".into()))?;
        Ok(ConsoleSnapshot {
            session,
            presentation,
            status,
        })
    }

    pub fn close(&mut self) -> Result<(), ShellError> {
        self.runtime.close()
    }
}

/// This surface can observe an authenticated runtime, but cannot invoke or
/// reconcile any OS effect. Mutations require the separately ported confirmation UI.
struct ReadOnlyPlatform;
impl PlatformAdapter for ReadOnlyPlatform {
    fn permission(&self, _payload: &PlatformPayload) -> Result<PermissionDecision, ShellError> {
        Err(ShellError::Security(
            "read-only Robrix console has no platform authority".into(),
        ))
    }
    fn invoke(
        &mut self,
        _key: &OperationKey,
        _payload: &PlatformPayload,
    ) -> Result<PlatformObservation, ShellError> {
        Err(ShellError::Security(
            "read-only Robrix console cannot invoke platform effects".into(),
        ))
    }
    fn reconcile(&mut self, _record: &OperationRecord) -> Result<PlatformObservation, ShellError> {
        Err(ShellError::State(
            "read-only Robrix console cannot reconcile platform effects".into(),
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::backend::{AuthenticatedRuntimeStatus, BackendAdapter};
    use std::collections::VecDeque;

    struct FixtureBackend {
        generations: VecDeque<u64>,
        connection_error: bool,
    }
    impl BackendAdapter for FixtureBackend {
        fn connect(
            &mut self,
            manifest: &EndpointManifest,
        ) -> Result<SessionIncarnation, ShellError> {
            if self.connection_error {
                return Err(std::io::Error::from(std::io::ErrorKind::ConnectionRefused).into());
            }
            Ok(SessionIncarnation {
                endpoint_id: manifest.endpoint_id.clone(),
                session_id: "fixture.console".into(),
                generation: 1,
            })
        }
        fn runtime_status(&mut self) -> Result<AuthenticatedRuntimeStatus, ShellError> {
            let generation = self.generations.pop_front().unwrap();
            Ok(AuthenticatedRuntimeStatus {
                value: serde_json::json!({"state":{"runtime_snapshot_generation":generation}}),
                body_digest: "a".repeat(64),
            })
        }
        fn close(&mut self, _session: &SessionIncarnation) -> Result<(), ShellError> {
            Ok(())
        }
    }
    fn manifest() -> EndpointManifest {
        EndpointManifest {
            endpoint_id: "fixture.endpoint".into(),
            address: "127.0.0.1:4000".into(),
            manifest_digest: "b".repeat(64),
            protocol_version: 1,
        }
    }
    fn runtime(path: &Path, connection_error: bool) -> NativeShellRuntime {
        NativeShellRuntime::new(
            Box::new(FixtureBackend {
                generations: VecDeque::from([7, 6]),
                connection_error,
            }),
            Box::new(ReadOnlyPlatform),
            None,
            OperationJournal::open(path.join("journal.json")).unwrap(),
        )
    }
    #[test]
    fn observed_status_preserves_owner_fences() {
        let dir = crate::private_state_test_support::private_tempdir();
        let mut console = ConsoleRuntime::connect(runtime(dir.path(), false), &manifest()).unwrap();
        let first = console.refresh().unwrap();
        assert_eq!(
            first.session,
            SessionIncarnation {
                endpoint_id: "fixture.endpoint".into(),
                session_id: "fixture.console".into(),
                generation: 1
            }
        );
        assert_eq!(first.presentation.generation, 7);
        assert!(
            console.refresh().is_err(),
            "regressed backend generation must be rejected"
        );
        assert!(
            console.runtime.view().is_none(),
            "failed observation must invalidate authority"
        );
        console.close().unwrap();
    }
    #[test]
    fn only_backend_connection_errors_have_connection_provenance() {
        let dir = crate::private_state_test_support::private_tempdir();
        assert!(matches!(
            ConsoleRuntime::connect(runtime(dir.path(), true), &manifest()),
            Err(ConsoleError::Connection(ShellError::Io(_)))
        ));
        let mut invalid = manifest();
        invalid.manifest_digest.clear();
        assert!(matches!(
            ConsoleRuntime::connect(runtime(dir.path(), false), &invalid),
            Err(ConsoleError::Initialization(ShellError::InvalidInput(_)))
        ));
    }
    #[test]
    fn genesis_preserves_raw_observation_separately_from_presentation_generation() {
        let dir = crate::private_state_test_support::private_tempdir();
        let runtime = NativeShellRuntime::new(
            Box::new(FixtureBackend {
                generations: VecDeque::from([0]),
                connection_error: false,
            }),
            Box::new(ReadOnlyPlatform),
            None,
            OperationJournal::open(dir.path().join("journal.json")).unwrap(),
        );
        let mut console = ConsoleRuntime::connect(runtime, &manifest()).unwrap();
        let snapshot = console.refresh().unwrap();
        assert_eq!(
            snapshot
                .status
                .pointer("/state/runtime_snapshot_generation"),
            Some(&serde_json::json!(0))
        );
        assert_eq!(snapshot.presentation.generation, 1);
    }
    #[test]
    fn pending_effects_refuse_before_backend_or_platform_entry_and_leave_journal_unchanged() {
        use crate::journal::OperationPhase;
        struct MustNotConnect;
        impl BackendAdapter for MustNotConnect {
            fn connect(&mut self, _: &EndpointManifest) -> Result<SessionIncarnation, ShellError> {
                panic!("backend admission must not occur")
            }
            fn runtime_status(&mut self) -> Result<AuthenticatedRuntimeStatus, ShellError> {
                panic!("observation must not occur")
            }
            fn close(&mut self, _: &SessionIncarnation) -> Result<(), ShellError> {
                panic!("no backend session exists")
            }
        }
        struct MustNotReconcile;
        impl PlatformAdapter for MustNotReconcile {
            fn permission(&self, _: &PlatformPayload) -> Result<PermissionDecision, ShellError> {
                panic!("platform permission must not occur")
            }
            fn invoke(
                &mut self,
                _: &OperationKey,
                _: &PlatformPayload,
            ) -> Result<PlatformObservation, ShellError> {
                panic!("platform effect must not occur")
            }
            fn reconcile(
                &mut self,
                _: &OperationRecord,
            ) -> Result<PlatformObservation, ShellError> {
                panic!("platform reconciliation must not occur")
            }
        }
        fn files(path: &Path) -> std::collections::BTreeMap<PathBuf, Vec<u8>> {
            std::fs::read_dir(path)
                .unwrap()
                .map(|entry| entry.unwrap().path())
                .filter(|path| path.is_file())
                .map(|path| {
                    let bytes = std::fs::read(&path).unwrap();
                    (path, bytes)
                })
                .collect()
        }
        for phase in [
            OperationPhase::Prepared,
            OperationPhase::Invoking,
            OperationPhase::Indeterminate,
        ] {
            let dir = crate::private_state_test_support::private_tempdir();
            let mut journal = OperationJournal::open(dir.path().join("journal.json")).unwrap();
            journal
                .upsert(OperationRecord {
                    endpoint_id: "fixture.endpoint".into(),
                    key: OperationKey {
                        session_id: "prior.session".into(),
                        session_generation: 1,
                        operation_id: "prior.operation".into(),
                    },
                    subject_id: "prior.principal".into(),
                    displayed_revision: 1,
                    action: crate::model::PlatformAction::CopyText,
                    payload_digest: "a".repeat(64),
                    binding_digest: "b".repeat(64),
                    grant_digest: "c".repeat(64),
                    phase,
                    terminal_status: None,
                    outcome_digest: None,
                })
                .unwrap();
            let before = files(dir.path());
            let runtime = NativeShellRuntime::new(
                Box::new(MustNotConnect),
                Box::new(MustNotReconcile),
                None,
                journal,
            );
            assert!(
                matches!(ConsoleRuntime::connect(runtime, &manifest()), Err(ConsoleError::Initialization(ShellError::State(message))) if message.contains("pending platform effects"))
            );
            assert_eq!(files(dir.path()), before);
        }
    }

    #[test]
    fn unprovisioned_config_has_no_defaults_or_mutation_flags() {
        assert!(
            serde_json::from_value::<ConsoleConfig>(
                serde_json::json!({"schema":"hepta.robrix-read-console.v1"})
            )
            .is_err()
        );
        assert!(
            ConsoleConfig {
                schema: "wrong".into(),
                endpoint_manifest: "/endpoint".into(),
                trusted_keys: "/trust".into(),
                state_dir: "/state".into()
            }
            .validate()
            .is_err()
        );
        assert!(serde_json::from_value::<ConsoleConfig>(serde_json::json!({"schema":"hepta.robrix-read-console.v1","endpoint_manifest":"/endpoint","trusted_keys":"/trust","state_dir":"/state","allow_clipboard":true})).is_err());
    }
}
