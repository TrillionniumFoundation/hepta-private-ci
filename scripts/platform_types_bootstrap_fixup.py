#!/usr/bin/env python3
"""Idempotent final bootstrap fixes for platform.types convergence.

This script runs after the one-shot V1 compatibility migration. It aligns the
V2 numeric test fixture with its target Q24 raw scale and makes Prompt V2 JSON
nullable fields required-by-presence while still accepting explicit JSON null.
The lock-refresh workflow deletes this script after all checks pass.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def fix_numeric_fixture() -> bool:
    path = ROOT / "codex-rs/hepta-types/src/numeric_registry_v2.rs"
    text = path.read_text(encoding="utf-8")
    if "minimum_raw: -(1_i64 << 24)," in text:
        return False

    pattern = re.compile(
        r"(?m)^(?P<indent>[ \t]*)let target = NumericSignalSchemaV1 \{\n"
        r"(?P=indent)    profile: NumericProfileV1::SignedQ24NearestTiesEven,\n"
        r"(?P=indent)    \.\.source\.schema\.clone\(\)\n"
        r"(?P=indent)\};$"
    )
    match = pattern.search(text)
    if match is None:
        raise SystemExit("numeric registry V2 target fixture anchor missing")
    indent = match.group("indent")
    replacement = (
        f"{indent}let target = NumericSignalSchemaV1 {{\n"
        f"{indent}    profile: NumericProfileV1::SignedQ24NearestTiesEven,\n"
        f"{indent}    minimum_raw: -(1_i64 << 24),\n"
        f"{indent}    maximum_raw: 1_i64 << 24,\n"
        f"{indent}    ..source.schema.clone()\n"
        f"{indent}}};"
    )
    text, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise SystemExit(f"numeric registry V2 target fixture replacements: {count}")
    path.write_text(text, encoding="utf-8")
    return True


def fix_required_nullable_prompt_fields() -> bool:
    path = ROOT / "codex-rs/hepta-wire/src/platform_types_json.rs"
    text = path.read_text(encoding="utf-8")
    if "fn deserialize_required_nullable" in text:
        return False

    text = replace_once(
        text,
        """#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(transparent)]
struct RequiredNullable<T>(Option<T>);

impl<'de, T> Deserialize<'de> for RequiredNullable<T>
where
    T: Deserialize<'de>,
{
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        Option::<T>::deserialize(deserializer).map(Self)
    }
}
""",
        """fn deserialize_required_nullable<'de, D, T>(
    deserializer: D,
) -> Result<Option<T>, D::Error>
where
    D: Deserializer<'de>,
    T: Deserialize<'de>,
{
    Option::<T>::deserialize(deserializer)
}
""",
        "required nullable deserializer",
    )
    text = replace_once(
        text,
        """    rejected_reason: RequiredNullable<String>,
    observed_token_positions: RequiredNullable<Vec<u32>>,
    truncation_observed: bool,
    legacy_v1_digest: RequiredNullable<String>,
""",
        """    #[serde(deserialize_with = "deserialize_required_nullable")]
    rejected_reason: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    observed_token_positions: Option<Vec<u32>>,
    truncation_observed: bool,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    legacy_v1_digest: Option<String>,
""",
        "required nullable prompt fields",
    )
    text = replace_once(
        text,
        """    let rejected_reason = wire
        .rejected_reason
        .0
        .map(|value| {
""",
        """    let rejected_reason = wire
        .rejected_reason
        .map(|value| {
""",
        "rejected reason decode",
    )
    text = replace_once(
        text,
        """    let legacy_v1_digest = wire
        .legacy_v1_digest
        .0
        .map(|value| digest(&value, "legacy_v1_digest"))
""",
        """    let legacy_v1_digest = wire
        .legacy_v1_digest
        .map(|value| digest(&value, "legacy_v1_digest"))
""",
        "legacy digest decode",
    )
    text = replace_once(
        text,
        "        wire.observed_token_positions.0,\n",
        "        wire.observed_token_positions,\n",
        "token positions decode",
    )
    text = replace_once(
        text,
        """        rejected_reason: RequiredNullable(
            value
                .rejected_reason()
                .map(|reason| reason.as_id().to_string()),
        ),
        observed_token_positions: RequiredNullable(
            value.observed_token_positions().map(<[u32]>::to_vec),
        ),
        truncation_observed: value.truncation_observed(),
        legacy_v1_digest: RequiredNullable(
            value.legacy_v1_digest().map(|item| item.to_string()),
        ),
""",
        """        rejected_reason: value
            .rejected_reason()
            .map(|reason| reason.as_id().to_string()),
        observed_token_positions: value.observed_token_positions().map(<[u32]>::to_vec),
        truncation_observed: value.truncation_observed(),
        legacy_v1_digest: value.legacy_v1_digest().map(|item| item.to_string()),
""",
        "prompt nullable encode",
    )
    path.write_text(text, encoding="utf-8")
    return True


def main() -> int:
    changed = []
    if fix_numeric_fixture():
        changed.append("numeric-registry-v2-target-scale")
    if fix_required_nullable_prompt_fields():
        changed.append("prompt-v2-required-nullable-fields")
    print(
        "platform.types final bootstrap: "
        + (", ".join(changed) if changed else "already converged")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
