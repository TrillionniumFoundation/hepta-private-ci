use crate::JsonSchema;
use crate::TS;
use serde::Deserialize;
use serde::Serialize;

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ThreadBackgroundTerminalsTerminateObservedParams {
    pub thread_id: String,
    pub process_id: String,
    /// Required positive observation budget, in milliseconds. The server starts
    /// it once at request ingress, including queueing and owner cleanup.
    #[serde(deserialize_with = "positive_milliseconds")]
    #[schemars(range(min = 1))]
    pub observation_timeout_ms: u32,
}

fn positive_milliseconds<'de, D>(deserializer: D) -> Result<u32, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let value = u32::deserialize(deserializer)?;
    if value == 0 {
        return Err(serde::de::Error::custom(
            "observationTimeoutMs must be positive",
        ));
    }
    Ok(value)
}

#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(rename_all = "camelCase", export_to = "v2/")]
pub enum ThreadBackgroundTerminalsTerminateObservedStatus {
    /// The original process exited and its manager cleanup finished in budget.
    Confirmed,
    /// No such confirmation. This does not establish that no effect occurred,
    /// that the process exited, or that its owner or handle can be reused.
    NotConfirmed,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ThreadBackgroundTerminalsTerminateObservedResponse {
    pub status: ThreadBackgroundTerminalsTerminateObservedStatus,
}

#[cfg(test)]
#[path = "thread_termination_observed_tests.rs"]
mod tests;
