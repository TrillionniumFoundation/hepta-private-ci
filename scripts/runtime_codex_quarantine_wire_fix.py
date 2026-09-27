#!/usr/bin/env python3
"""One-shot Serde adapters for runtime.codex quarantine domain values."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise SystemExit(
            f"{path}: expected one replacement, found {count}: {old[:120]!r}"
        )
    write(path, content.replace(old, new, 1))


path = "codex-rs/hepta-codex-adapter/src/quarantine.rs"
replace_once(
    path,
    """use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

pub const RUNTIME_CODEX_QUARANTINE_SCHEMA_VERSION: u32 = 1;
""",
    """use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

mod stable_id_wire {
    use super::StableId;
    use serde::Deserialize;
    use serde::Deserializer;
    use serde::Serializer;

    pub fn serialize<S>(value: &StableId, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_str(value.as_str())
    }

    pub fn deserialize<'de, D>(deserializer: D) -> Result<StableId, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        StableId::new(value).map_err(|_| serde::de::Error::custom("invalid stable id"))
    }
}

mod optional_stable_id_wire {
    use super::StableId;
    use serde::Deserialize;
    use serde::Deserializer;
    use serde::Serializer;

    pub fn serialize<S>(value: &Option<StableId>, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        match value {
            Some(value) => serializer.serialize_some(value.as_str()),
            None => serializer.serialize_none(),
        }
    }

    pub fn deserialize<'de, D>(deserializer: D) -> Result<Option<StableId>, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = Option::<String>::deserialize(deserializer)?;
        value
            .map(|value| {
                StableId::new(value)
                    .map_err(|_| serde::de::Error::custom("invalid optional stable id"))
            })
            .transpose()
    }
}

mod digest32_wire {
    use super::Digest32;
    use serde::Deserialize;
    use serde::Deserializer;
    use serde::Serializer;

    pub fn serialize<S>(value: &Digest32, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_str(&value.to_string())
    }

    pub fn deserialize<'de, D>(deserializer: D) -> Result<Digest32, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        value
            .parse()
            .map_err(|_| serde::de::Error::custom("invalid sha256 digest"))
    }
}

pub const RUNTIME_CODEX_QUARANTINE_SCHEMA_VERSION: u32 = 1;
""",
)

replace_once(
    path,
    """    pub operation_id: StableId,
    pub request_digest: Digest32,
    pub source_admission_digest: Digest32,
    pub authority_witness_digest: Digest32,
    pub thread_id: Option<StableId>,
    pub turn_id: Option<StableId>,
""",
    """    #[serde(with = "stable_id_wire")]
    pub operation_id: StableId,
    #[serde(with = "digest32_wire")]
    pub request_digest: Digest32,
    #[serde(with = "digest32_wire")]
    pub source_admission_digest: Digest32,
    #[serde(with = "digest32_wire")]
    pub authority_witness_digest: Digest32,
    #[serde(default, with = "optional_stable_id_wire")]
    pub thread_id: Option<StableId>,
    #[serde(default, with = "optional_stable_id_wire")]
    pub turn_id: Option<StableId>,
""",
)

replace_once(
    path,
    """    pub quarantine_digest: Digest32,
    pub disposition: RuntimeCodexResolutionDispositionV1,
    pub independent_evidence_digest: Digest32,
""",
    """    #[serde(with = "digest32_wire")]
    pub quarantine_digest: Digest32,
    pub disposition: RuntimeCodexResolutionDispositionV1,
    #[serde(with = "digest32_wire")]
    pub independent_evidence_digest: Digest32,
""",
)

Path(__file__).unlink()
