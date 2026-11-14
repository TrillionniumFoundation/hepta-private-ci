//! Canonical values accepted by the original Pocket4 bound-text receiver.

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

/// Original cell incarnation, independently read by the native receiver.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AndroidCellGeneration {
    pub boot_id: String,
    pub init_start_ticks: String,
    pub mount_namespace: String,
    pub pid_namespace: String,
    pub time_namespace: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AndroidApplicationGeneration {
    pub pid: u64,
    pub process_name: String,
    pub start_ticks: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AndroidNativeWindow {
    pub activity: String,
    pub bounds: [u32; 4],
    pub display_id: u32,
    pub package: String,
    pub window_token: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AndroidNativeTextNode {
    pub bounds: [u32; 4],
    pub class: String,
    pub node_sha256: Sha256Digest,
    pub prior_text_sha256: Sha256Digest,
    pub resource_id: String,
}

/// A non-atomic native observation. It is input to an intent, never authority.
/// Field order is part of canonical UTF-8 compatibility with the original
/// Python/Java receiver; serialization is lexicographic at every object level.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AndroidNativeTextObservation {
    pub application: AndroidApplicationGeneration,
    pub atomic_snapshot: bool,
    pub generation: AndroidCellGeneration,
    pub observed_elapsed_ms: u64,
    pub schema_version: u16,
    pub scope_sha256: Sha256Digest,
    pub target: AndroidNativeTextNode,
    pub window: AndroidNativeWindow,
}

impl AndroidNativeTextObservation {
    pub fn destination_id(&self) -> Result<String, String> {
        #[derive(Serialize)]
        struct Scope<'a> {
            application: &'a AndroidApplicationGeneration,
            generation: &'a AndroidCellGeneration,
            package: &'a str,
            resource_id: &'a str,
        }
        let raw = serde_json::to_vec(&Scope {
            application: &self.application,
            generation: &self.generation,
            package: &self.window.package,
            resource_id: &self.target.resource_id,
        })
        .map_err(|e| e.to_string())?;
        Ok(format!(
            "pocket4.android:{}",
            Sha256Digest::for_bytes(&raw).as_str()
        ))
    }

    pub fn validate(&self) -> Result<(), String> {
        for digest in [
            &self.scope_sha256,
            &self.target.prior_text_sha256,
            &self.target.node_sha256,
        ] {
            Sha256Digest::parse(digest.as_str())?;
        }
        let generation = &self.generation;
        let package = &self.window.package;
        let valid_bounds = |bounds: [u32; 4]| {
            bounds[0] < bounds[2] && bounds[1] < bounds[3] && bounds[2] <= 8192 && bounds[3] <= 8192
        };
        let digits = |value: &str| {
            !value.is_empty() && value.len() <= 20 && value.bytes().all(|b| b.is_ascii_digit())
        };
        let namespace = |value: &str, kind: &str| {
            value
                .strip_prefix(kind)
                .and_then(|v| v.strip_suffix(']'))
                .is_some_and(digits)
        };
        let resource_prefix = format!("{package}:id/");
        let valid_resource = self
            .target
            .resource_id
            .strip_prefix(&resource_prefix)
            .is_some_and(|id| {
                !id.is_empty()
                    && id.len() <= 256
                    && id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_')
                    && !id.as_bytes()[0].is_ascii_digit()
            });
        if self.schema_version != 1
            || self.atomic_snapshot
            || self.observed_elapsed_ms == 0
            || self.observed_elapsed_ms >= 1 << 53
            || generation.boot_id.len() != 36
            || generation.boot_id.bytes().enumerate().any(|(i, b)| {
                if matches!(i, 8 | 13 | 18 | 23) {
                    b != b'-'
                } else {
                    !b.is_ascii_digit() && !(b'a'..=b'f').contains(&b)
                }
            })
            || !digits(&generation.init_start_ticks)
            || !namespace(&generation.mount_namespace, "mnt:[")
            || !namespace(&generation.pid_namespace, "pid:[")
            || !namespace(&generation.time_namespace, "time:[")
            || self.application.pid == 0
            || self.application.pid > u32::MAX as u64
            || self.application.process_name != *package
            || !digits(&self.application.start_ticks)
            || !valid_package(package)
            || self.window.display_id != 0
            || self.window.activity.is_empty()
            || self.window.activity.len() > 512
            || self.window.activity.contains('\0')
            || self.window.window_token.is_empty()
            || self.window.window_token.len() > 32
            || self
                .window
                .window_token
                .bytes()
                .any(|b| !b.is_ascii_digit() && !(b'a'..=b'f').contains(&b))
            || !valid_bounds(self.window.bounds)
            || !valid_bounds(self.target.bounds)
            || self.target.bounds[0] < self.window.bounds[0]
            || self.target.bounds[1] < self.window.bounds[1]
            || self.target.bounds[2] > self.window.bounds[2]
            || self.target.bounds[3] > self.window.bounds[3]
            || !valid_resource
            || self.target.class.is_empty()
            || self.target.class.len() > 512
            || self.target.class.contains('\0')
        {
            return Err("invalid native Android text observation".to_string());
        }
        #[derive(Serialize)]
        struct Node<'a> {
            bounds: [u32; 4],
            class: &'a str,
            prior_text_sha256: &'a Sha256Digest,
            resource_id: &'a str,
        }
        let raw = serde_json::to_vec(&Node {
            bounds: self.target.bounds,
            class: &self.target.class,
            prior_text_sha256: &self.target.prior_text_sha256,
            resource_id: &self.target.resource_id,
        })
        .map_err(|e| e.to_string())?;
        if Sha256Digest::for_bytes(&raw) != self.target.node_sha256 {
            return Err("native Android node hash mismatch".to_string());
        }
        Ok(())
    }

    pub(super) fn same_target(&self, other: &Self) -> bool {
        self.generation == other.generation
            && self.application == other.application
            && self.window == other.window
            && self.target.resource_id == other.target.resource_id
            && self.target.class == other.target.class
            && self.target.bounds == other.target.bounds
    }
}

pub(super) fn valid_package(value: &str) -> bool {
    value.len() <= 256
        && value.contains('.')
        && value.split('.').all(|part| {
            !part.is_empty()
                && !part.as_bytes()[0].is_ascii_digit()
                && part.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_')
        })
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AndroidSetTextV1 {
    pub action: String,
    pub destination_id: String,
    pub expires_elapsed_ms: u64,
    pub observation: AndroidNativeTextObservation,
    pub operation_id: String,
    pub schema_version: u16,
    pub value: String,
}

impl AndroidSetTextV1 {
    pub fn to_json(&self) -> Result<String, String> {
        self.observation.validate()?;
        if self.schema_version != 1
            || self.action != "set_text"
            || self.destination_id != self.observation.destination_id()?
            || self.value.len() > 4096
            || self.value.contains('\0')
            || self.operation_id.is_empty()
            || self.operation_id.len() > 128
            || self
                .operation_id
                .bytes()
                .any(|b| !b.is_ascii_alphanumeric() && !b"._:-".contains(&b))
            || self.expires_elapsed_ms <= self.observation.observed_elapsed_ms
            || self.expires_elapsed_ms - self.observation.observed_elapsed_ms > 30000
            || self.expires_elapsed_ms >= 1 << 53
        {
            return Err("invalid original Android text payload".to_string());
        }
        let raw = serde_json::to_string(self).map_err(|e| e.to_string())?;
        if raw.len() > 16384 {
            return Err("Android text payload exceeds its bound".to_string());
        }
        Ok(raw)
    }

    pub fn from_json(raw: &str) -> Result<Self, String> {
        if raw.is_empty() || raw.len() > 16384 {
            return Err("Android text payload exceeds its bound".to_string());
        }
        let value: Self =
            serde_json::from_str(raw).map_err(|_| "invalid Android text payload schema")?;
        if value.to_json()? != raw {
            return Err("Android text payload is not canonical UTF-8".to_string());
        }
        Ok(value)
    }
}
