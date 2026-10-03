//! Inactive source-side publication state for the versioned run bridge.
//!
//! A caller must persist a returned transition before replacing its live state
//! or acknowledging it. These values neither perform I/O nor prove authority,
//! persistence, physical termination, or permission to disclose output.
use serde::Deserialize;
use serde::Serialize;
use serde::de::DeserializeSeed;

use crate::RUN_BRIDGE_SCHEMA_VERSION;
use crate::RunBridgeAcknowledgementV1;
use crate::RunBridgeBindingV1;
use crate::RunBridgeError;
use crate::RunBridgeLogicalOutcomeV1;
use crate::RunBridgePrimaryV1;
use crate::RunBridgePublicationKindV1;
use crate::RunBridgeQualificationConflictV1;

const MAX_SNAPSHOT_BYTES: usize = 16 * 1024;
const MAX_OBJECT_ENTRIES: usize = 16;
const MAX_KEY_BYTES: usize = 64;
const MAX_STRING_BYTES: usize = 512;
const MAX_OBJECT_DEPTH: usize = 3;

/// Bounded immutable publication history and its outstanding delivery facts.
/// Deserialization validates all cross-field relationships before adoption.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct RunBridgeOutboxV1 {
    schema_version: u32,
    binding: RunBridgeBindingV1,
    primary: RunBridgePrimaryV1,
    primary_ack: Option<RunBridgeAcknowledgementV1>,
    conflict: Option<RunBridgeQualificationConflictV1>,
    conflict_ack: Option<RunBridgeAcknowledgementV1>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredOutboxV1 {
    schema_version: u32,
    binding: RunBridgeBindingV1,
    primary: RunBridgePrimaryV1,
    #[serde(deserialize_with = "required_option")]
    primary_ack: Option<RunBridgeAcknowledgementV1>,
    #[serde(deserialize_with = "required_option")]
    conflict: Option<RunBridgeQualificationConflictV1>,
    #[serde(deserialize_with = "required_option")]
    conflict_ack: Option<RunBridgeAcknowledgementV1>,
}

/// Source facts accepted only after their separate owner authorization checks.
#[derive(Clone, Debug)]
pub enum RunBridgeOutboxChangeV1 {
    QueueConflict(RunBridgeQualificationConflictV1),
    AcknowledgePrimary(RunBridgeAcknowledgementV1),
    AcknowledgeConflict(RunBridgeAcknowledgementV1),
}

// This JSON snapshot has no sequence-valued fields. Preserve duplicate-key
// rejection recursively and reject positional struct arrays before typed hydration.
struct SnapshotValue(serde_json::Value);

fn required_option<'de, D, T>(deserializer: D) -> Result<Option<T>, D::Error>
where
    D: serde::Deserializer<'de>,
    T: Deserialize<'de>,
{
    Option::<T>::deserialize(deserializer)
}

struct SnapshotSeed {
    depth: usize,
}

impl<'de> DeserializeSeed<'de> for SnapshotSeed {
    type Value = SnapshotValue;
    fn deserialize<D: serde::Deserializer<'de>>(
        self,
        deserializer: D,
    ) -> Result<Self::Value, D::Error> {
        struct Visitor {
            depth: usize,
        }
        impl<'de> serde::de::Visitor<'de> for Visitor {
            type Value = SnapshotValue;
            fn expecting(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                f.write_str("a run bridge JSON snapshot without positional arrays")
            }
            fn visit_map<M: serde::de::MapAccess<'de>>(
                self,
                mut map: M,
            ) -> Result<Self::Value, M::Error> {
                if self.depth >= MAX_OBJECT_DEPTH {
                    return Err(serde::de::Error::custom(
                        "run bridge snapshot depth exceeded",
                    ));
                }
                let mut object = serde_json::Map::new();
                while let Some(key) = map.next_key::<String>()? {
                    if object.len() >= MAX_OBJECT_ENTRIES || key.len() > MAX_KEY_BYTES {
                        return Err(serde::de::Error::custom(
                            "run bridge snapshot object bound exceeded",
                        ));
                    }
                    if object.contains_key(&key) {
                        return Err(serde::de::Error::custom(
                            "duplicate run bridge snapshot key",
                        ));
                    }
                    let value = map.next_value_seed(SnapshotSeed {
                        depth: self.depth + 1,
                    })?;
                    object.insert(key, value.0);
                }
                Ok(SnapshotValue(serde_json::Value::Object(object)))
            }
            fn visit_str<E: serde::de::Error>(self, value: &str) -> Result<Self::Value, E> {
                if value.len() > MAX_STRING_BYTES {
                    return Err(E::custom("run bridge snapshot string bound exceeded"));
                }
                Ok(SnapshotValue(serde_json::Value::String(value.to_string())))
            }
            fn visit_string<E: serde::de::Error>(self, value: String) -> Result<Self::Value, E> {
                if value.len() > MAX_STRING_BYTES {
                    return Err(E::custom("run bridge snapshot string bound exceeded"));
                }
                Ok(SnapshotValue(serde_json::Value::String(value)))
            }
            fn visit_u64<E: serde::de::Error>(self, value: u64) -> Result<Self::Value, E> {
                Ok(SnapshotValue(value.into()))
            }
            fn visit_i64<E: serde::de::Error>(self, value: i64) -> Result<Self::Value, E> {
                Ok(SnapshotValue(value.into()))
            }
            fn visit_bool<E: serde::de::Error>(self, value: bool) -> Result<Self::Value, E> {
                Ok(SnapshotValue(value.into()))
            }
            fn visit_unit<E: serde::de::Error>(self) -> Result<Self::Value, E> {
                Ok(SnapshotValue(serde_json::Value::Null))
            }
        }
        deserializer.deserialize_any(Visitor { depth: self.depth })
    }
}

impl<'de> Deserialize<'de> for RunBridgeOutboxV1 {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let raw = SnapshotSeed { depth: 0 }.deserialize(deserializer)?;
        let stored: StoredOutboxV1 =
            serde_json::from_value(raw.0).map_err(serde::de::Error::custom)?;
        Self::try_from(stored).map_err(serde::de::Error::custom)
    }
}

impl TryFrom<StoredOutboxV1> for RunBridgeOutboxV1 {
    type Error = RunBridgeError;

    fn try_from(stored: StoredOutboxV1) -> Result<Self, Self::Error> {
        let state = Self {
            schema_version: stored.schema_version,
            binding: stored.binding,
            primary: stored.primary,
            primary_ack: stored.primary_ack,
            conflict: stored.conflict,
            conflict_ack: stored.conflict_ack,
        };
        state.validate()?;
        Ok(state)
    }
}

impl RunBridgeOutboxV1 {
    /// Decode an untrusted JSON snapshot only within the fixed byte budget.
    /// Direct serde use is reserved for inputs already bounded by their caller;
    /// visitor limits bound the intermediate object, not a parser's input buffer.
    pub fn from_json_slice(bytes: &[u8]) -> Result<Self, RunBridgeError> {
        if bytes.len() > MAX_SNAPSHOT_BYTES {
            return Err(RunBridgeError("run bridge snapshot byte bound exceeded"));
        }
        serde_json::from_slice(bytes).map_err(|_| RunBridgeError("invalid run bridge snapshot"))
    }

    /// Start only after the owner has durably normalized its primary outcome.
    pub fn new(
        binding: RunBridgeBindingV1,
        primary: RunBridgePrimaryV1,
    ) -> Result<Self, RunBridgeError> {
        let state = Self {
            schema_version: RUN_BRIDGE_SCHEMA_VERSION,
            binding,
            primary,
            primary_ack: None,
            conflict: None,
            conflict_ack: None,
        };
        state.validate()?;
        Ok(state)
    }

    /// Produce a candidate for an owner transaction; never mutate the original
    /// on conflict or manufacture a second terminal publication.
    pub fn transition(&self, change: RunBridgeOutboxChangeV1) -> Result<Self, RunBridgeError> {
        let mut next = self.clone();
        match change {
            RunBridgeOutboxChangeV1::QueueConflict(notice) => {
                if let Some(existing) = &next.conflict {
                    if *existing != notice {
                        return Err(RunBridgeError("immutable run bridge conflict differs"));
                    }
                } else {
                    next.conflict = Some(notice);
                }
            }
            RunBridgeOutboxChangeV1::AcknowledgePrimary(ack) => {
                if let Some(existing) = &next.primary_ack {
                    if *existing != ack {
                        return Err(RunBridgeError("immutable primary acknowledgement differs"));
                    }
                } else {
                    next.primary_ack = Some(ack);
                }
            }
            RunBridgeOutboxChangeV1::AcknowledgeConflict(ack) => {
                if let Some(existing) = &next.conflict_ack {
                    if *existing != ack {
                        return Err(RunBridgeError("immutable conflict acknowledgement differs"));
                    }
                } else {
                    next.conflict_ack = Some(ack);
                }
            }
        }
        next.validate()?;
        Ok(next)
    }

    fn validate(&self) -> Result<(), RunBridgeError> {
        if self.schema_version != RUN_BRIDGE_SCHEMA_VERSION {
            return Err(RunBridgeError("unsupported run bridge outbox schema"));
        }
        self.primary.validate(&self.binding)?;
        if let Some(ack) = &self.primary_ack {
            ack.validate(
                &self.binding,
                &self.primary.digest(&self.binding)?,
                RunBridgePublicationKindV1::Primary,
            )?;
        }
        if let Some(notice) = &self.conflict {
            notice.validate(&self.binding, &self.primary)?;
            if self.primary.logical_outcome != RunBridgeLogicalOutcomeV1::Succeeded {
                return Err(RunBridgeError(
                    "qualification downgrade requires successful primary",
                ));
            }
        }
        if let Some(ack) = &self.conflict_ack {
            let primary_ack = self.primary_ack.as_ref().ok_or(RunBridgeError(
                "primary acknowledgement required before conflict acknowledgement",
            ))?;
            let notice = self.conflict.as_ref().ok_or(RunBridgeError(
                "conflict acknowledgement has no pending notice",
            ))?;
            ack.validate(
                &self.binding,
                &notice.digest(&self.binding, &self.primary)?,
                RunBridgePublicationKindV1::QualificationConflict,
            )?;
            if ack.owner_revision <= primary_ack.owner_revision {
                return Err(RunBridgeError("conflict acknowledgement precedes primary"));
            }
        }
        Ok(())
    }

    pub fn binding(&self) -> &RunBridgeBindingV1 {
        &self.binding
    }

    pub fn primary(&self) -> &RunBridgePrimaryV1 {
        &self.primary
    }

    pub fn primary_acknowledgement(&self) -> Option<&RunBridgeAcknowledgementV1> {
        self.primary_ack.as_ref()
    }

    pub fn conflict(&self) -> Option<&RunBridgeQualificationConflictV1> {
        self.conflict.as_ref()
    }

    pub fn conflict_acknowledgement(&self) -> Option<&RunBridgeAcknowledgementV1> {
        self.conflict_ack.as_ref()
    }

    /// Delivery bookkeeping only; actual capacity release additionally needs
    /// the owner's durable physical terminal or consumed pre-effect proof.
    pub fn primary_delivery_pending(&self) -> bool {
        self.primary_ack.is_none()
    }

    pub fn conflict_delivery_pending(&self) -> bool {
        self.conflict.is_some() && self.conflict_ack.is_none()
    }

    /// Historical diagnostic only, never final-use or output-delivery authority.
    pub fn acknowledged_success_without_conflict(&self) -> bool {
        self.primary.logical_outcome == RunBridgeLogicalOutcomeV1::Succeeded
            && self.primary_ack.is_some()
            && self.conflict.is_none()
    }
}

#[cfg(test)]
#[path = "run_bridge_outbox_tests.rs"]
mod tests;
