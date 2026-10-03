//! Identified creation observations keep the original requested configuration.
use super::ThreadSource;
use super::ThreadStartParams;
use super::ThreadStartResponse;
use crate::JsonSchema;
use crate::TS;
use codex_experimental_api_macros::ExperimentalApi;
use codex_utils_absolute_path::AbsolutePathBuf;
use serde::Deserialize;
use serde::Serialize;

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ThreadCreationObserveParams {
    pub idempotency_key: String,
    pub expected_parameters_sha256: String,
    #[ts(optional = nullable)]
    pub expected_project_id: Option<String>,
    pub expected_cwd: AbsolutePathBuf,
    #[ts(optional = nullable)]
    pub expected_thread_source: Option<ThreadSource>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, JsonSchema, TS, ExperimentalApi)]
#[serde(tag = "type", rename_all = "camelCase")]
#[ts(tag = "type", rename_all = "camelCase", export_to = "v2/")]
pub enum ThreadCreationObserveOutcome {
    #[serde(rename_all = "camelCase")]
    #[ts(rename_all = "camelCase")]
    Pending {
        thread_id: String,
    },
    #[serde(rename_all = "camelCase")]
    #[ts(rename_all = "camelCase")]
    Materialized {
        thread_id: String,
    },
    Created {
        response: Box<ThreadStartResponse>,
    },
    #[serde(rename_all = "camelCase")]
    #[ts(rename_all = "camelCase")]
    Deleted {
        thread_id: String,
    },
    #[serde(rename_all = "camelCase")]
    #[ts(rename_all = "camelCase")]
    Abandoned {
        thread_id: String,
    },
    Missing,
    Unknown,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, JsonSchema, TS, ExperimentalApi)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ThreadCreationObserveResponse {
    pub idempotency_key: String,
    pub parameters_sha256: String,
    pub outcome: ThreadCreationObserveOutcome,
}

impl ThreadStartParams {
    /// Canonical complete requested parameters; the correlation key is excluded.
    /// Sorting recursively also covers the client's unordered config map.
    pub fn canonical_creation_parameters(&self) -> serde_json::Result<Vec<u8>> {
        let mut params = self.clone();
        params.idempotency_key = None;
        // Match the original configuration owner's lexical cwd normalization.
        // Otherwise a valid /a/../b request would bind a scope that its actual
        // rollout and receipt can never satisfy after creation.
        params.cwd = params
            .cwd
            .map(AbsolutePathBuf::from_absolute_path)
            .transpose()
            .map_err(serde::ser::Error::custom)?
            .map(|cwd| cwd.as_path().to_string_lossy().into_owned());
        fn canonical(value: serde_json::Value) -> serde_json::Value {
            match value {
                serde_json::Value::Object(map) => serde_json::Value::Object(
                    map.into_iter()
                        .map(|(key, value)| (key, canonical(value)))
                        .collect::<std::collections::BTreeMap<_, _>>()
                        .into_iter()
                        .collect(),
                ),
                serde_json::Value::Array(values) => {
                    serde_json::Value::Array(values.into_iter().map(canonical).collect())
                }
                value => value,
            }
        }
        // None means no requested override. Omit these top-level absent fields
        // so an additive future optional parameter cannot change old hashes.
        // Explicit serviceTier:null remains a distinct requested override;
        // nested config nulls are also preserved exactly.
        let preserve_service_tier_null = params.service_tier == Some(None);
        let mut value = serde_json::to_value(params)?;
        if let serde_json::Value::Object(map) = &mut value {
            map.retain(|key, value| {
                !value.is_null() || (key == "serviceTier" && preserve_service_tier_null)
            });
        }
        serde_json::to_vec(&canonical(value))
    }
}

#[cfg(test)]
#[path = "thread_creation_tests.rs"]
mod tests;
