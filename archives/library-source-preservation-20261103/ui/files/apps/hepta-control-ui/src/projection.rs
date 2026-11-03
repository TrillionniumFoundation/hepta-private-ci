use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

use crate::canonical::{
    CanonicalLimits, assert_safe_integer, assert_sha256, assert_stable_identifier,
    canonical_json_with_limits, digest_canonical_with_limits, parse_canonical_json_with_limits,
    value_safe_integer,
};
use crate::contract::Session;
use crate::error::{ControlError, ErrorCode, Result, invalid};

pub const MAX_MODULES: usize = 1000;

pub fn runtime_canonical_limits() -> CanonicalLimits {
    CanonicalLimits {
        max_entries: 5 * MAX_MODULES + 16,
        ..CanonicalLimits::default()
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RuntimeStatus {
    Ready,
    Degraded,
    Quarantined,
    Recovering,
    Unavailable,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ModuleProjection {
    pub id: String,
    pub status: RuntimeStatus,
    pub revision: u64,
    pub semantic_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RuntimeProjection {
    pub generation: u64,
    pub revision: u64,
    pub modules: Vec<ModuleProjection>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Snapshot {
    pub session_id: String,
    pub connection_generation: u64,
    pub generation: u64,
    pub revision: u64,
    pub semantic_digest: String,
    pub modules: Vec<ModuleProjection>,
    pub observed_at: Option<String>,
}

pub fn project_runtime(value: &Value) -> Result<RuntimeProjection> {
    let encoded = canonical_json_with_limits(value, runtime_canonical_limits())?;
    let mut runtime: RuntimeProjection = serde_json::from_str(&encoded).map_err(|_| invalid())?;
    assert_safe_integer(runtime.generation, /*min*/ 1)?;
    assert_safe_integer(runtime.revision, /*min*/ 1)?;
    if runtime.modules.len() > MAX_MODULES {
        return Err(invalid());
    }
    for module in &runtime.modules {
        assert_stable_identifier(&module.id)?;
        assert_safe_integer(module.revision, /*min*/ 1)?;
        assert_sha256(&module.semantic_digest)?;
    }
    runtime
        .modules
        .sort_by(|left, right| left.id.cmp(&right.id));
    if runtime
        .modules
        .windows(2)
        .any(|pair| pair[0].id == pair[1].id)
    {
        return Err(invalid());
    }
    Ok(runtime)
}

pub fn project_runtime_from_local_canonical_json(text: &str) -> Result<RuntimeProjection> {
    project_runtime(&parse_canonical_json_with_limits(
        text,
        CanonicalLimits {
            max_depth: 8,
            max_string_bytes: 4096,
            ..runtime_canonical_limits()
        },
    )?)
}

pub fn digest_runtime_projection(runtime: &RuntimeProjection) -> Result<String> {
    let value = serde_json::to_value(runtime).map_err(|_| invalid())?;
    let runtime = project_runtime(&value)?;
    digest_canonical_with_limits(
        "hepta.ui-control.runtime-projection.v1",
        &serde_json::to_value(runtime).map_err(|_| invalid())?,
        runtime_canonical_limits(),
    )
}

pub fn normalize_snapshot(value: &Value, session: &Session) -> Result<Snapshot> {
    let object = value.as_object().ok_or_else(invalid)?;
    canonical_json_with_limits(value, runtime_canonical_limits())?;
    let session_id = object
        .get("sessionId")
        .and_then(Value::as_str)
        .ok_or_else(invalid)?;
    assert_stable_identifier(session_id)?;
    assert_stable_identifier(&session.session_id)?;
    if session_id != session.session_id {
        return Err(invalid());
    }
    let connection_generation =
        value_safe_integer(object.get("connectionGeneration"), /*min*/ 1)?;
    if connection_generation != session.connection_generation {
        return Err(ControlError::new(ErrorCode::StaleGeneration));
    }
    let runtime = project_runtime(&json!({ "generation": object.get("generation"),
        "revision": object.get("revision"), "modules": object.get("modules") }))?;
    let semantic_digest = digest_canonical_with_limits(
        "hepta.ui-control.runtime-snapshot.v1",
        &json!({ "sessionId": session_id, "connectionGeneration": connection_generation,
            "generation": runtime.generation, "revision": runtime.revision, "modules": runtime.modules }),
        runtime_canonical_limits(),
    )?;
    if let Some(declared) = object.get("semanticDigest") {
        let declared = declared.as_str().ok_or_else(invalid)?;
        assert_sha256(declared)?;
        if declared != semantic_digest {
            return Err(ControlError::new(ErrorCode::SnapshotDrift));
        }
    }
    let snapshot = Snapshot {
        session_id: session_id.to_owned(),
        connection_generation,
        generation: runtime.generation,
        revision: runtime.revision,
        semantic_digest,
        modules: runtime.modules,
        observed_at: object
            .get("observedAt")
            .and_then(Value::as_str)
            .map(str::to_owned),
    };
    canonical_json_with_limits(
        &serde_json::to_value(&snapshot).map_err(|_| invalid())?,
        runtime_canonical_limits(),
    )?;
    Ok(snapshot)
}

pub fn validate_snapshot_transition(
    previous: Option<&Snapshot>,
    next: Snapshot,
) -> Result<Snapshot> {
    let Some(previous) = previous else {
        return Ok(next);
    };
    if next.session_id != previous.session_id
        || next.connection_generation < previous.connection_generation
    {
        return Err(ControlError::new(ErrorCode::StaleGeneration));
    }
    if next.connection_generation > previous.connection_generation {
        return Ok(next);
    }
    if next.generation < previous.generation {
        return Err(ControlError::new(ErrorCode::StaleGeneration));
    }
    if next.generation > previous.generation {
        return Ok(next);
    }
    if next.revision < previous.revision {
        return Err(ControlError::new(ErrorCode::StaleRevision));
    }
    if next.revision > previous.revision {
        return Ok(next);
    }
    if next.semantic_digest != previous.semantic_digest {
        return Err(ControlError::new(ErrorCode::SnapshotDrift));
    }
    Ok(previous.clone())
}

#[cfg(test)]
#[path = "projection_tests.rs"]
mod tests;
