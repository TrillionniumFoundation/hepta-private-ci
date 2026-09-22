use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::VerifiedUseToken;
use ed25519_dalek::Signature;
use ed25519_dalek::Verifier as _;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;

use crate::error::ShellError;
use crate::model::EndpointManifest;
use crate::model::PlatformPayload;
use crate::model::SessionIncarnation;
use crate::model::sha256_bytes;
use crate::model::sha256_hex;
use crate::model::validate_digest;
use crate::model::validate_stable_id;

const MAX_CLOCK_SKEW_MS: u64 = 5 * 60 * 1000;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SignedEndpointManifestV1 {
    pub schema: String,
    pub endpoint_id: String,
    pub address: String,
    pub protocol_version: u32,
    pub gateway_credential_account: String,
    pub issued_unix_ms: u64,
    pub expires_unix_ms: u64,
    pub key_id: String,
    pub manifest_digest: String,
    pub signature_base64: String,
}

#[derive(Debug, Clone)]
pub struct VerifiedEndpointManifest {
    pub manifest: EndpointManifest,
    pub gateway_credential_account: String,
}

impl SignedEndpointManifestV1 {
    pub fn payload_message(&self) -> String {
        format!(
            "hepta.endpoint-manifest-payload.v1\nschema={}\nendpoint_id={}\naddress={}\nprotocol_version={}\ngateway_credential_account={}\nissued_unix_ms={}\nexpires_unix_ms={}\nkey_id={}\n",
            self.schema,
            self.endpoint_id,
            self.address,
            self.protocol_version,
            self.gateway_credential_account,
            self.issued_unix_ms,
            self.expires_unix_ms,
            self.key_id
        )
    }

    pub fn computed_manifest_digest(&self) -> String {
        sha256_hex(self.payload_message().as_bytes())
    }

    pub fn signing_message(&self) -> String {
        format!(
            "hepta.endpoint-manifest-signature.v1\nmanifest_digest={}\n",
            self.manifest_digest
        )
    }

    pub fn verify(&self, keys: &TrustedKeySet) -> Result<VerifiedEndpointManifest, ShellError> {
        if self.schema != "hepta.endpoint-manifest.v1" {
            return Err(ShellError::Security(
                "unsupported native endpoint manifest schema".to_owned(),
            ));
        }
        validate_stable_id(&self.endpoint_id, "endpoint manifest endpoint_id")?;
        validate_stable_id(
            &self.gateway_credential_account,
            "endpoint manifest gateway credential account",
        )?;
        validate_stable_id(&self.key_id, "endpoint manifest key_id")?;
        validate_digest(&self.manifest_digest, "endpoint manifest digest")?;
        if self.protocol_version == 0 {
            return Err(ShellError::Security(
                "endpoint manifest protocol version must be positive".to_owned(),
            ));
        }
        let now = now_unix_ms()?;
        if self.issued_unix_ms > now.saturating_add(MAX_CLOCK_SKEW_MS)
            || self.expires_unix_ms < now
            || self.expires_unix_ms <= self.issued_unix_ms
            || self.expires_unix_ms.saturating_sub(self.issued_unix_ms) > 24 * 60 * 60 * 1000
        {
            return Err(ShellError::Security(
                "native endpoint manifest time window is invalid".to_owned(),
            ));
        }
        if self.computed_manifest_digest() != self.manifest_digest {
            return Err(ShellError::Security(
                "native endpoint manifest digest mismatch".to_owned(),
            ));
        }
        keys.verify_message(
            &self.key_id,
            &self.signature_base64,
            self.signing_message().as_bytes(),
        )?;
        let manifest = EndpointManifest {
            endpoint_id: self.endpoint_id.clone(),
            address: self.address.clone(),
            manifest_digest: self.manifest_digest.clone(),
            protocol_version: self.protocol_version,
        };
        manifest.validate()?;
        Ok(VerifiedEndpointManifest {
            manifest,
            gateway_credential_account: self.gateway_credential_account.clone(),
        })
    }
}

#[derive(Debug, Clone)]
pub struct TrustedKeySet {
    keys: BTreeMap<String, VerifyingKey>,
    revoked_key_ids: BTreeSet<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct KeySetFile {
    schema: String,
    keys: BTreeMap<String, String>,
    #[serde(default)]
    revoked_key_ids: BTreeSet<String>,
}

impl TrustedKeySet {
    pub fn from_path(path: &Path) -> Result<Self, ShellError> {
        if !path.is_absolute() {
            return Err(ShellError::InvalidInput(
                "trusted key set path must be absolute".to_owned(),
            ));
        }
        let file: KeySetFile = serde_json::from_slice(&std::fs::read(path)?)?;
        if file.schema != "hepta.native-trusted-keys.v1" || file.keys.is_empty() {
            return Err(ShellError::Security(
                "trusted native key set schema or key population is invalid".to_owned(),
            ));
        }
        for key_id in &file.revoked_key_ids {
            validate_stable_id(key_id, "revoked trusted key id")?;
        }
        let revoked_key_ids = file.revoked_key_ids;
        let mut keys = BTreeMap::new();
        for (key_id, encoded) in file.keys {
            validate_stable_id(&key_id, "trusted key id")?;
            let decoded = STANDARD
                .decode(encoded)
                .map_err(|error| ShellError::Security(error.to_string()))?;
            let key_bytes: [u8; 32] = decoded.try_into().map_err(|_| {
                ShellError::Security("trusted Ed25519 public key must be 32 bytes".to_owned())
            })?;
            let key = VerifyingKey::from_bytes(&key_bytes)
                .map_err(|error| ShellError::Security(error.to_string()))?;
            keys.insert(key_id, key);
        }
        Ok(Self {
            keys,
            revoked_key_ids,
        })
    }

    pub fn verify_message(
        &self,
        key_id: &str,
        signature_base64: &str,
        message: &[u8],
    ) -> Result<(), ShellError> {
        validate_stable_id(key_id, "signing key id")?;
        if self.revoked_key_ids.contains(key_id) {
            return Err(ShellError::Security(format!(
                "native signing key {key_id} is revoked"
            )));
        }
        let key = self.keys.get(key_id).ok_or_else(|| {
            ShellError::Security(format!("untrusted native signing key {key_id}"))
        })?;
        let signature_bytes = STANDARD
            .decode(signature_base64)
            .map_err(|error| ShellError::Security(error.to_string()))?;
        let signature = Signature::from_slice(&signature_bytes)
            .map_err(|error| ShellError::Security(error.to_string()))?;
        key.verify(message, &signature)
            .map_err(|error| ShellError::Security(error.to_string()))
    }
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct KernelFinalUseAuthorityConfigV1 {
    pub schema: String,
    pub signer_id: String,
    pub verifying_key_base64: String,
    pub state_dir: PathBuf,
    pub head: FinalUseRevocations,
}

impl KernelFinalUseAuthorityConfigV1 {
    fn load(path: &Path) -> Result<(Self, [u8; 32]), ShellError> {
        if !path.is_absolute() {
            return Err(ShellError::InvalidInput(
                "kernel final-use authority config path must be absolute".to_owned(),
            ));
        }
        let config: Self = serde_json::from_slice(&std::fs::read(path)?)?;
        if config.schema != "hepta.native-final-use-authority.v1" {
            return Err(ShellError::Security(
                "unsupported kernel final-use authority config schema".to_owned(),
            ));
        }
        validate_stable_id(&config.signer_id, "final-use signer_id")?;
        if !config.state_dir.is_absolute() {
            return Err(ShellError::Security(
                "kernel final-use state directory must be absolute".to_owned(),
            ));
        }
        let decoded = STANDARD
            .decode(&config.verifying_key_base64)
            .map_err(|error| ShellError::Security(error.to_string()))?;
        let verifying_key: [u8; 32] = decoded.try_into().map_err(|_| {
            ShellError::Security("kernel final-use Ed25519 public key must be 32 bytes".to_owned())
        })?;
        Ok((config, verifying_key))
    }
}

#[derive(Debug)]
pub struct KernelFinalUseGate {
    authority: FinalUseAuthority,
    config_path: PathBuf,
    signer_id: String,
    verifying_key: [u8; 32],
    state_dir: PathBuf,
    current_head: Mutex<FinalUseRevocations>,
}

#[derive(Debug)]
pub struct KernelFinalUsePermit {
    token: VerifiedUseToken,
    binding: FinalUseBinding,
}

impl KernelFinalUseGate {
    pub fn open(config_path: PathBuf) -> Result<Self, ShellError> {
        let (config, verifying_key) = KernelFinalUseAuthorityConfigV1::load(&config_path)?;
        let authority = FinalUseAuthority::open_state_dir(
            &config.state_dir,
            config.signer_id.clone(),
            verifying_key,
            config.head.clone(),
        )
        .map_err(|error| {
            ShellError::Security(format!("open kernel final-use authority: {error}"))
        })?;
        Ok(Self {
            authority,
            config_path,
            signer_id: config.signer_id,
            verifying_key,
            state_dir: config.state_dir,
            current_head: Mutex::new(config.head),
        })
    }

    pub fn claim_platform(
        &self,
        signed: &SignedFinalUseGrant,
        binding: FinalUseBinding,
    ) -> Result<KernelFinalUsePermit, ShellError> {
        self.refresh_revocations()?;
        let token = self
            .authority
            .claim(signed, &binding)
            .map_err(|error| ShellError::Security(format!("kernel final-use claim: {error}")))?;
        Ok(KernelFinalUsePermit { token, binding })
    }

    pub fn with_platform_use<T>(
        &self,
        permit: KernelFinalUsePermit,
        consumer: impl FnOnce() -> T,
    ) -> Result<T, ShellError> {
        self.refresh_revocations()?;
        self.authority
            .with_verified_use(permit.token, &permit.binding, consumer)
            .map_err(|error| {
                ShellError::Security(format!("kernel final-use revalidation: {error}"))
            })
    }

    fn refresh_revocations(&self) -> Result<(), ShellError> {
        let (config, verifying_key) = KernelFinalUseAuthorityConfigV1::load(&self.config_path)?;
        if config.signer_id != self.signer_id
            || verifying_key != self.verifying_key
            || config.state_dir != self.state_dir
        {
            return Err(ShellError::Security(
                "kernel final-use trust identity changed in place".to_owned(),
            ));
        }
        let mut current = self
            .current_head
            .lock()
            .map_err(|_| ShellError::Security("kernel final-use head lock poisoned".to_owned()))?;
        let same = config.head.authority_epoch == current.authority_epoch
            && config.head.revision == current.revision
            && config.head.revoked_grant_ids == current.revoked_grant_ids;
        if same {
            return Ok(());
        }
        if config.head.authority_epoch < current.authority_epoch
            || config.head.revision <= current.revision
            || (config.head.authority_epoch == current.authority_epoch
                && !config
                    .head
                    .revoked_grant_ids
                    .is_superset(&current.revoked_grant_ids))
        {
            return Err(ShellError::Security(
                "kernel final-use revocation head regressed".to_owned(),
            ));
        }
        self.authority
            .update_revocations(config.head.clone())
            .map_err(|error| {
                ShellError::Security(format!("update kernel final-use revocations: {error}"))
            })?;
        *current = config.head;
        Ok(())
    }
}

pub fn platform_final_use_binding(
    subject_id: &str,
    session: &SessionIncarnation,
    operation_id: &str,
    displayed_revision: u64,
    payload: &PlatformPayload,
) -> Result<FinalUseBinding, ShellError> {
    validate_stable_id(subject_id, "final-use subject_id")?;
    validate_stable_id(operation_id, "final-use operation_id")?;
    session.validate()?;
    payload.validate()?;
    if displayed_revision == 0 {
        return Err(ShellError::InvalidInput(
            "displayed revision must be positive".to_owned(),
        ));
    }
    let payload_bytes = serde_json::to_vec(payload)?;
    let payload_sha256 = sha256_bytes(&payload_bytes);
    let payload_digest = sha256_hex(&payload_bytes);
    let destination_id = format!("ui.native.platform:{}", payload.action());
    validate_stable_id(&destination_id, "final-use destination_id")?;
    let request_sha256 = sha256_bytes(
        format!(
            "hepta.ui.native.platform-request.v1|{subject_id}|{}|{}|{operation_id}|{}|{displayed_revision}|{payload_digest}",
            session.session_id,
            session.generation,
            payload.action(),
        )
        .as_bytes(),
    );
    let scope_sha256 = sha256_bytes(
        format!(
            "hepta.ui.native.platform-scope.v1|{subject_id}|{destination_id}|{}|{payload_digest}",
            payload.action(),
        )
        .as_bytes(),
    );
    Ok(FinalUseBinding {
        subject_id: subject_id.to_owned(),
        destination_id,
        request_sha256,
        scope_sha256,
        payload_sha256,
    })
}

pub fn now_unix_ms() -> Result<u64, ShellError> {
    let duration = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| ShellError::State(error.to_string()))?;
    u64::try_from(duration.as_millis())
        .map_err(|_| ShellError::State("system clock exceeds u64 milliseconds".to_owned()))
}
