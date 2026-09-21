use std::collections::BTreeSet;
use std::collections::VecDeque;
use std::path::Path;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;
use serde::Serialize;
use zeroize::Zeroize as _;

use crate::backend::AuthenticatedRuntimeStatus;
use crate::backend::BackendAdapter;
use crate::error::ShellError;
use crate::journal::OperationJournal;
use crate::journal::OperationPhase;
use crate::journal::OperationRecord;
use crate::model::EndpointManifest;
use crate::model::OperationKey;
use crate::model::PlatformObservation;
use crate::model::PlatformPayload;
use crate::model::PlatformRequest;
use crate::model::SessionIncarnation;
use crate::model::TerminalStatus;
use crate::model::sha256_bytes;
use crate::model::sha256_hex;
use crate::platform::PermissionDecision;
use crate::platform::PlatformAdapter;
use crate::runtime::NativeShellRuntime;
use crate::security::KernelFinalUseGate;
use crate::security::TrustedKeySet;
use crate::security::now_unix_ms;
use crate::security::platform_final_use_binding;
use crate::updater::PendingUpdateStatus;
use crate::updater::SignedUpdateManifestV1;
use crate::updater::UpdateManager;
use crate::updater::activate_staged_update;
use crate::updater::digest_file;

const SUBJECT: &str = "qualification.operator";
const SIGNER: &str = "authority.qualification";
const QUALIFICATION_SCHEMA: &str = "hepta.native-packaged-fault-qualification.v1";

#[derive(Debug, Serialize)]
pub struct PackagedQualificationReceipt {
    pub schema: &'static str,
    pub platform: &'static str,
    pub architecture: &'static str,
    pub authenticated_view: bool,
    pub cross_generation_fenced: bool,
    pub permission_denial_no_dispatch: bool,
    pub grant_revocation_before_effect: bool,
    pub parent_death_ack_loss_reconciled: bool,
    pub updater_death_rolled_back: bool,
    pub rollback_failure_recovery_required: bool,
    pub effect_authority_granted: bool,
    pub activation_authority_granted: bool,
    pub release_authority_granted: bool,
}

#[derive(Debug)]
struct QualificationRoot {
    path: PathBuf,
}

impl QualificationRoot {
    fn create() -> Result<Self, ShellError> {
        let path = std::env::temp_dir().join(format!(
            "hepta-native-qualification-{}-{}",
            std::process::id(),
            now_unix_ms()?.max(1)
        ));
        std::fs::create_dir(&path)?;
        Ok(Self { path })
    }
}

impl Drop for QualificationRoot {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.path);
    }
}

#[derive(Debug)]
struct QualificationBackend {
    sessions: VecDeque<SessionIncarnation>,
}

impl BackendAdapter for QualificationBackend {
    fn connect(&mut self, _manifest: &EndpointManifest) -> Result<SessionIncarnation, ShellError> {
        self.sessions
            .pop_front()
            .ok_or_else(|| ShellError::Backend("qualification session queue is empty".to_owned()))
    }

    fn runtime_status(&mut self) -> Result<AuthenticatedRuntimeStatus, ShellError> {
        let value = serde_json::json!({
            "status": "ok",
            "state": {"runtime_snapshot_generation": 7}
        });
        let body = serde_json::to_vec(&value)?;
        Ok(AuthenticatedRuntimeStatus {
            value,
            body_digest: sha256_hex(body),
        })
    }

    fn close(&mut self, _session: &SessionIncarnation) -> Result<(), ShellError> {
        Ok(())
    }
}

#[derive(Debug)]
struct QualificationPlatformState {
    permission_allowed: bool,
    invoke_indeterminate: bool,
    reconcile_terminal: bool,
    invoke_calls: usize,
    reconcile_calls: usize,
}

impl Default for QualificationPlatformState {
    fn default() -> Self {
        Self {
            permission_allowed: true,
            invoke_indeterminate: false,
            reconcile_terminal: false,
            invoke_calls: 0,
            reconcile_calls: 0,
        }
    }
}

#[derive(Debug, Clone)]
struct QualificationPlatform {
    state: Arc<Mutex<QualificationPlatformState>>,
}

impl PlatformAdapter for QualificationPlatform {
    fn permission(&self, _payload: &PlatformPayload) -> Result<PermissionDecision, ShellError> {
        let state = self
            .state
            .lock()
            .map_err(|_| ShellError::State("qualification platform lock poisoned".to_owned()))?;
        Ok(PermissionDecision {
            allowed: state.permission_allowed,
            outcome_digest: sha256_hex(if state.permission_allowed {
                b"qualification.permission.allowed".as_slice()
            } else {
                b"qualification.permission.denied".as_slice()
            }),
        })
    }

    fn invoke(
        &mut self,
        _key: &OperationKey,
        _payload: &PlatformPayload,
    ) -> Result<PlatformObservation, ShellError> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| ShellError::State("qualification platform lock poisoned".to_owned()))?;
        state.invoke_calls += 1;
        if state.invoke_indeterminate {
            Ok(PlatformObservation::indeterminate())
        } else {
            Ok(PlatformObservation {
                terminal_status: Some(TerminalStatus::Succeeded),
                outcome_digest: Some(sha256_hex(b"qualification.effect.succeeded")),
            })
        }
    }

    fn reconcile(&mut self, _record: &OperationRecord) -> Result<PlatformObservation, ShellError> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| ShellError::State("qualification platform lock poisoned".to_owned()))?;
        state.reconcile_calls += 1;
        if state.reconcile_terminal {
            Ok(PlatformObservation {
                terminal_status: Some(TerminalStatus::Succeeded),
                outcome_digest: Some(sha256_hex(b"qualification.effect.reconciled")),
            })
        } else {
            Ok(PlatformObservation::indeterminate())
        }
    }
}

fn ephemeral_signing_key() -> Result<SigningKey, ShellError> {
    let mut material = [0_u8; 32];
    getrandom::fill(&mut material)
        .map_err(|error| ShellError::Security(format!("qualification CSPRNG: {error}")))?;
    let signing = SigningKey::from_bytes(&material);
    material.zeroize();
    Ok(signing)
}

fn random_nonce() -> Result<[u8; 32], ShellError> {
    let mut nonce = [0_u8; 32];
    getrandom::fill(&mut nonce)
        .map_err(|error| ShellError::Security(format!("qualification nonce CSPRNG: {error}")))?;
    Ok(nonce)
}

fn manifest() -> EndpointManifest {
    EndpointManifest {
        endpoint_id: "runtime.qualification".to_owned(),
        address: "127.0.0.1:7373".to_owned(),
        manifest_digest: sha256_hex(b"qualification.endpoint.manifest"),
        protocol_version: 1,
    }
}

fn session(id: &str, generation: u64) -> SessionIncarnation {
    SessionIncarnation {
        endpoint_id: "runtime.qualification".to_owned(),
        session_id: id.to_owned(),
        generation,
    }
}

fn authority_config_path(root: &Path) -> PathBuf {
    root.join("final-use-authority.json")
}

fn write_authority_config(
    root: &Path,
    signing: &SigningKey,
    head: &FinalUseRevocations,
) -> Result<PathBuf, ShellError> {
    let path = authority_config_path(root);
    let state_dir = root.join("final-use-state");
    std::fs::write(
        &path,
        serde_json::to_vec(&serde_json::json!({
            "schema": "hepta.native-final-use-authority.v1",
            "signer_id": SIGNER,
            "verifying_key_base64": STANDARD.encode(signing.verifying_key().to_bytes()),
            "state_dir": state_dir,
            "head": head,
        }))?,
    )?;
    Ok(path)
}

fn signed_grant(
    signing: &SigningKey,
    grant_id: &str,
    session: &SessionIncarnation,
    operation_id: &str,
    displayed_revision: u64,
    payload: &PlatformPayload,
) -> Result<SignedFinalUseGrant, ShellError> {
    let binding =
        platform_final_use_binding(SUBJECT, session, operation_id, displayed_revision, payload)?;
    let now = now_unix_ms()?;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: SIGNER.to_owned(),
        authority_epoch: 1,
        grant_id: grant_id.to_owned(),
        nonce: random_nonce()?,
        binding,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 60_000,
    };
    let signature = signing
        .sign(
            &grant
                .signing_bytes()
                .map_err(|error| ShellError::Security(error.to_string()))?,
        )
        .to_bytes()
        .to_vec();
    Ok(SignedFinalUseGrant { grant, signature })
}

fn request(
    signing: &SigningKey,
    grant_id: &str,
    session: &SessionIncarnation,
    operation_id: &str,
    displayed_revision: u64,
    payload: PlatformPayload,
) -> Result<PlatformRequest, ShellError> {
    Ok(PlatformRequest {
        subject_id: SUBJECT.to_owned(),
        operation_id: operation_id.to_owned(),
        displayed_revision,
        grant: signed_grant(
            signing,
            grant_id,
            session,
            operation_id,
            displayed_revision,
            &payload,
        )?,
        payload,
    })
}

fn wait_for_ready(path: &Path) -> Result<(), ShellError> {
    let deadline = Instant::now() + Duration::from_secs(15);
    while !path.exists() && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(10));
    }
    if path.exists() {
        Ok(())
    } else {
        Err(ShellError::State(format!(
            "qualification child did not reach durable cut: {}",
            path.display()
        )))
    }
}

fn kill_child(child: &mut Child) -> Result<(), ShellError> {
    child
        .kill()
        .map_err(|error| ShellError::State(format!("kill qualification child: {error}")))?;
    child
        .wait()
        .map_err(|error| ShellError::State(format!("wait qualification child: {error}")))?;
    Ok(())
}

fn write_trusted_keys(root: &Path, signing: &SigningKey) -> Result<PathBuf, ShellError> {
    let path = root.join("trusted-keys.json");
    std::fs::write(
        &path,
        serde_json::to_vec(&serde_json::json!({
            "schema": "hepta.native-trusted-keys.v1",
            "keys": {
                "qualification.release": STANDARD.encode(signing.verifying_key().to_bytes())
            }
        }))?,
    )?;
    Ok(path)
}

fn signed_update_manifest(
    signing: &SigningKey,
    package: &Path,
    target: &Path,
) -> Result<SignedUpdateManifestV1, ShellError> {
    let now = now_unix_ms()?;
    let mut manifest = SignedUpdateManifestV1 {
        schema: "hepta.native-update.v1".to_owned(),
        package_digest: digest_file(package)?,
        predecessor_digest: digest_file(target)?,
        evidence_digest: sha256_hex(b"qualification.packaged-fault-evidence"),
        platform: std::env::consts::OS.to_owned(),
        architecture: std::env::consts::ARCH.to_owned(),
        backend_protocol_version: 1,
        channel: "stable".to_owned(),
        selected_by: "qualification.reviewer".to_owned(),
        generator_principal: "qualification.builder".to_owned(),
        issued_unix_ms: now.saturating_sub(1_000),
        expires_unix_ms: now + 60_000,
        key_id: "qualification.release".to_owned(),
        signature_base64: String::new(),
    };
    manifest.signature_base64 = STANDARD.encode(
        signing
            .sign(manifest.signing_message().as_bytes())
            .to_bytes(),
    );
    Ok(manifest)
}

pub fn run_packaged_e2e() -> Result<PackagedQualificationReceipt, ShellError> {
    let root = QualificationRoot::create()?;
    let signing = ephemeral_signing_key()?;
    let head = FinalUseRevocations {
        authority_epoch: 1,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let authority_config = write_authority_config(&root.path, &signing, &head)?;
    let final_use = Arc::new(KernelFinalUseGate::open(authority_config.clone())?);
    let platform_state = Arc::new(Mutex::new(QualificationPlatformState::default()));
    let session_one = session("session.qualification.one", 1);
    let session_two = session("session.qualification.two", 2);
    let journal_path = root.path.join("operation-journal.json");

    let mut runtime = NativeShellRuntime::new(
        Box::new(QualificationBackend {
            sessions: vec![session_one.clone(), session_two.clone()].into(),
        }),
        Box::new(QualificationPlatform {
            state: Arc::clone(&platform_state),
        }),
        Some(Arc::clone(&final_use)),
        OperationJournal::open(&journal_path)?,
    );

    runtime.connect_runtime(&manifest())?;
    let (view_one, _) = runtime.refresh_runtime_view()?;
    let payload = PlatformPayload::CopyText {
        text: "qualification effect".to_owned(),
    };
    let first = runtime.request_platform_capability(request(
        &signing,
        "grant.qualification.one",
        &session_one,
        "operation.same-id",
        view_one.revision,
        payload.clone(),
    )?)?;
    if !first.terminal_observed {
        return Err(ShellError::State(
            "qualification first effect did not become terminal".to_owned(),
        ));
    }

    runtime.close()?;
    runtime.connect_runtime(&manifest())?;
    let (view_two, _) = runtime.refresh_runtime_view()?;
    let second = runtime.request_platform_capability(request(
        &signing,
        "grant.qualification.two",
        &session_two,
        "operation.same-id",
        view_two.revision,
        payload.clone(),
    )?)?;
    let cross_generation_fenced = second.terminal_observed
        && first.key.session_id != second.key.session_id
        && platform_state
            .lock()
            .map_err(|_| ShellError::State("qualification platform lock poisoned".to_owned()))?
            .invoke_calls
            == 2;
    if !cross_generation_fenced {
        return Err(ShellError::State(
            "cross-generation operation identity was reused".to_owned(),
        ));
    }

    {
        let mut state = platform_state
            .lock()
            .map_err(|_| ShellError::State("qualification platform lock poisoned".to_owned()))?;
        state.permission_allowed = false;
    }
    let denied = runtime.request_platform_capability(request(
        &signing,
        "grant.qualification.permission-denied",
        &session_two,
        "operation.permission-denied",
        view_two.revision,
        payload.clone(),
    )?)?;
    let permission_denial_no_dispatch = denied.terminal_status == Some(TerminalStatus::Rejected)
        && platform_state
            .lock()
            .map_err(|_| ShellError::State("qualification platform lock poisoned".to_owned()))?
            .invoke_calls
            == 2;
    if !permission_denial_no_dispatch {
        return Err(ShellError::State(
            "permission denial reached the platform effect boundary".to_owned(),
        ));
    }

    let revoke_binding = platform_final_use_binding(
        SUBJECT,
        &session_two,
        "operation.revoked",
        view_two.revision,
        &payload,
    )?;
    let revoked_grant = signed_grant(
        &signing,
        "grant.qualification.revoked",
        &session_two,
        "operation.revoked",
        view_two.revision,
        &payload,
    )?;
    let permit = final_use.claim_platform(&revoked_grant, revoke_binding)?;
    let mut revoked_ids = BTreeSet::new();
    revoked_ids.insert("grant.qualification.revoked".to_owned());
    write_authority_config(
        &root.path,
        &signing,
        &FinalUseRevocations {
            authority_epoch: 1,
            revision: 2,
            revoked_grant_ids: revoked_ids,
        },
    )?;
    let grant_revocation_before_effect = final_use.with_platform_use(permit, || ()).is_err();
    if !grant_revocation_before_effect {
        return Err(ShellError::State(
            "revoked final-use grant crossed the final effect boundary".to_owned(),
        ));
    }
    drop(runtime);
    drop(final_use);

    let crash_root = root.path.join("parent-death");
    std::fs::create_dir(&crash_root)?;
    let crash_ready = crash_root.join("ready");
    let mut crash_child = Command::new(
        std::env::current_exe()
            .map_err(|error| ShellError::State(format!("qualification current exe: {error}")))?,
    )
    .arg("--qualification-journal-child")
    .arg(&crash_root)
    .arg(&crash_ready)
    .spawn()
    .map_err(|error| ShellError::State(format!("spawn journal qualification child: {error}")))?;
    wait_for_ready(&crash_ready)?;
    kill_child(&mut crash_child)?;

    let crash_state = Arc::new(Mutex::new(QualificationPlatformState {
        reconcile_terminal: true,
        ..Default::default()
    }));
    let mut restarted = NativeShellRuntime::new(
        Box::new(QualificationBackend {
            sessions: vec![session("session.qualification.restarted", 42)].into(),
        }),
        Box::new(QualificationPlatform {
            state: Arc::clone(&crash_state),
        }),
        None,
        OperationJournal::open(crash_root.join("operations.json"))?,
    );
    restarted.connect_runtime(&manifest())?;
    let crash_observation = crash_state
        .lock()
        .map_err(|_| ShellError::State("qualification platform lock poisoned".to_owned()))?;
    let parent_death_ack_loss_reconciled = restarted
        .operation_history()
        .iter()
        .any(|receipt| receipt.terminal_observed)
        && crash_observation.invoke_calls == 0
        && crash_observation.reconcile_calls == 1;
    drop(crash_observation);
    if !parent_death_ack_loss_reconciled {
        return Err(ShellError::State(
            "possible dispatch was replayed after parent death".to_owned(),
        ));
    }
    drop(restarted);

    let update_signing = ephemeral_signing_key()?;
    let trusted_keys_path = write_trusted_keys(&root.path, &update_signing)?;
    let trusted_keys = TrustedKeySet::from_path(&trusted_keys_path)?;
    let update_root = root.path.join("updates");
    let manager = UpdateManager::new(trusted_keys, update_root.clone())?;
    let target = root.path.join("hepta-native-target");
    let candidate = root.path.join("hepta-native-candidate");
    std::fs::write(&target, b"qualification predecessor")?;
    std::fs::write(&candidate, b"qualification candidate")?;
    let predecessor_digest = digest_file(&target)?;
    let update_manifest = signed_update_manifest(&update_signing, &candidate, &target)?;
    manager.verify_and_stage(update_manifest, &candidate, 1)?;

    let updater_ready = root.path.join("updater-child.ready");
    let mut updater_child = Command::new(
        std::env::current_exe()
            .map_err(|error| ShellError::State(format!("qualification current exe: {error}")))?,
    )
    .arg("--qualification-updater-child")
    .arg(manager.pending_path())
    .arg(&trusted_keys_path)
    .arg(&target)
    .arg(&updater_ready)
    .spawn()
    .map_err(|error| ShellError::State(format!("spawn updater qualification child: {error}")))?;
    wait_for_ready(&updater_ready)?;
    if digest_file(&target)? == predecessor_digest {
        return Err(ShellError::State(
            "qualification updater child did not activate the candidate".to_owned(),
        ));
    }
    kill_child(&mut updater_child)?;

    let reopened = UpdateManager::new(
        TrustedKeySet::from_path(&trusted_keys_path)?,
        update_root,
    )?;
    let updater_death_rolled_back = reopened.recover_interrupted_activation()?
        && digest_file(&target)? == predecessor_digest
        && reopened
            .load_pending()?
            .is_some_and(|pending| pending.status == PendingUpdateStatus::RolledBack);
    if !updater_death_rolled_back {
        return Err(ShellError::State(
            "interrupted updater did not restore the admitted predecessor".to_owned(),
        ));
    }

    let recovery_target = root.path.join("hepta-native-recovery-target");
    let recovery_candidate = root.path.join("hepta-native-recovery-candidate");
    std::fs::write(&recovery_target, b"qualification recovery predecessor")?;
    std::fs::write(&recovery_candidate, b"qualification recovery candidate")?;
    let recovery_manifest =
        signed_update_manifest(&update_signing, &recovery_candidate, &recovery_target)?;
    reopened.verify_and_stage(recovery_manifest, &recovery_candidate, 1)?;
    activate_staged_update(
        &reopened.pending_path(),
        &TrustedKeySet::from_path(&trusted_keys_path)?,
        &recovery_target,
        1,
    )?;
    let pending = reopened
        .load_pending()?
        .ok_or_else(|| ShellError::Update("qualification pending update disappeared".to_owned()))?;
    let backup = pending
        .backup_path
        .ok_or_else(|| ShellError::Update("qualification backup path is missing".to_owned()))?;
    std::fs::remove_file(backup)?;
    let rollback_failure_recovery_required = reopened.rollback_unconfirmed().is_err()
        && reopened.load_pending()?.is_some_and(|pending| {
            pending.status == PendingUpdateStatus::RecoveryRequired
                && pending.recovery_reason.is_some()
        });
    if !rollback_failure_recovery_required {
        return Err(ShellError::State(
            "rollback failure did not persist recovery_required".to_owned(),
        ));
    }

    Ok(PackagedQualificationReceipt {
        schema: QUALIFICATION_SCHEMA,
        platform: std::env::consts::OS,
        architecture: std::env::consts::ARCH,
        authenticated_view: true,
        cross_generation_fenced,
        permission_denial_no_dispatch,
        grant_revocation_before_effect,
        parent_death_ack_loss_reconciled,
        updater_death_rolled_back,
        rollback_failure_recovery_required,
        effect_authority_granted: false,
        activation_authority_granted: false,
        release_authority_granted: false,
    })
}

pub fn run_journal_child(root: &Path, ready: &Path) -> Result<(), ShellError> {
    if !root.is_absolute() || !ready.is_absolute() {
        return Err(ShellError::InvalidInput(
            "qualification child paths must be absolute".to_owned(),
        ));
    }
    let payload = PlatformPayload::CopyText {
        text: "possibly dispatched before parent death".to_owned(),
    };
    let mut journal = OperationJournal::open(root.join("operations.json"))?;
    journal.upsert(OperationRecord {
        endpoint_id: "runtime.qualification".to_owned(),
        key: OperationKey {
            session_id: "session.qualification.crashed".to_owned(),
            session_generation: 41,
            operation_id: "operation.ack-loss".to_owned(),
        },
        subject_id: SUBJECT.to_owned(),
        displayed_revision: 1,
        action: payload.action(),
        payload_digest: payload.digest()?,
        binding_digest: sha256_hex(b"qualification.binding"),
        grant_digest: sha256_hex(b"qualification.grant"),
        phase: OperationPhase::Invoking,
        terminal_status: None,
        outcome_digest: None,
    })?;
    std::fs::write(ready, b"invoking-durable")?;
    loop {
        std::thread::park();
    }
}

pub fn run_updater_child(
    pending: &Path,
    trusted_keys: &Path,
    target: &Path,
    ready: &Path,
) -> Result<(), ShellError> {
    if !pending.is_absolute()
        || !trusted_keys.is_absolute()
        || !target.is_absolute()
        || !ready.is_absolute()
    {
        return Err(ShellError::InvalidInput(
            "qualification updater paths must be absolute".to_owned(),
        ));
    }
    let keys = TrustedKeySet::from_path(trusted_keys)?;
    activate_staged_update(pending, &keys, target, 1)?;
    std::fs::write(ready, b"activated-unconfirmed")?;
    loop {
        std::thread::park();
    }
}
