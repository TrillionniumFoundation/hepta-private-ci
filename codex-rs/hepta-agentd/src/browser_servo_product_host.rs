use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Duration;

use codex_hepta_contracts::{
    FinalUseAuthority, FinalUseBinding, FinalUseRevocations, SignedFinalUseGrant,
};
use serde::Deserialize;
use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::browser_revocation_feed::BrowserRevocationFeed;
use crate::browser_servo_admission_transport::AdmissionValidatingTransport;
use crate::browser_servo_product::{
    BrowserFinalUseInvocation, BrowserServoCall, BrowserServoError,
    BrowserServoHostConfig, BrowserServoMethod, BrowserServoPort,
    BrowserServoProcessConfig, ChildBrowserTransport,
};

const CONFIG_SCHEMA: &str = "hepta.agentd.browser-service.v1";
const CONFIG_VERSION: u64 = 1;
const MAX_NODE_BYTES: usize = 256 * 1024 * 1024;
const MAX_CLOSURE_FILES: usize = 256;
const MAX_CLOSURE_FILE_BYTES: u64 = 64 * 1024 * 1024;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ArtifactBinding {
    path: PathBuf,
    sha256: String,
    max_bytes: u64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProductHostConfig {
    schema: String,
    version: u64,
    node_sha256: String,
    service_closure: Vec<ArtifactBinding>,
    browser: BrowserServoHostConfig,
}

#[derive(Clone, Copy, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProductMethod {
    OpenProfile,
    AdmitEffectGrant,
    ObservePage,
    NavigateOrAct,
    ReconcileOperation,
    ReconcilePersistedOperation,
    CloseProfile,
}

impl ProductMethod {
    fn module_method(self) -> BrowserServoMethod {
        match self {
            Self::OpenProfile => BrowserServoMethod::OpenProfile,
            Self::AdmitEffectGrant => BrowserServoMethod::AdmitEffectGrant,
            Self::ObservePage => BrowserServoMethod::ObservePage,
            Self::NavigateOrAct => BrowserServoMethod::NavigateOrAct,
            Self::ReconcileOperation => BrowserServoMethod::ReconcileOperation,
            Self::ReconcilePersistedOperation => {
                BrowserServoMethod::ReconcilePersistedOperation
            }
            Self::CloseProfile => BrowserServoMethod::CloseProfile,
        }
    }

    fn requires_final_use(self) -> bool {
        matches!(self, Self::NavigateOrAct)
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProductCall {
    pub request_id: Option<String>,
    method: ProductMethod,
    input: Value,
    signed_grant: Option<SignedFinalUseGrant>,
    binding: Option<FinalUseBinding>,
}

type ProductPort =
    BrowserServoPort<AdmissionValidatingTransport<ChildBrowserTransport>>;

pub struct PersistentBrowserProduct {
    authority: FinalUseAuthority,
    process: BrowserServoProcessConfig,
    frame_timeout: Duration,
    port: Option<ProductPort>,
    revocation_feed: BrowserRevocationFeed,
}

impl PersistentBrowserProduct {
    pub fn from_config(config: ProductHostConfig) -> Result<Self, BrowserServoError> {
        if config.schema != CONFIG_SCHEMA || config.version != CONFIG_VERSION {
            return Err(BrowserServoError::Invalid(
                "Browser product config schema/version is unsupported".into(),
            ));
        }
        verify_file_digest(
            &config.browser.node_path,
            parse_digest(&config.node_sha256, "node_sha256")?,
            MAX_NODE_BYTES,
        )?;
        verify_service_closure(
            &config.browser.service_path,
            &config.service_closure,
        )?;

        let browser = config.browser;
        if browser.authority_epoch == 0 || browser.revocation_revision == 0 {
            return Err(BrowserServoError::Invalid(
                "Browser authority epoch/revision must be non-zero".into(),
            ));
        }
        let bootstrap = FinalUseRevocations {
            authority_epoch: browser.authority_epoch,
            revision: browser.revocation_revision,
            revoked_grant_ids: browser.revoked_grant_ids.clone(),
        };
        let authority = FinalUseAuthority::open_state_dir(
            &browser.authority_state_dir,
            browser.signer_id.clone(),
            browser.verifying_key,
            bootstrap.clone(),
        )?;
        let revocation_feed = BrowserRevocationFeed::start(
            authority.clone(),
            browser.revocation_feed_path.clone(),
            bootstrap,
        )
        .map_err(BrowserServoError::RevocationFeed)?;
        let process = process_config(browser)?;
        process.validate()?;
        let frame_timeout = process.parent_frame_timeout()?;
        let port = Some(spawn_port(&authority, &process, frame_timeout)?);
        Ok(Self {
            authority,
            process,
            frame_timeout,
            port,
            revocation_feed,
        })
    }

    pub fn call(&mut self, call: ProductCall) -> Result<Value, BrowserServoError> {
        if call.method.requires_final_use() {
            self.revocation_feed
                .refresh_now()
                .map_err(BrowserServoError::RevocationFeed)?;
        }
        if self.port.is_none() {
            self.port = Some(spawn_port(
                &self.authority,
                &self.process,
                self.frame_timeout,
            )?);
        }
        let method = call.method.module_method();
        let request = if call.method.requires_final_use() {
            BrowserServoCall::effect(
                call.input,
                BrowserFinalUseInvocation {
                    signed_grant: call.signed_grant.ok_or_else(|| {
                        BrowserServoError::Invalid(
                            "navigate_or_act requires a signed final-use grant"
                                .into(),
                        )
                    })?,
                    binding: call.binding.ok_or_else(|| {
                        BrowserServoError::Invalid(
                            "navigate_or_act requires an exact FinalUseBinding"
                                .into(),
                        )
                    })?,
                },
            )?
        } else {
            if call.signed_grant.is_some() || call.binding.is_some() {
                return Err(BrowserServoError::Invalid(
                    "non-effect Browser calls must not carry final-use authority"
                        .into(),
                ));
            }
            BrowserServoCall::read(method, call.input)?
        };
        let result = self
            .port
            .as_ref()
            .ok_or_else(|| {
                BrowserServoError::Unavailable(
                    "Browser port is unavailable".into(),
                )
            })?
            .call(request);
        if result.as_ref().err().is_some_and(reset_required) {
            // Never retry this semantic operation. A later call may start a
            // clean child and explicitly reconcile the durable identity.
            self.port = None;
        }
        result
    }
}

fn process_config(
    browser: BrowserServoHostConfig,
) -> Result<BrowserServoProcessConfig, BrowserServoError> {
    Ok(BrowserServoProcessConfig {
        node_path: browser.node_path,
        service_path: browser.service_path,
        service_sha256: parse_digest(
            &browser.service_sha256,
            "service_sha256",
        )?,
        worker_path: browser.worker_path,
        worker_sha256: parse_digest(
            &browser.worker_sha256,
            "worker_sha256",
        )?,
        profile_root: browser.profile_root,
        journal_path: browser.journal_path,
        reconciliation_root: browser.reconciliation_root,
        reconciliation_observer_id: browser.reconciliation_observer_id,
        reconciliation_verifying_key: browser
            .reconciliation_verifying_key
            .as_deref()
            .map(|value| {
                parse_digest(value, "reconciliation_verifying_key")
            })
            .transpose()?,
        reconciliation_minimum_observer_generation: browser
            .reconciliation_minimum_observer_generation,
        reconciliation_minimum_observed_at_unix_ms: browser
            .reconciliation_minimum_observed_at_unix_ms,
        reconciliation_current_frontier_digest: browser
            .reconciliation_current_frontier_digest
            .as_deref()
            .map(|value| {
                parse_digest(value, "reconciliation_current_frontier_digest")
            })
            .transpose()?,
        reconciliation_max_future_skew_ms: browser
            .reconciliation_max_future_skew_ms,
        bwrap_path: browser.bwrap_path,
        bwrap_sha256: parse_digest(
            &browser.bwrap_sha256,
            "bwrap_sha256",
        )?,
        prlimit_path: browser.prlimit_path,
        prlimit_sha256: parse_digest(
            &browser.prlimit_sha256,
            "prlimit_sha256",
        )?,
        max_profiles: browser.max_profiles,
        max_address_space_bytes: browser.max_address_space_bytes,
        max_cpu_seconds: browser.max_cpu_seconds,
        max_open_files: browser.max_open_files,
        max_processes: browser.max_processes,
        driver_timeout_ms: browser.driver_timeout_ms,
    })
}

fn spawn_port(
    authority: &FinalUseAuthority,
    process: &BrowserServoProcessConfig,
    frame_timeout: Duration,
) -> Result<ProductPort, BrowserServoError> {
    let child = ChildBrowserTransport::spawn(process)?;
    BrowserServoPort::with_frame_timeout(
        authority.clone(),
        AdmissionValidatingTransport::new(child),
        frame_timeout,
    )
}

fn reset_required(error: &BrowserServoError) -> bool {
    matches!(
        error,
        BrowserServoError::Protocol(_)
            | BrowserServoError::Indeterminate(_)
            | BrowserServoError::Unavailable(_)
    )
}

fn verify_service_closure(
    entrypoint: &Path,
    closure: &[ArtifactBinding],
) -> Result<(), BrowserServoError> {
    if closure.is_empty() || closure.len() > MAX_CLOSURE_FILES {
        return Err(BrowserServoError::Invalid(
            "Browser service closure file count is outside bounds".into(),
        ));
    }
    let mut paths = HashSet::new();
    let mut entrypoint_bound = false;
    for binding in closure {
        if !binding.path.is_absolute() || !paths.insert(binding.path.clone()) {
            return Err(BrowserServoError::Invalid(
                "Browser service closure paths must be absolute and unique"
                    .into(),
            ));
        }
        if binding.max_bytes == 0
            || binding.max_bytes > MAX_CLOSURE_FILE_BYTES
        {
            return Err(BrowserServoError::Invalid(
                "Browser service closure file bound is invalid".into(),
            ));
        }
        verify_file_digest(
            &binding.path,
            parse_digest(
                &binding.sha256,
                "service_closure.sha256",
            )?,
            usize::try_from(binding.max_bytes).map_err(|_| {
                BrowserServoError::Invalid(
                    "Browser service closure size overflow".into(),
                )
            })?,
        )?;
        entrypoint_bound |= binding.path == entrypoint;
    }
    if !entrypoint_bound {
        return Err(BrowserServoError::Invalid(
            "Browser service closure does not bind the selected entrypoint"
                .into(),
        ));
    }
    Ok(())
}

fn verify_file_digest(
    path: &Path,
    expected: [u8; 32],
    maximum: usize,
) -> Result<(), BrowserServoError> {
    let metadata = fs::symlink_metadata(path).map_err(|error| {
        BrowserServoError::Invalid(format!(
            "cannot inspect {}: {error}",
            path.display()
        ))
    })?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(BrowserServoError::Invalid(format!(
            "{} must be a regular non-symlink file",
            path.display()
        )));
    }
    let size = usize::try_from(metadata.len())
        .map_err(|_| {
            BrowserServoError::Invalid(
                "Browser artifact size overflow".into(),
            )
        })?;
    if size == 0 || size > maximum {
        return Err(BrowserServoError::Invalid(format!(
            "{} exceeds its bounded file size",
            path.display()
        )));
    }
    let bytes = fs::read(path).map_err(|error| {
        BrowserServoError::Invalid(format!(
            "cannot read {}: {error}",
            path.display()
        ))
    })?;
    let actual: [u8; 32] = Sha256::digest(bytes).into();
    if actual != expected {
        return Err(BrowserServoError::BindingMismatch(format!(
            "{} digest does not match selected Browser artifact",
            path.display()
        )));
    }
    Ok(())
}

fn parse_digest(
    value: &str,
    name: &str,
) -> Result<[u8; 32], BrowserServoError> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
        || value.bytes().all(|byte| byte == b'0')
    {
        return Err(BrowserServoError::Invalid(format!(
            "{name} must be non-zero lowercase SHA-256 hex"
        )));
    }
    let mut output = [0_u8; 32];
    for (index, byte) in output.iter_mut().enumerate() {
        let start = index * 2;
        *byte = u8::from_str_radix(&value[start..start + 2], 16)
            .map_err(|error| {
                BrowserServoError::Invalid(format!(
                    "{name} contains invalid hex: {error}"
                ))
            })?;
    }
    Ok(output)
}
