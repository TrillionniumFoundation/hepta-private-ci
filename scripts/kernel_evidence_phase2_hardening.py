#!/usr/bin/env python3
"""Apply the phase-two kernel.evidence trust/recovery hardening.

The script is intentionally fail-closed and idempotent. It is executed only after
phase-one verification profiles have landed. It never changes qualification,
acceptance, activation, canary, promotion, or release status flags.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def path(name: str) -> Path:
    return ROOT / name


def read(name: str) -> str:
    return path(name).read_text(encoding="utf-8")


def write(name: str, value: str) -> None:
    target = path(name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value, encoding="utf-8")


def replace_once(name: str, old: str, new: str) -> None:
    text = read(name)
    if new in text:
        return
    observed = text.count(old)
    if observed != 1:
        raise SystemExit(
            f"{name}: expected one match, observed {observed}: {old[:120]!r}"
        )
    write(name, text.replace(old, new, 1))


def replace_regex_once(name: str, pattern: str, replacement: str) -> None:
    text = read(name)
    if re.search(pattern, text, flags=re.S) is None:
        if replacement in text:
            return
        raise SystemExit(f"{name}: regex did not match: {pattern}")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"{name}: expected one regex replacement, observed {count}")
    write(name, updated)


if "EvidenceVerificationProfileV1" not in read(
    "codex-rs/hepta-evidence/src/qualification.rs"
):
    raise SystemExit("phase one has not landed; refusing to apply phase two")

TRUST_SNAPSHOT = r"""use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;

use crate::EvidenceError;
use crate::EvidenceIssuerRoleV1;
use crate::EvidenceIssuerTrustBindingV1;
use crate::canonical::canonical_json;

const SIGNED_REGISTRY_SCHEMA_VERSION: u32 = 2;
const LEGACY_REGISTRY_SCHEMA_VERSION: u32 = 1;
const MAX_ISSUERS: usize = 32;
const MAX_ROLES_PER_ISSUER: usize = 16;
const MAX_SIGNERS: usize = 32;
const MAX_SIGNATURES: usize = 8;
const MAX_FUTURE_CLOCK_SKEW_MS: u64 = 5 * 60 * 1000;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EvidenceTrustRegistrySignerV2 {
    principal_id: String,
    key_epoch: u64,
    public_key_hex: String,
    revoked: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EvidenceTrustRegistryIssuerV2 {
    issuer_id: String,
    key_epoch: u64,
    public_key_hex: String,
    revoked: bool,
    roles: Vec<EvidenceIssuerRoleV1>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EvidenceTrustRegistrySignatureV2 {
    signer_principal_id: String,
    signer_key_epoch: u64,
    signature_hex: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SignedEvidenceTrustRegistryV2 {
    schema_version: u32,
    agent_id: String,
    generation: u64,
    predecessor_sha256: Option<Sha256Digest>,
    issued_at_unix_ms: u64,
    signer_policy_generation: u64,
    threshold: usize,
    signers: Vec<EvidenceTrustRegistrySignerV2>,
    issuers: Vec<EvidenceTrustRegistryIssuerV2>,
    signatures: Vec<EvidenceTrustRegistrySignatureV2>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct UnsignedEvidenceTrustRegistryV2<'a> {
    schema_version: u32,
    agent_id: &'a str,
    generation: u64,
    predecessor_sha256: &'a Option<Sha256Digest>,
    issued_at_unix_ms: u64,
    signer_policy_generation: u64,
    threshold: usize,
    signers: &'a [EvidenceTrustRegistrySignerV2],
    issuers: &'a [EvidenceTrustRegistryIssuerV2],
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct EvidenceTrustSignerPolicyDigestV2<'a> {
    schema_version: u32,
    policy_generation: u64,
    threshold: usize,
    signers: &'a [EvidenceTrustRegistrySignerV2],
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct LegacyEvidenceIssuerTrustV1 {
    issuer_id: String,
    key_epoch: u64,
    public_key_hex: String,
    revoked: bool,
    roles: Vec<String>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct LegacyEvidenceTrustV1 {
    schema_version: u32,
    agent_id: String,
    issuers: Vec<LegacyEvidenceIssuerTrustV1>,
}

#[derive(Clone, Debug)]
struct VerifiedEvidenceIssuer {
    issuer_id: String,
    key_epoch: u64,
    verifying_key: VerifyingKey,
    revoked: bool,
    roles: BTreeSet<EvidenceIssuerRoleV1>,
}

/// A sealed trust snapshot. Callers cannot construct this from an arbitrary
/// vector of bindings; it is produced only by parsing and validating an owner
/// registry, and production requires the signed monotonic v2 format.
#[derive(Clone, Debug)]
pub struct VerifiedEvidenceTrustSnapshot {
    agent_id: String,
    generation: u64,
    predecessor_sha256: Option<Sha256Digest>,
    registry_sha256: Sha256Digest,
    signer_policy_sha256: Sha256Digest,
    signed: bool,
    issuers: Vec<VerifiedEvidenceIssuer>,
    bindings: Vec<EvidenceIssuerTrustBindingV1>,
}

mod sealed {
    pub trait Sealed {}
}

/// Sealed view accepted by qualification verification. Production code can
/// supply only `VerifiedEvidenceTrustSnapshot`; raw binding slices are accepted
/// solely while compiling the evidence crate's unit tests.
pub trait EvidenceTrustSnapshotView: sealed::Sealed {
    #[doc(hidden)]
    fn evidence_bindings(&self) -> &[EvidenceIssuerTrustBindingV1];
}

impl sealed::Sealed for VerifiedEvidenceTrustSnapshot {}

impl EvidenceTrustSnapshotView for VerifiedEvidenceTrustSnapshot {
    fn evidence_bindings(&self) -> &[EvidenceIssuerTrustBindingV1] {
        &self.bindings
    }
}

#[cfg(test)]
impl sealed::Sealed for [EvidenceIssuerTrustBindingV1] {}

#[cfg(test)]
impl EvidenceTrustSnapshotView for [EvidenceIssuerTrustBindingV1] {
    fn evidence_bindings(&self) -> &[EvidenceIssuerTrustBindingV1] {
        self
    }
}

impl VerifiedEvidenceTrustSnapshot {
    pub fn parse_owner_registry(
        bytes: &[u8],
        expected_agent_id: &str,
        now_unix_ms: u64,
        require_signed: bool,
    ) -> Result<Self, EvidenceError> {
        let value: serde_json::Value = serde_json::from_slice(bytes)
            .map_err(|error| EvidenceError::InvalidRecord(error.to_string()))?;
        let schema_version = value
            .get("schemaVersion")
            .or_else(|| value.get("schema_version"))
            .and_then(serde_json::Value::as_u64)
            .ok_or_else(|| invalid("evidence trust registry has no schema version"))?;
        match schema_version {
            2 => Self::parse_signed(bytes, expected_agent_id, now_unix_ms),
            1 if !require_signed => Self::parse_legacy(bytes, expected_agent_id),
            1 => Err(invalid(
                "production evidence trust requires signed monotonic registry schema v2",
            )),
            _ => Err(invalid("unsupported evidence trust registry schema")),
        }
    }

    fn parse_signed(
        bytes: &[u8],
        expected_agent_id: &str,
        now_unix_ms: u64,
    ) -> Result<Self, EvidenceError> {
        let registry: SignedEvidenceTrustRegistryV2 = serde_json::from_slice(bytes)
            .map_err(|error| EvidenceError::InvalidRecord(error.to_string()))?;
        if canonical_json(&registry)? != bytes {
            return Err(invalid(
                "signed evidence trust registry must use canonical JSON without duplicate keys",
            ));
        }
        if registry.schema_version != SIGNED_REGISTRY_SCHEMA_VERSION
            || registry.agent_id != expected_agent_id
            || registry.generation == 0
            || registry.signer_policy_generation == 0
            || registry.threshold == 0
            || registry.signers.is_empty()
            || registry.signers.len() > MAX_SIGNERS
            || registry.issuers.is_empty()
            || registry.issuers.len() > MAX_ISSUERS
            || registry.signatures.is_empty()
            || registry.signatures.len() > MAX_SIGNATURES
            || registry.issued_at_unix_ms
                > now_unix_ms.saturating_add(MAX_FUTURE_CLOCK_SKEW_MS)
        {
            return Err(invalid(
                "signed evidence trust registry owner, generation, policy, size or time is invalid",
            ));
        }
        match (registry.generation, registry.predecessor_sha256.as_ref()) {
            (1, None) => {}
            (1, Some(_)) | (_, None) => {
                return Err(invalid(
                    "trust registry predecessor is inconsistent with its generation",
                ));
            }
            (_, Some(predecessor)) => validate_digest(predecessor, "trust predecessor")?,
        }

        let mut signer_identities = BTreeSet::new();
        let mut signer_principals = BTreeSet::new();
        let mut signer_map = BTreeMap::new();
        let mut previous_signer: Option<(&str, u64)> = None;
        for signer in &registry.signers {
            validate_identity(&signer.principal_id, signer.key_epoch, "trust signer")?;
            let current = (signer.principal_id.as_str(), signer.key_epoch);
            if previous_signer.is_some_and(|previous| previous >= current)
                || !signer_identities.insert((signer.principal_id.clone(), signer.key_epoch))
            {
                return Err(invalid(
                    "trust registry signers must be unique and canonically ordered",
                ));
            }
            previous_signer = Some(current);
            let key = VerifyingKey::from_bytes(&hex_array::<32>(&signer.public_key_hex)?)
                .map_err(|_| invalid("trust registry contains invalid signer key"))?;
            if !signer.revoked {
                signer_principals.insert(signer.principal_id.clone());
            }
            signer_map.insert((signer.principal_id.as_str(), signer.key_epoch), (signer, key));
        }
        if registry.threshold > signer_principals.len() {
            return Err(invalid(
                "trust registry threshold exceeds active distinct signer principals",
            ));
        }

        let unsigned = UnsignedEvidenceTrustRegistryV2 {
            schema_version: registry.schema_version,
            agent_id: &registry.agent_id,
            generation: registry.generation,
            predecessor_sha256: &registry.predecessor_sha256,
            issued_at_unix_ms: registry.issued_at_unix_ms,
            signer_policy_generation: registry.signer_policy_generation,
            threshold: registry.threshold,
            signers: &registry.signers,
            issuers: &registry.issuers,
        };
        let payload = canonical_json(&unsigned)?;
        let mut signing_bytes = b"hepta.kernel.evidence.trust-registry.v2\0".to_vec();
        push_part(&mut signing_bytes, &payload);

        let mut verified_principals = BTreeSet::new();
        let mut previous_signature: Option<(&str, u64)> = None;
        for signature in &registry.signatures {
            let current = (
                signature.signer_principal_id.as_str(),
                signature.signer_key_epoch,
            );
            if previous_signature.is_some_and(|previous| previous >= current) {
                return Err(invalid(
                    "trust registry signatures must be unique and canonically ordered",
                ));
            }
            previous_signature = Some(current);
            let (signer, key) = signer_map.get(&current).ok_or_else(|| {
                invalid("trust registry signature is outside its signer policy")
            })?;
            if signer.revoked {
                return Err(invalid("trust registry signature uses a revoked signer"));
            }
            let signature = Signature::from_bytes(&hex_array::<64>(&signature.signature_hex)?);
            key.verify_strict(&signing_bytes, &signature)
                .map_err(|_| invalid("trust registry threshold signature verification failed"))?;
            verified_principals.insert(signer.principal_id.as_str());
        }
        if verified_principals.len() < registry.threshold {
            return Err(invalid(
                "trust registry does not satisfy its distinct-principal threshold",
            ));
        }

        let (issuers, bindings) = verified_issuers_v2(&registry.issuers)?;
        let signer_policy_sha256 = Sha256Digest::for_bytes(&canonical_json(
            &EvidenceTrustSignerPolicyDigestV2 {
                schema_version: SIGNED_REGISTRY_SCHEMA_VERSION,
                policy_generation: registry.signer_policy_generation,
                threshold: registry.threshold,
                signers: &registry.signers,
            },
        )?);
        Ok(Self {
            agent_id: registry.agent_id,
            generation: registry.generation,
            predecessor_sha256: registry.predecessor_sha256,
            registry_sha256: Sha256Digest::for_bytes(bytes),
            signer_policy_sha256,
            signed: true,
            issuers,
            bindings,
        })
    }

    fn parse_legacy(bytes: &[u8], expected_agent_id: &str) -> Result<Self, EvidenceError> {
        let registry: LegacyEvidenceTrustV1 = serde_json::from_slice(bytes)
            .map_err(|error| EvidenceError::InvalidRecord(error.to_string()))?;
        if registry.schema_version != LEGACY_REGISTRY_SCHEMA_VERSION
            || registry.agent_id != expected_agent_id
            || registry.issuers.is_empty()
            || registry.issuers.len() > MAX_ISSUERS
        {
            return Err(invalid(
                "legacy evidence trust registry owner, schema or issuer bound is invalid",
            ));
        }
        let mut identities = BTreeSet::new();
        let mut issuers = Vec::new();
        let mut bindings = Vec::new();
        for configured in registry.issuers {
            validate_identity(&configured.issuer_id, configured.key_epoch, "legacy issuer")?;
            if !identities.insert((configured.issuer_id.clone(), configured.key_epoch))
                || configured.roles.is_empty()
                || configured.roles.len() > MAX_ROLES_PER_ISSUER
            {
                return Err(invalid(
                    "legacy evidence trust registry has duplicate issuers or invalid role bounds",
                ));
            }
            let verifying_key = VerifyingKey::from_bytes(&hex_array::<32>(
                &configured.public_key_hex,
            )?)
            .map_err(|_| invalid("legacy evidence trust registry contains invalid key"))?;
            let mut roles = BTreeSet::new();
            for role in configured.roles {
                let role = EvidenceIssuerRoleV1::parse(&role)
                    .map_err(EvidenceError::InvalidRecord)?;
                if !roles.insert(role) {
                    return Err(invalid("legacy evidence trust registry repeats a role"));
                }
                if !configured.revoked {
                    bindings.push(EvidenceIssuerTrustBindingV1 {
                        issuer_principal_id: configured.issuer_id.clone(),
                        issuer_key_epoch: configured.key_epoch,
                        issuer_signing_identity_sha256: Sha256Digest::for_bytes(
                            verifying_key.as_bytes(),
                        ),
                        role,
                    });
                }
            }
            issuers.push(VerifiedEvidenceIssuer {
                issuer_id: configured.issuer_id,
                key_epoch: configured.key_epoch,
                verifying_key,
                revoked: configured.revoked,
                roles,
            });
        }
        bindings.sort_by(|left, right| {
            left.issuer_principal_id
                .cmp(&right.issuer_principal_id)
                .then(left.issuer_key_epoch.cmp(&right.issuer_key_epoch))
                .then(left.role.cmp(&right.role))
        });
        Ok(Self {
            agent_id: registry.agent_id,
            generation: 0,
            predecessor_sha256: None,
            registry_sha256: Sha256Digest::for_bytes(bytes),
            signer_policy_sha256: Sha256Digest::for_bytes(
                b"hepta.kernel.evidence.legacy-owner-trust.v1",
            ),
            signed: false,
            issuers,
            bindings,
        })
    }

    pub fn agent_id(&self) -> &str {
        &self.agent_id
    }

    pub fn generation(&self) -> u64 {
        self.generation
    }

    pub fn predecessor_sha256(&self) -> Option<&Sha256Digest> {
        self.predecessor_sha256.as_ref()
    }

    pub fn registry_sha256(&self) -> &Sha256Digest {
        &self.registry_sha256
    }

    pub fn signer_policy_sha256(&self) -> &Sha256Digest {
        &self.signer_policy_sha256
    }

    pub fn is_signed(&self) -> bool {
        self.signed
    }

    pub fn issuer_for(
        &self,
        issuer_id: &str,
        key_epoch: u64,
        role: EvidenceIssuerRoleV1,
    ) -> Result<IssuerRegistration, EvidenceError> {
        let issuer = self
            .issuers
            .iter()
            .find(|issuer| issuer.issuer_id == issuer_id && issuer.key_epoch == key_epoch)
            .ok_or_else(|| invalid("evidence issuer/key epoch is not registered"))?;
        if issuer.revoked || !issuer.roles.contains(&role) {
            return Err(invalid(
                "evidence issuer is revoked or not registered for the requested role",
            ));
        }
        Ok(IssuerRegistration {
            issuer_id: StableId::new(issuer.issuer_id.clone())
                .map_err(|error| invalid(format!("invalid evidence issuer: {error}")))?,
            key_epoch: Generation::new(issuer.key_epoch)
                .map_err(|error| invalid(format!("invalid evidence issuer epoch: {error}")))?,
            verifying_key: issuer.verifying_key,
            revoked: false,
        })
    }
}

fn verified_issuers_v2(
    configured: &[EvidenceTrustRegistryIssuerV2],
) -> Result<
    (
        Vec<VerifiedEvidenceIssuer>,
        Vec<EvidenceIssuerTrustBindingV1>,
    ),
    EvidenceError,
> {
    let mut identities = BTreeSet::new();
    let mut previous: Option<(&str, u64)> = None;
    let mut issuers = Vec::new();
    let mut bindings = Vec::new();
    for configured in configured {
        validate_identity(&configured.issuer_id, configured.key_epoch, "evidence issuer")?;
        let current = (configured.issuer_id.as_str(), configured.key_epoch);
        if previous.is_some_and(|previous| previous >= current)
            || !identities.insert((configured.issuer_id.clone(), configured.key_epoch))
            || configured.roles.is_empty()
            || configured.roles.len() > MAX_ROLES_PER_ISSUER
        {
            return Err(invalid(
                "signed evidence issuers must be unique, ordered and have bounded roles",
            ));
        }
        previous = Some(current);
        let verifying_key = VerifyingKey::from_bytes(&hex_array::<32>(
            &configured.public_key_hex,
        )?)
        .map_err(|_| invalid("signed evidence registry contains invalid issuer key"))?;
        let mut roles = BTreeSet::new();
        let mut previous_role: Option<&str> = None;
        for role in &configured.roles {
            if previous_role.is_some_and(|previous| previous >= role.as_str())
                || !roles.insert(*role)
            {
                return Err(invalid(
                    "signed evidence issuer roles must be unique and ordered",
                ));
            }
            previous_role = Some(role.as_str());
            if !configured.revoked {
                bindings.push(EvidenceIssuerTrustBindingV1 {
                    issuer_principal_id: configured.issuer_id.clone(),
                    issuer_key_epoch: configured.key_epoch,
                    issuer_signing_identity_sha256: Sha256Digest::for_bytes(
                        verifying_key.as_bytes(),
                    ),
                    role: *role,
                });
            }
        }
        issuers.push(VerifiedEvidenceIssuer {
            issuer_id: configured.issuer_id.clone(),
            key_epoch: configured.key_epoch,
            verifying_key,
            revoked: configured.revoked,
            roles,
        });
    }
    Ok((issuers, bindings))
}

fn validate_identity(value: &str, epoch: u64, label: &str) -> Result<(), EvidenceError> {
    StableId::new(value.to_string())
        .map_err(|error| invalid(format!("invalid {label} identity: {error}")))?;
    Generation::new(epoch)
        .map_err(|error| invalid(format!("invalid {label} epoch: {error}")))?;
    Ok(())
}

fn validate_digest(value: &Sha256Digest, label: &str) -> Result<(), EvidenceError> {
    Sha256Digest::parse(value.as_str().to_string())
        .map(|_| ())
        .map_err(|error| invalid(format!("invalid {label} digest: {error}")))
}

fn hex_array<const N: usize>(value: &str) -> Result<[u8; N], EvidenceError> {
    if value.len() != N * 2
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(invalid("non-canonical lowercase hexadecimal value"));
    }
    let mut result = [0_u8; N];
    for (index, target) in result.iter_mut().enumerate() {
        let offset = index * 2;
        *target = u8::from_str_radix(&value[offset..offset + 2], 16)
            .map_err(|_| invalid("invalid hexadecimal value"))?;
    }
    Ok(result)
}

fn push_part(target: &mut Vec<u8>, part: &[u8]) {
    target.extend_from_slice(&u64::try_from(part.len()).unwrap_or(u64::MAX).to_be_bytes());
    target.extend_from_slice(part);
}

fn invalid(message: impl Into<String>) -> EvidenceError {
    EvidenceError::InvalidRecord(message.into())
}
"""
write("codex-rs/hepta-evidence/src/trust_snapshot.rs", TRUST_SNAPSHOT)

RECOVERY_FRONTIER = r"""use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::schema_validation::classify_sqlx_error;

pub const EVIDENCE_DATABASE_LINEAGE: &str = "hepta_evidence_2.sqlite";
const MAX_QUALIFICATION_FRONTIER_ROWS: usize = 1_000_000;
const MAX_AUTHBUS_REPLAY_FRONTIER_ROWS: usize = 16_384;
const MAX_AUTHORITATIVE_TABLES: usize = 128;
const MAX_AUTHORITATIVE_COLUMNS_PER_TABLE: usize = 256;
const MAX_AUTHORITATIVE_ROWS: usize = 2_000_000;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceRecoverySnapshotV1 {
    pub schema_version: u32,
    pub database_lineage: String,
    pub migration_set_sha256: Sha256Digest,
    pub qualification_max_seq: u64,
    pub qualification_frontier_sha256: Sha256Digest,
    pub authbus_replay_frontier_sha256: Sha256Digest,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EvidenceRecoveryStateV2 {
    pub snapshot: EvidenceRecoverySnapshotV1,
    pub authoritative_store_sha256: Sha256Digest,
}

impl HeptaEvidenceStore {
    pub async fn bind_recovery_store_id(&self, store_id: &str) -> Result<(), EvidenceError> {
        StableId::new(store_id.to_string()).map_err(|error| {
            EvidenceError::InvalidRecord(format!("invalid evidence recovery store id: {error}"))
        })?;
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let existing: Option<String> = sqlx::query_scalar(
            "SELECT store_id FROM evidence_recovery_identity WHERE singleton = 1",
        )
        .fetch_optional(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;
        match existing {
            Some(existing) if existing != store_id => {
                transaction.rollback().await.map_err(classify_sqlx_error)?;
                return Err(EvidenceError::IdempotencyConflict {
                    record_id: "evidence_recovery_identity".to_string(),
                });
            }
            Some(_) => {}
            None => {
                sqlx::query(
                    "INSERT INTO evidence_recovery_identity (singleton, store_id) VALUES (1, ?)",
                )
                .bind(store_id)
                .execute(&mut *transaction)
                .await
                .map_err(classify_sqlx_error)?;
            }
        }
        transaction.commit().await.map_err(classify_sqlx_error)
    }

    pub async fn recovery_store_id(&self) -> Result<Option<String>, EvidenceError> {
        sqlx::query_scalar("SELECT store_id FROM evidence_recovery_identity WHERE singleton = 1")
            .fetch_optional(&self.pool)
            .await
            .map_err(classify_sqlx_error)
    }

    pub async fn recovery_snapshot(&self) -> Result<EvidenceRecoverySnapshotV1, EvidenceError> {
        Ok(self.recovery_state_v2().await?.snapshot)
    }

    /// Computes every recovery component from one SQLite read transaction.
    /// The authoritative digest covers every user table except local recovery
    /// identity/admission witnesses and the migration ledger, which are bound
    /// separately. Dynamic values use SQLite `quote()` plus length-delimited
    /// hashing, so text, blobs, NULLs and numeric values remain unambiguous.
    pub async fn recovery_state_v2(&self) -> Result<EvidenceRecoveryStateV2, EvidenceError> {
        let mut transaction = self.pool.begin().await.map_err(classify_sqlx_error)?;

        let migration_rows = sqlx::query(
            "SELECT version, description, checksum
             FROM _sqlx_migrations
             WHERE success = 1
             ORDER BY version",
        )
        .fetch_all(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;
        let mut migration_frontier = empty_frontier(b"hepta.evidence.migrations.v1");
        for row in migration_rows {
            let version: i64 = row.try_get("version").map_err(classify_sqlx_error)?;
            let description: String = row.try_get("description").map_err(classify_sqlx_error)?;
            let checksum: Vec<u8> = row.try_get("checksum").map_err(classify_sqlx_error)?;
            migration_frontier = extend_frontier(
                b"hepta.evidence.migrations.v1",
                &migration_frontier,
                &[&version.to_be_bytes(), description.as_bytes(), checksum.as_slice()],
            );
        }

        let qualification_rows = sqlx::query(
            "SELECT seq, evidence_id, envelope_sha256
             FROM qualification_evidence
             ORDER BY seq ASC
             LIMIT ?",
        )
        .bind(i64::try_from(MAX_QUALIFICATION_FRONTIER_ROWS + 1).map_err(|_| {
            EvidenceError::InvalidRecord("qualification recovery bound overflow".into())
        })?)
        .fetch_all(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;
        if qualification_rows.len() > MAX_QUALIFICATION_FRONTIER_ROWS {
            return Err(EvidenceError::Unavailable(
                "qualification recovery frontier exceeds one million rows".to_string(),
            ));
        }
        let mut qualification_frontier =
            empty_frontier(b"hepta.evidence.qualification-frontier.v1");
        let mut qualification_max_seq = 0_u64;
        for row in qualification_rows {
            let seq: i64 = row.try_get("seq").map_err(classify_sqlx_error)?;
            let seq = u64::try_from(seq)
                .map_err(|_| EvidenceError::Corrupt("negative qualification sequence".into()))?;
            let evidence_id: String = row.try_get("evidence_id").map_err(classify_sqlx_error)?;
            let envelope_sha256: String =
                row.try_get("envelope_sha256").map_err(classify_sqlx_error)?;
            qualification_frontier = extend_frontier(
                b"hepta.evidence.qualification-frontier.v1",
                &qualification_frontier,
                &[&seq.to_be_bytes(), evidence_id.as_bytes(), envelope_sha256.as_bytes()],
            );
            qualification_max_seq = seq;
        }

        let replay_rows = sqlx::query(
            "SELECT issuer_id, key_epoch, subject_id, scope_digest, sequence, envelope_digest
             FROM authbus_replay_sequences
             ORDER BY issuer_id, key_epoch, subject_id, scope_digest
             LIMIT ?",
        )
        .bind(i64::try_from(MAX_AUTHBUS_REPLAY_FRONTIER_ROWS + 1).map_err(|_| {
            EvidenceError::InvalidRecord("AuthBus recovery bound overflow".into())
        })?)
        .fetch_all(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;
        if replay_rows.len() > MAX_AUTHBUS_REPLAY_FRONTIER_ROWS {
            return Err(EvidenceError::Unavailable(
                "AuthBus replay recovery frontier exceeds registered capacity".to_string(),
            ));
        }
        let mut replay_frontier = empty_frontier(b"hepta.evidence.authbus-replay-frontier.v1");
        for row in replay_rows {
            let issuer_id: String = row.try_get("issuer_id").map_err(classify_sqlx_error)?;
            let key_epoch: Vec<u8> = row.try_get("key_epoch").map_err(classify_sqlx_error)?;
            let subject_id: String = row.try_get("subject_id").map_err(classify_sqlx_error)?;
            let scope_digest: Vec<u8> = row.try_get("scope_digest").map_err(classify_sqlx_error)?;
            let sequence: Vec<u8> = row.try_get("sequence").map_err(classify_sqlx_error)?;
            let envelope_digest: Vec<u8> =
                row.try_get("envelope_digest").map_err(classify_sqlx_error)?;
            if key_epoch.len() != 8
                || scope_digest.len() != 32
                || sequence.len() != 8
                || envelope_digest.len() != 32
            {
                return Err(EvidenceError::Corrupt(
                    "AuthBus replay frontier contains invalid fixed-width fields".to_string(),
                ));
            }
            replay_frontier = extend_frontier(
                b"hepta.evidence.authbus-replay-frontier.v1",
                &replay_frontier,
                &[
                    issuer_id.as_bytes(),
                    key_epoch.as_slice(),
                    subject_id.as_bytes(),
                    scope_digest.as_slice(),
                    sequence.as_slice(),
                    envelope_digest.as_slice(),
                ],
            );
        }

        let authoritative_store_sha256 = authoritative_store_frontier(&mut transaction).await?;
        let snapshot = EvidenceRecoverySnapshotV1 {
            schema_version: 1,
            database_lineage: EVIDENCE_DATABASE_LINEAGE.to_string(),
            migration_set_sha256: migration_frontier,
            qualification_max_seq,
            qualification_frontier_sha256: qualification_frontier,
            authbus_replay_frontier_sha256: replay_frontier,
        };
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(EvidenceRecoveryStateV2 {
            snapshot,
            authoritative_store_sha256,
        })
    }
}

async fn authoritative_store_frontier(
    transaction: &mut Transaction<'_, Sqlite>,
) -> Result<Sha256Digest, EvidenceError> {
    let table_rows = sqlx::query(
        "SELECT name FROM sqlite_schema
         WHERE type = 'table'
           AND name NOT LIKE 'sqlite_%'
           AND name NOT IN ('_sqlx_migrations', 'evidence_recovery_identity', 'evidence_frontier_acceptance')
         ORDER BY name
         LIMIT ?",
    )
    .bind(i64::try_from(MAX_AUTHORITATIVE_TABLES + 1).map_err(|_| {
        EvidenceError::InvalidRecord("authoritative table bound overflow".into())
    })?)
    .fetch_all(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    if table_rows.len() > MAX_AUTHORITATIVE_TABLES {
        return Err(EvidenceError::Unavailable(
            "authoritative evidence table inventory exceeds registered capacity".into(),
        ));
    }

    let mut frontier = empty_frontier(b"hepta.evidence.authoritative-store.v2");
    let mut total_rows = 0_usize;
    for table_row in table_rows {
        let table: String = table_row.try_get("name").map_err(classify_sqlx_error)?;
        let table_ident = quote_identifier(&table);
        let columns = sqlx::query(&format!("PRAGMA table_info({table_ident})"))
            .fetch_all(&mut **transaction)
            .await
            .map_err(classify_sqlx_error)?;
        if columns.is_empty() || columns.len() > MAX_AUTHORITATIVE_COLUMNS_PER_TABLE {
            return Err(EvidenceError::Corrupt(format!(
                "authoritative table {table} has an invalid column inventory"
            )));
        }
        let column_names = columns
            .iter()
            .map(|row| row.try_get::<String, _>("name").map_err(classify_sqlx_error))
            .collect::<Result<Vec<_>, _>>()?;
        let projections = column_names
            .iter()
            .enumerate()
            .map(|(index, column)| format!("quote({}) AS c{index}", quote_identifier(column)))
            .collect::<Vec<_>>()
            .join(", ");
        let order = column_names
            .iter()
            .map(|column| quote_identifier(column))
            .collect::<Vec<_>>()
            .join(", ");
        let remaining = MAX_AUTHORITATIVE_ROWS.saturating_sub(total_rows);
        let query = format!(
            "SELECT {projections} FROM {table_ident} ORDER BY {order} LIMIT {}",
            remaining.saturating_add(1)
        );
        let rows = sqlx::query(&query)
            .fetch_all(&mut **transaction)
            .await
            .map_err(classify_sqlx_error)?;
        if rows.len() > remaining {
            return Err(EvidenceError::Unavailable(
                "authoritative evidence rows exceed registered recovery capacity".into(),
            ));
        }
        frontier = extend_frontier(
            b"hepta.evidence.authoritative-store.v2",
            &frontier,
            &[b"table", table.as_bytes()],
        );
        for (row_index, row) in rows.iter().enumerate() {
            let mut values = Vec::with_capacity(column_names.len() + 2);
            values.push(table.as_bytes());
            let index_bytes = u64::try_from(row_index).unwrap_or(u64::MAX).to_be_bytes();
            values.push(index_bytes.as_slice());
            let mut owned = Vec::with_capacity(column_names.len());
            for index in 0..column_names.len() {
                let alias = format!("c{index}");
                owned.push(row.try_get::<String, _>(alias.as_str()).map_err(classify_sqlx_error)?);
            }
            values.extend(owned.iter().map(|value| value.as_bytes()));
            frontier = extend_frontier(
                b"hepta.evidence.authoritative-store.v2",
                &frontier,
                &values,
            );
        }
        total_rows = total_rows.saturating_add(rows.len());
    }
    Ok(frontier)
}

fn quote_identifier(value: &str) -> String {
    format!("\"{}\"", value.replace('"', "\"\""))
}

fn empty_frontier(domain: &[u8]) -> Sha256Digest {
    let mut bytes = Vec::with_capacity(domain.len() + 1);
    bytes.extend_from_slice(domain);
    bytes.push(0);
    Sha256Digest::for_bytes(&bytes)
}

fn extend_frontier(domain: &[u8], previous: &Sha256Digest, parts: &[&[u8]]) -> Sha256Digest {
    let mut bytes = Vec::with_capacity(
        domain.len()
            + previous.as_str().len()
            + parts.iter().map(|part| part.len() + 8).sum::<usize>()
            + 2,
    );
    bytes.extend_from_slice(domain);
    bytes.push(0);
    bytes.extend_from_slice(previous.as_str().as_bytes());
    for part in parts {
        bytes.extend_from_slice(&u64::try_from(part.len()).unwrap_or(u64::MAX).to_be_bytes());
        bytes.extend_from_slice(part);
    }
    Sha256Digest::for_bytes(&bytes)
}
"""
write("codex-rs/hepta-evidence/src/recovery_frontier.rs", RECOVERY_FRONTIER)

# Dependencies and exports.
replace_once(
    "codex-rs/hepta-evidence/Cargo.toml",
    "codex-state = { workspace = true }\n",
    "codex-state = { workspace = true }\ned25519-dalek = { workspace = true }\n",
)
replace_once(
    "codex-rs/hepta-evidence/src/lib.rs",
    "mod summary;\n",
    "mod summary;\nmod trust_snapshot;\n",
)
replace_once(
    "codex-rs/hepta-evidence/src/lib.rs",
    "pub use recovery_frontier::EvidenceRecoverySnapshotV1;\n",
    "pub use recovery_frontier::EvidenceRecoverySnapshotV1;\npub use recovery_frontier::EvidenceRecoveryStateV2;\npub use trust_snapshot::EvidenceTrustSnapshotView;\npub use trust_snapshot::VerifiedEvidenceTrustSnapshot;\n",
)

# Seal qualification verification behind a verified snapshot view.
qualification = "codex-rs/hepta-evidence/src/qualification.rs"
text = read(qualification)
old_sig = """    pub async fn verify_chain(
        &self,
        request: &VerifyChainRequestV1,
        current_trust: &[EvidenceIssuerTrustBindingV1],
    ) -> Result<EvidenceDispositionV1, EvidenceError> {"""
new_sig = """    pub async fn verify_chain<T>(
        &self,
        request: &VerifyChainRequestV1,
        current_trust: &T,
    ) -> Result<EvidenceDispositionV1, EvidenceError>
    where
        T: crate::EvidenceTrustSnapshotView + ?Sized,
    {
        let current_trust = current_trust.evidence_bindings();"""
if new_sig not in text:
    if old_sig not in text:
        raise SystemExit("qualification verify_chain signature drifted")
    text = text.replace(old_sig, new_sig, 1)
write(qualification, text)

EVIDENCE_TRUST = r"""//! Owner-controlled trust registry for kernel.evidence production ingress.

#[cfg(unix)]
use std::fs::File;
#[cfg(unix)]
use std::io::Read;
use std::path::Path;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_evidence::EvidenceIssuerRoleV1;
use codex_hepta_evidence::VerifiedEvidenceTrustSnapshot;

use crate::AgentdError;
use crate::AgentdIdentity;

const MAX_EVIDENCE_TRUST_FILE_BYTES: u64 = 128 * 1024;

pub(crate) struct EvidenceTrust {
    snapshot: VerifiedEvidenceTrustSnapshot,
}

impl EvidenceTrust {
    pub(crate) fn load(path: &Path, identity: &AgentdIdentity) -> Result<Self, AgentdError> {
        Self::load_internal(path, identity, false)
    }

    pub(crate) fn load_signed(
        path: &Path,
        identity: &AgentdIdentity,
    ) -> Result<Self, AgentdError> {
        Self::load_internal(path, identity, true)
    }

    pub(crate) fn load_with_digest(
        path: &Path,
        identity: &AgentdIdentity,
    ) -> Result<(Self, Sha256Digest), AgentdError> {
        let trust = Self::load(path, identity)?;
        let digest = trust.snapshot.registry_sha256().clone();
        Ok((trust, digest))
    }

    pub(crate) fn load_signed_with_digest(
        path: &Path,
        identity: &AgentdIdentity,
    ) -> Result<(Self, Sha256Digest), AgentdError> {
        let trust = Self::load_signed(path, identity)?;
        let digest = trust.snapshot.registry_sha256().clone();
        Ok((trust, digest))
    }

    fn load_internal(
        path: &Path,
        identity: &AgentdIdentity,
        require_signed: bool,
    ) -> Result<Self, AgentdError> {
        let bytes = read_owner_file(path, identity)?;
        let snapshot = VerifiedEvidenceTrustSnapshot::parse_owner_registry(
            &bytes,
            identity.agent_id.as_str(),
            current_time_millis()?,
            require_signed,
        )
        .map_err(evidence_error)?;
        if require_signed && !snapshot.is_signed() {
            return Err(invalid("production trust registry is not signed"));
        }
        Ok(Self { snapshot })
    }

    pub(crate) fn verification_snapshot(&self) -> &VerifiedEvidenceTrustSnapshot {
        &self.snapshot
    }

    pub(crate) fn generation(&self) -> u64 {
        self.snapshot.generation()
    }

    pub(crate) fn predecessor_sha256(&self) -> Option<&Sha256Digest> {
        self.snapshot.predecessor_sha256()
    }

    pub(crate) fn signer_policy_sha256(&self) -> &Sha256Digest {
        self.snapshot.signer_policy_sha256()
    }

    pub(crate) fn issuer_for(
        &self,
        issuer_id: &str,
        key_epoch: u64,
        role: EvidenceIssuerRoleV1,
    ) -> Result<IssuerRegistration, AgentdError> {
        self.snapshot
            .issuer_for(issuer_id, key_epoch, role)
            .map_err(evidence_error)
    }
}

#[cfg(unix)]
pub(crate) fn read_owner_file(
    path: &Path,
    identity: &AgentdIdentity,
) -> Result<Vec<u8>, AgentdError> {
    use std::os::unix::fs::MetadataExt;

    if !path.is_absolute()
        || path.parent() != Some(identity.home_root.as_path())
        || identity.home_root.canonicalize()? != identity.home_root
    {
        return Err(invalid(
            "evidence trust file must be a direct child of the canonical Agent home",
        ));
    }
    let home = std::fs::metadata(&identity.home_root)?;
    let before = std::fs::symlink_metadata(path)?;
    if !home.is_dir()
        || home.mode() & 0o077 != 0
        || !before.is_file()
        || before.nlink() != 1
        || before.uid() != home.uid()
        || before.mode() & 0o077 != 0
        || before.len() == 0
        || before.len() > MAX_EVIDENCE_TRUST_FILE_BYTES
    {
        return Err(invalid(
            "evidence trust file must be a private owner-controlled regular file",
        ));
    }
    let mut file = File::open(path)?;
    let opened = file.metadata()?;
    let identity_tuple = |metadata: &std::fs::Metadata| {
        (
            metadata.dev(),
            metadata.ino(),
            metadata.len(),
            metadata.mtime(),
            metadata.mtime_nsec(),
            metadata.ctime(),
            metadata.ctime_nsec(),
        )
    };
    if identity_tuple(&opened) != identity_tuple(&before) {
        return Err(invalid("evidence trust file changed while opening"));
    }
    let mut bytes = Vec::new();
    file.by_ref()
        .take(MAX_EVIDENCE_TRUST_FILE_BYTES + 1)
        .read_to_end(&mut bytes)?;
    let after = std::fs::symlink_metadata(path)?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_EVIDENCE_TRUST_FILE_BYTES
        || !after.is_file()
        || identity_tuple(&after) != identity_tuple(&before)
        || identity_tuple(&file.metadata()?) != identity_tuple(&before)
    {
        return Err(invalid("evidence trust file changed while reading"));
    }
    Ok(bytes)
}

#[cfg(not(unix))]
pub(crate) fn read_owner_file(
    _path: &Path,
    _identity: &AgentdIdentity,
) -> Result<Vec<u8>, AgentdError> {
    Err(invalid(
        "the kernel evidence trust-file profile currently requires Unix ownership checks",
    ))
}

fn current_time_millis() -> Result<u64, AgentdError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| invalid(&format!("system clock is before Unix epoch: {error}")))?
        .as_millis();
    u64::try_from(millis).map_err(|error| invalid(&format!("system clock overflow: {error}")))
}

fn evidence_error(error: codex_hepta_evidence::EvidenceError) -> AgentdError {
    invalid(&error.to_string())
}

fn invalid(message: &str) -> AgentdError {
    AgentdError::Invalid(format!("kernel.evidence: {message}"))
}
"""
write("codex-rs/hepta-agentd/src/evidence_trust.rs", EVIDENCE_TRUST)

PROCESS_LOCK = r"""//! Cross-process ownership and backup/write fencing for kernel.evidence.

use std::fs::File;
use std::path::Path;
use std::path::PathBuf;

use crate::AgentdError;

const OWNER_LOCK_FILE: &str = ".kernel-evidence.owner.lock";
const WRITER_FENCE_FILE: &str = ".kernel-evidence.writer.fence";

pub(crate) struct KernelEvidenceOwnerLock {
    #[allow(dead_code)]
    file: File,
}

pub(crate) struct KernelEvidenceWriteFence {
    path: PathBuf,
}

pub(crate) struct KernelEvidenceWritePermit {
    #[allow(dead_code)]
    file: File,
}

pub struct KernelEvidenceBackupFenceGuard {
    #[allow(dead_code)]
    file: File,
}

impl KernelEvidenceOwnerLock {
    pub(crate) fn acquire(home: &Path) -> Result<Self, AgentdError> {
        let file = open_private_lock(home, OWNER_LOCK_FILE)?;
        lock(&file, LockMode::Exclusive)?;
        Ok(Self { file })
    }
}

impl KernelEvidenceWriteFence {
    pub(crate) fn new(home: &Path) -> Result<Self, AgentdError> {
        let path = home.join(WRITER_FENCE_FILE);
        let file = open_private_lock(home, WRITER_FENCE_FILE)?;
        drop(file);
        Ok(Self { path })
    }

    pub(crate) fn acquire_writer(&self) -> Result<KernelEvidenceWritePermit, AgentdError> {
        let home = self
            .path
            .parent()
            .ok_or_else(|| invalid("writer fence has no owner directory"))?;
        let file = open_private_lock(home, WRITER_FENCE_FILE)?;
        lock(&file, LockMode::Shared)?;
        Ok(KernelEvidenceWritePermit { file })
    }
}

pub fn acquire_kernel_evidence_backup_fence(
    home: &Path,
) -> Result<KernelEvidenceBackupFenceGuard, AgentdError> {
    let file = open_private_lock(home, WRITER_FENCE_FILE)?;
    lock(&file, LockMode::Exclusive)?;
    Ok(KernelEvidenceBackupFenceGuard { file })
}

#[derive(Clone, Copy)]
enum LockMode {
    Shared,
    Exclusive,
}

#[cfg(unix)]
fn open_private_lock(home: &Path, file_name: &str) -> Result<File, AgentdError> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;

    let canonical_home = home.canonicalize()?;
    if canonical_home != home {
        return Err(invalid("kernel evidence lock home must be canonical"));
    }
    let home_metadata = std::fs::metadata(home)?;
    if !home_metadata.is_dir() || home_metadata.mode() & 0o077 != 0 {
        return Err(invalid("kernel evidence lock home must be private"));
    }
    let path = home.join(file_name);
    let file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .mode(0o600)
        .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
        .open(&path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file()
        || metadata.nlink() != 1
        || metadata.uid() != home_metadata.uid()
        || metadata.mode() & 0o077 != 0
    {
        return Err(invalid(
            "kernel evidence lock file is not private and owner-bound",
        ));
    }
    Ok(file)
}

#[cfg(not(unix))]
fn open_private_lock(_home: &Path, _file_name: &str) -> Result<File, AgentdError> {
    Err(invalid(
        "kernel evidence process and backup fencing currently requires Unix flock",
    ))
}

#[cfg(unix)]
fn lock(file: &File, mode: LockMode) -> Result<(), AgentdError> {
    use std::os::fd::AsRawFd;

    let operation = match mode {
        LockMode::Shared => libc::LOCK_SH | libc::LOCK_NB,
        LockMode::Exclusive => libc::LOCK_EX | libc::LOCK_NB,
    };
    let result = unsafe { libc::flock(file.as_raw_fd(), operation) };
    if result != 0 {
        return Err(invalid(match mode {
            LockMode::Shared => "kernel evidence backup fence is active",
            LockMode::Exclusive => "another kernel evidence owner or writer is active",
        }));
    }
    Ok(())
}

#[cfg(not(unix))]
fn lock(_file: &File, _mode: LockMode) -> Result<(), AgentdError> {
    Err(invalid(
        "kernel evidence process and backup fencing currently requires Unix flock",
    ))
}

fn invalid(message: &str) -> AgentdError {
    AgentdError::Invalid(format!("kernel.evidence: {message}"))
}
"""
write("codex-rs/hepta-agentd/src/evidence_process_lock.rs", PROCESS_LOCK)

# Register Agentd fencing module and public backup API.
replace_once(
    "codex-rs/hepta-agentd/src/lib.rs",
    "mod evidence_production;\n",
    "mod evidence_production;\nmod evidence_process_lock;\n",
)
if "pub use evidence_process_lock::acquire_kernel_evidence_backup_fence;" not in read(
    "codex-rs/hepta-agentd/src/lib.rs"
):
    text = read("codex-rs/hepta-agentd/src/lib.rs")
    marker = "mod evidence_trust;\n"
    if marker not in text:
        raise SystemExit("Agentd module marker drifted")
    text = text.replace(
        marker,
        marker
        + "pub use evidence_process_lock::acquire_kernel_evidence_backup_fence;\n",
        1,
    )
    write("codex-rs/hepta-agentd/src/lib.rs", text)

# Upgrade EvidenceHost to hold a production owner lock and per-append shared fence.
host = "codex-rs/hepta-agentd/src/evidence_host.rs"
text = read(host)
if "KernelEvidenceOwnerLock" not in text:
    text = text.replace(
        "use crate::evidence_trust::EvidenceTrust;\n",
        "use crate::evidence_process_lock::KernelEvidenceOwnerLock;\nuse crate::evidence_process_lock::KernelEvidenceWriteFence;\nuse crate::evidence_trust::EvidenceTrust;\n",
        1,
    )
    text = text.replace(
        """pub(crate) struct EvidenceHost {
    pub(crate) store: HeptaEvidenceStore,
    trust_file: PathBuf,
}""",
        """pub(crate) struct EvidenceHost {
    pub(crate) store: HeptaEvidenceStore,
    trust_file: PathBuf,
    require_signed_trust: bool,
    _owner_lock: Option<KernelEvidenceOwnerLock>,
    writer_fence: KernelEvidenceWriteFence,
}""",
        1,
    )
    text = text.replace(
        """        EvidenceTrust::load(&trust_file, identity)?;
        let production_profile = recovery_frontier.as_ref().is_some_and(""",
        """        let production_profile = recovery_frontier.as_ref().is_some_and(""",
        1,
    )
    marker = """        );
        let home = AbsolutePathBuf::from_absolute_path(&identity.home_root)?;"""
    replacement = """        );
        if production_profile {
            EvidenceTrust::load_signed(&trust_file, identity)?;
        } else {
            EvidenceTrust::load(&trust_file, identity)?;
        }
        let owner_lock = if production_profile {
            Some(KernelEvidenceOwnerLock::acquire(&identity.home_root)?)
        } else {
            None
        };
        let writer_fence = KernelEvidenceWriteFence::new(&identity.home_root)?;
        let home = AbsolutePathBuf::from_absolute_path(&identity.home_root)?;"""
    if marker not in text:
        raise SystemExit("EvidenceHost production profile marker drifted")
    text = text.replace(marker, replacement, 1)
    text = text.replace(
        """        Ok(Self { store, trust_file })
    }

    fn trust(&self, state: &AgentdState) -> Result<EvidenceTrust, AgentdError> {
        EvidenceTrust::load(&self.trust_file, state.identity())
    }""",
        """        Ok(Self {
            store,
            trust_file,
            require_signed_trust: production_profile,
            _owner_lock: owner_lock,
            writer_fence,
        })
    }

    fn trust(&self, state: &AgentdState) -> Result<EvidenceTrust, AgentdError> {
        if self.require_signed_trust {
            EvidenceTrust::load_signed(&self.trust_file, state.identity())
        } else {
            EvidenceTrust::load(&self.trust_file, state.identity())
        }
    }""",
        1,
    )
    text = text.replace(
        """    let evidence_id = host
        .store""",
        """    let _write_permit = host.writer_fence.acquire_writer()?;
    let evidence_id = host
        .store""",
        1,
    )
    text = text.replace(
        "let current_trust = host.trust(state)?.verification_bindings()?;",
        "let current_trust = host.trust(state)?;",
        1,
    )
    text = text.replace(
        "            &current_trust,\n",
        "            current_trust.verification_snapshot(),\n",
        1,
    )
write(host, text)

# Bind trust generation/predecessor, all-domain digest and backup image to frontier v2.
frontier = "codex-rs/hepta-evidence/src/frontier_v2.rs"
text = read(frontier)
if "issuer_trust_registry_generation" not in text:
    text = text.replace(
        "    pub issuer_trust_registry_sha256: Sha256Digest,\n",
        "    pub issuer_trust_registry_sha256: Sha256Digest,\n    pub issuer_trust_registry_generation: u64,\n    pub issuer_trust_registry_predecessor_sha256: Option<Sha256Digest>,\n    pub authoritative_store_sha256: Sha256Digest,\n",
        1,
    )
    text = text.replace(
        "    pub backup_publication_sha256: Sha256Digest,\n",
        "    pub backup_publication_sha256: Sha256Digest,\n    pub backup_image_sha256: Sha256Digest,\n",
        1,
    )
    text = text.replace(
        '            ("issuer trust registry", &self.issuer_trust_registry_sha256),\n',
        '            ("issuer trust registry", &self.issuer_trust_registry_sha256),\n            ("authoritative store", &self.authoritative_store_sha256),\n',
        1,
    )
    text = text.replace(
        '            ("backup publication", &self.backup_publication_sha256),\n',
        '            ("backup publication", &self.backup_publication_sha256),\n            ("backup image", &self.backup_image_sha256),\n',
        1,
    )
    text = text.replace(
        """        if self.ledger_root_sha256 != evidence_recovery_ledger_root_v2(&self.snapshot) {
            return Err(invalid("frontier ledger root does not match the snapshot"));
        }""",
        """        if self.ledger_root_sha256 != evidence_recovery_ledger_root_v2(&self.snapshot) {
            return Err(invalid("frontier ledger root does not match the snapshot"));
        }
        if self.issuer_trust_registry_generation == 0 {
            return Err(invalid("issuer trust registry generation must be positive"));
        }
        match (
            self.issuer_trust_registry_generation,
            self.issuer_trust_registry_predecessor_sha256.as_ref(),
        ) {
            (1, None) => {}
            (1, Some(_)) | (_, None) => {
                return Err(invalid(
                    "issuer trust predecessor is inconsistent with its generation",
                ));
            }
            (_, Some(predecessor)) if !valid_sha256(predecessor) => {
                return Err(invalid("issuer trust predecessor digest is invalid"));
            }
            _ => {}
        }""",
        1,
    )
    text = text.replace(
        "    issuer_trust_registry_sha256: &'a Sha256Digest,\n",
        "    issuer_trust_registry_sha256: &'a Sha256Digest,\n    issuer_trust_registry_generation: u64,\n    issuer_trust_registry_predecessor_sha256: &'a Option<Sha256Digest>,\n    authoritative_store_sha256: &'a Sha256Digest,\n",
        1,
    )
    text = text.replace(
        "    backup_publication_sha256: &'a Sha256Digest,\n",
        "    backup_publication_sha256: &'a Sha256Digest,\n    backup_image_sha256: &'a Sha256Digest,\n",
        1,
    )
    text = text.replace(
        """        issuer_trust_registry_sha256: &frontier.issuer_trust_registry_sha256,
        frontier_signer_registry_sha256:""",
        """        issuer_trust_registry_sha256: &frontier.issuer_trust_registry_sha256,
        issuer_trust_registry_generation: frontier.issuer_trust_registry_generation,
        issuer_trust_registry_predecessor_sha256:
            &frontier.issuer_trust_registry_predecessor_sha256,
        authoritative_store_sha256: &frontier.authoritative_store_sha256,
        frontier_signer_registry_sha256:""",
        1,
    )
    text = text.replace(
        "        backup_publication_sha256: &frontier.backup_publication_sha256,\n",
        "        backup_publication_sha256: &frontier.backup_publication_sha256,\n        backup_image_sha256: &frontier.backup_image_sha256,\n",
        1,
    )
write(frontier, text)

# Upgrade production admission and durable backup witness fields.
production = "codex-rs/hepta-agentd/src/evidence_production.rs"
text = read(production)
if "backup_image_sha256" not in text:
    text = text.replace(
        """    snapshot_sha256: Sha256Digest,
    backend_identity_sha256: Sha256Digest,
    published_at_unix_ms: u64,""",
        """    snapshot_sha256: Sha256Digest,
    authoritative_store_sha256: Sha256Digest,
    backup_image_sha256: Sha256Digest,
    backup_object_version: String,
    backup_storage_etag_sha256: Sha256Digest,
    backend_identity_sha256: Sha256Digest,
    published_at_unix_ms: u64,""",
        1,
    )
    text = text.replace(
        "let (_, issuer_trust_sha256) = EvidenceTrust::load_with_digest(issuer_trust_file, identity)?;",
        "let (issuer_trust, issuer_trust_sha256) =\n        EvidenceTrust::load_signed_with_digest(issuer_trust_file, identity)?;",
        1,
    )
    text = text.replace(
        """        || frontier.issuer_trust_registry_sha256 != issuer_trust_sha256
        || frontier.frontier_signer_registry_sha256""",
        """        || frontier.issuer_trust_registry_sha256 != issuer_trust_sha256
        || frontier.issuer_trust_registry_generation != issuer_trust.generation()
        || frontier.issuer_trust_registry_predecessor_sha256.as_ref()
            != issuer_trust.predecessor_sha256()
        || frontier.frontier_signer_registry_sha256""",
        1,
    )
    text = text.replace(
        """    let actual_snapshot = store.recovery_snapshot().await.map_err(evidence_error)?;
    if actual_snapshot != frontier.snapshot
        || evidence_recovery_ledger_root_v2(&actual_snapshot) != frontier.ledger_root_sha256
    {""",
        """    let actual_state = store.recovery_state_v2().await.map_err(evidence_error)?;
    if actual_state.snapshot != frontier.snapshot
        || actual_state.authoritative_store_sha256 != frontier.authoritative_store_sha256
        || evidence_recovery_ledger_root_v2(&actual_state.snapshot)
            != frontier.ledger_root_sha256
    {""",
        1,
    )
    text = text.replace(
        """    validate_digest(&backup.snapshot_sha256, "backup snapshot")?;
    validate_digest(&backup.backend_identity_sha256, "backup backend identity")?;""",
        """    validate_digest(&backup.snapshot_sha256, "backup snapshot")?;
    validate_digest(
        &backup.authoritative_store_sha256,
        "backup authoritative store",
    )?;
    validate_digest(&backup.backup_image_sha256, "backup image")?;
    validate_digest(
        &backup.backup_storage_etag_sha256,
        "backup storage etag",
    )?;
    validate_digest(&backup.backend_identity_sha256, "backup backend identity")?;""",
        1,
    )
    text = text.replace(
        """        || backup.snapshot_sha256 != Sha256Digest::for_bytes(&snapshot_bytes)
        || backup.backend_identity_sha256 != frontier.backend_identity_sha256""",
        """        || backup.snapshot_sha256 != Sha256Digest::for_bytes(&snapshot_bytes)
        || backup.authoritative_store_sha256 != frontier.authoritative_store_sha256
        || backup.backup_image_sha256 != frontier.backup_image_sha256
        || backup.backup_object_version.is_empty()
        || backup.backup_object_version.len() > 512
        || backup.backup_object_version == "latest"
        || backup.backend_identity_sha256 != frontier.backend_identity_sha256""",
        1,
    )
write(production, text)

# Add new frontier fields to test/build literals. Production publishers are
# external; checked-in literals are qualification fixtures and use generation 1.
for target in [
    "codex-rs/hepta-evidence/src/frontier_v2_tests.rs",
    "codex-rs/hepta-evidence/src/frontier_backend_tests.rs",
    "codex-rs/hepta-evidence/src/frontier_backend_file_tests.rs",
    "codex-rs/hepta-evidence/src/frontier_acceptance_tests.rs",
    "codex-rs/hepta-evidence/tests/frontier_backend_multiprocess.rs",
    "codex-rs/hepta-agentd/src/evidence_frontier_signers_tests.rs",
    "codex-rs/hepta-agentd/src/evidence_production_tests.rs",
]:
    value = read(target)
    if "EvidenceRecoveryFrontierV2" not in value:
        continue
    if "issuer_trust_registry_generation:" not in value:
        value = re.sub(
            r"(?m)^(\s*)issuer_trust_registry_sha256: ([^\n]+),$",
            r"\1issuer_trust_registry_sha256: \2,\n\1issuer_trust_registry_generation: 1,\n\1issuer_trust_registry_predecessor_sha256: None,\n\1authoritative_store_sha256: Sha256Digest::for_bytes(b\"authoritative-store\"),",
            value,
        )
    if "backup_image_sha256:" not in value:
        value = re.sub(
            r"(?m)^(\s*)backup_publication_sha256: ([^\n]+),$",
            r"\1backup_publication_sha256: \2,\n\1backup_image_sha256: Sha256Digest::for_bytes(b\"backup-image\"),",
            value,
        )
    write(target, value)

# Unit backup fixture fields.
prod_tests = "codex-rs/hepta-agentd/src/evidence_production_tests.rs"
value = read(prod_tests)
if "backup_object_version:" not in value:
    value = re.sub(
        r"(?m)^(\s*)snapshot_sha256: ([^\n]+),$",
        r"\1snapshot_sha256: \2,\n\1authoritative_store_sha256: frontier.authoritative_store_sha256.clone(),\n\1backup_image_sha256: frontier.backup_image_sha256.clone(),\n\1backup_object_version: \"object-version:immutable-1\".to_string(),\n\1backup_storage_etag_sha256: Sha256Digest::for_bytes(b\"backup-etag\"),",
        value,
    )
write(prod_tests, value)

# Production trust fixtures must be signed registry v2. Existing qualification
# and developer profiles may continue using legacy v1; production rejects it.

# Update status source paths/capabilities without advancing any gate.
status_path = path("qualification/kernel-evidence/STATUS_SOURCE.json")
status = json.loads(status_path.read_text(encoding="utf-8"))
for source in [
    "codex-rs/hepta-agentd/src/evidence_process_lock.rs",
    "codex-rs/hepta-evidence/src/trust_snapshot.rs",
    "scripts/kernel_evidence_phase2_hardening.py",
]:
    if source not in status["sourcePaths"]:
        status["sourcePaths"].append(source)
status["sourcePaths"] = sorted(status["sourcePaths"])
status["capabilities"].update(
    {
        "sealedVerifiedTrustSnapshot": True,
        "signedMonotonicIssuerTrustRegistry": True,
        "singleTransactionRecoverySnapshot": True,
        "authoritativeStoreDigest": True,
        "backupImageDigestBinding": True,
        "crossProcessOwnerLock": True,
        "backupWriterFence": True,
    }
)
for flag in [
    "exactSourceQualified",
    "mergeCandidateQualified",
    "independentAcceptance",
    "externalFrontierActive",
    "backupRestoreDrilled",
    "canaryAccepted",
    "releaseApproved",
]:
    status[flag] = False
status["workflowRunId"] = None
status["artifactDigest"] = None
status_path.write_text(
    json.dumps(status, indent=2, sort_keys=False) + "\n", encoding="utf-8"
)

# Documentation deltas are intentionally explicit and do not claim execution.
for name, section in {
    "docs/modules/kernel.evidence/TECHNICAL.md": """

## Trust and recovery hardening overlay (2026-09-27)

Production verification accepts a sealed `VerifiedEvidenceTrustSnapshot`, not a caller-created binding vector. The production registry uses schema v2 with a positive generation, predecessor digest after generation one, canonical ordering, bounded threshold signers and Ed25519 signatures. Its generation, predecessor and digest are pinned by the signed external recovery frontier.

`recovery_state_v2` computes migration, qualification, replay and all-authoritative-table digests in one SQLite read transaction. Local recovery identity and accepted-frontier witnesses are excluded from the authoritative content digest because admission writes them after comparison; they remain independently constrained. The frontier also binds an immutable backup-image digest. Production Agentd holds a non-blocking cross-process owner lock, and every append obtains a shared writer-fence lock so an external backup process can take the exclusive fence before copying the image.

These are source capabilities only. External storage deployment, restore drills, independent acceptance, canary and release remain false until separately evidenced.
""",
    "docs/lane-a-foundation/kernel.evidence/CURRENT_IMPLEMENTATION.md": """

## 2026-09 trust/recovery closure

The current hardening branch adds a sealed verified trust snapshot, signed monotonic trust registry v2, single-transaction authoritative-store recovery digest, immutable backup-image binding, a production single-owner process lock and a shared/exclusive backup writer fence. Legacy unsigned trust remains readable only by explicitly non-production qualification profiles. Production fails closed on legacy trust, registry rollback, predecessor mismatch, stale snapshot, owner-lock contention or an active backup fence.

No operational or independent gate is advanced by source presence.
""",
    "qualification/kernel-evidence/TRACEABILITY.md": """

## Phase-two trust and recovery closure

- `VerifiedEvidenceTrustSnapshot` is sealed; public qualification verification cannot consume a raw binding slice outside evidence-crate unit tests.
- Signed trust registry v2 binds generation, predecessor, issuer/key/role inventory and a threshold signer policy; production rejects schema v1.
- `EvidenceRecoveryFrontierV2` binds trust generation/predecessor, a one-transaction authoritative-store digest and immutable backup-image digest.
- `KernelEvidenceOwnerLock` and `KernelEvidenceWriteFence` provide cross-process single-owner and backup/write exclusion on the Unix production profile.
- All status gates remain false until exact-candidate execution and external ceremonies are retained.
""",
}.items():
    value = read(name)
    heading = section.strip().splitlines()[0]
    if heading not in value:
        write(name, value.rstrip() + section + "\n")

print("phase-two hardening applied; status gates preserved false")
