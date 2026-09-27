#!/usr/bin/env python3
"""Apply the prompt.registry V4 source migration deterministically.

This is an idempotent, exact-anchor migration helper used by the remediation
branch. It intentionally fails closed if the source no longer matches the
reviewed baseline, rather than applying a fuzzy edit to an unknown tree.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    file_path = ROOT / path
    text = file_path.read_text(encoding="utf-8")
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one exact anchor, found {count}: {old[:80]!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_durable_registry() -> None:
    path = "codex-rs/hepta-prompt-registry/src/durable.rs"
    replace_once(
        path,
        "use crate::PromptFactor;\nuse crate::PromptModelTupleV2;",
        "use crate::PromptFactor;\nuse crate::PromptFactorRelation;\n"
        "use crate::PromptFactorRelationKind;\nuse crate::PromptModelTupleV2;",
    )
    replace_once(
        path,
        "    pub fn register_factor(\n"
        "        &mut self,\n"
        "        factor: PromptFactor,\n"
        "    ) -> Result<RegistryReceipt, DurableRegistryError> {\n"
        "        self.commit(|registry| registry.register_factor(factor))\n"
        "    }\n\n",
        "    pub fn register_factor(\n"
        "        &mut self,\n"
        "        factor: PromptFactor,\n"
        "    ) -> Result<RegistryReceipt, DurableRegistryError> {\n"
        "        self.commit(|registry| registry.register_factor(factor))\n"
        "    }\n\n"
        "    /// Register one governed factor relation in the same durable image\n"
        "    /// as factors, realizations, lifecycle state and payload references.\n"
        "    pub fn register_factor_relation(\n"
        "        &mut self,\n"
        "        relation: PromptFactorRelation,\n"
        "    ) -> Result<RegistryReceipt, DurableRegistryError> {\n"
        "        self.commit(|registry| registry.register_factor_relation(relation))\n"
        "    }\n\n",
    )
    replace_once(
        path,
        "    payloads: Vec<StoredPayload>,\n"
        "    supersessions: Vec<StoredSupersession>,",
        "    payloads: Vec<StoredPayload>,\n"
        "    #[serde(default)]\n"
        "    relations: Vec<StoredRelation>,\n"
        "    supersessions: Vec<StoredSupersession>,",
    )
    replace_once(
        path,
        "#[derive(Deserialize, Serialize)]\n"
        "#[serde(deny_unknown_fields)]\n"
        "struct StoredSupersession {",
        "#[derive(Deserialize, Serialize)]\n"
        "#[serde(deny_unknown_fields)]\n"
        "struct StoredRelation {\n"
        "    relation_id: String,\n"
        "    left_factor_id: String,\n"
        "    right_factor_id: String,\n"
        "    kind: u8,\n"
        "    evidence_digest: [u8; 32],\n"
        "}\n\n"
        "#[derive(Deserialize, Serialize)]\n"
        "#[serde(deny_unknown_fields)]\n"
        "struct StoredSupersession {",
    )
    replace_once(
        path,
        "        payloads: Vec::new(),\n"
        "        supersessions: registry",
        "        payloads: Vec::new(),\n"
        "        relations: registry\n"
        "            .relations\n"
        "            .values()\n"
        "            .map(|relation| StoredRelation {\n"
        "                relation_id: relation.relation_id.to_string(),\n"
        "                left_factor_id: relation.left_factor_id.to_string(),\n"
        "                right_factor_id: relation.right_factor_id.to_string(),\n"
        "                kind: relation_kind_code(relation.kind),\n"
        "                evidence_digest: relation.evidence_digest.into_array(),\n"
        "            })\n"
        "            .collect(),\n"
        "        supersessions: registry",
    )
    replace_once(
        path,
        "    let mut lifecycle_events = Vec::new();\n"
        "    for stored_event in stored.lifecycle_events {",
        "    let mut relations = BTreeMap::new();\n"
        "    let mut relation_semantics = BTreeSet::new();\n"
        "    for stored_relation in stored.relations {\n"
        "        let relation = decode_relation(stored_relation)?;\n"
        "        if relation.evidence_digest.is_zero()\n"
        "            || relation.left_factor_id >= relation.right_factor_id\n"
        "            || !relation_semantics.insert((\n"
        "                relation.left_factor_id.clone(),\n"
        "                relation.right_factor_id.clone(),\n"
        "                relation.kind,\n"
        "            ))\n"
        "            || relations\n"
        "                .insert(relation.relation_id.clone(), relation)\n"
        "                .is_some()\n"
        "        {\n"
        "            return Err(DurableRegistryError::Corrupt);\n"
        "        }\n"
        "    }\n"
        "    if factors\n"
        "        .len()\n"
        "        .saturating_add(realizations.len())\n"
        "        .saturating_add(relations.len())\n"
        "        > configured_maximum\n"
        "    {\n"
        "        return Err(DurableRegistryError::CapacityExceeded);\n"
        "    }\n\n"
        "    let mut lifecycle_events = Vec::new();\n"
        "    for stored_event in stored.lifecycle_events {",
    )
    replace_once(
        path,
        "        realization_supersessions,\n"
        "        relations: BTreeMap::new(),\n"
        "        lifecycle_events,",
        "        realization_supersessions,\n"
        "        relations,\n"
        "        lifecycle_events,",
    )
    replace_once(
        path,
        "            .saturating_add(registry.realizations.len())\n"
        "            > registry.maximum_records",
        "            .saturating_add(registry.realizations.len())\n"
        "            .saturating_add(registry.relations.len())\n"
        "            > registry.maximum_records",
    )
    replace_once(
        path,
        "    let mut seen_predecessors = BTreeSet::new();\n"
        "    for (successor, predecessor) in &registry.realization_supersessions {",
        "    let mut seen_relation_semantics = BTreeSet::new();\n"
        "    for relation in registry.relations.values() {\n"
        "        let Some(left) = registry.factors.get(&relation.left_factor_id) else {\n"
        "            return Err(DurableRegistryError::Corrupt);\n"
        "        };\n"
        "        let Some(right) = registry.factors.get(&relation.right_factor_id) else {\n"
        "            return Err(DurableRegistryError::Corrupt);\n"
        "        };\n"
        "        if relation.evidence_digest.is_zero()\n"
        "            || relation.left_factor_id >= relation.right_factor_id\n"
        "            || left.source != FactorSource::GovernedInternal\n"
        "            || right.source != FactorSource::GovernedInternal\n"
        "            || left.lifecycle != Lifecycle::Admitted\n"
        "            || right.lifecycle != Lifecycle::Admitted\n"
        "            || !seen_relation_semantics.insert((\n"
        "                relation.left_factor_id.clone(),\n"
        "                relation.right_factor_id.clone(),\n"
        "                relation.kind,\n"
        "            ))\n"
        "        {\n"
        "            return Err(DurableRegistryError::Corrupt);\n"
        "        }\n"
        "    }\n\n"
        "    let mut seen_predecessors = BTreeSet::new();\n"
        "    for (successor, predecessor) in &registry.realization_supersessions {",
    )
    replace_once(
        path,
        "fn decode_event(stored: StoredLifecycleEvent) -> Result<LifecycleEvent, DurableRegistryError> {",
        "fn decode_relation(\n"
        "    stored: StoredRelation,\n"
        ") -> Result<PromptFactorRelation, DurableRegistryError> {\n"
        "    Ok(PromptFactorRelation {\n"
        "        relation_id: parse_id(stored.relation_id)?,\n"
        "        left_factor_id: parse_id(stored.left_factor_id)?,\n"
        "        right_factor_id: parse_id(stored.right_factor_id)?,\n"
        "        kind: decode_relation_kind(stored.kind)?,\n"
        "        evidence_digest: Digest32::from_array(stored.evidence_digest),\n"
        "    })\n"
        "}\n\n"
        "fn decode_event(stored: StoredLifecycleEvent) -> Result<LifecycleEvent, DurableRegistryError> {",
    )
    replace_once(
        path,
        "const fn role_code(value: PromptRoleV2) -> u8 {",
        "const fn relation_kind_code(value: PromptFactorRelationKind) -> u8 {\n"
        "    match value {\n"
        "        PromptFactorRelationKind::Complements => 0,\n"
        "        PromptFactorRelationKind::Substitutes => 1,\n"
        "        PromptFactorRelationKind::Conflicts => 2,\n"
        "    }\n"
        "}\n\n"
        "fn decode_relation_kind(\n"
        "    value: u8,\n"
        ") -> Result<PromptFactorRelationKind, DurableRegistryError> {\n"
        "    match value {\n"
        "        0 => Ok(PromptFactorRelationKind::Complements),\n"
        "        1 => Ok(PromptFactorRelationKind::Substitutes),\n"
        "        2 => Ok(PromptFactorRelationKind::Conflicts),\n"
        "        _ => Err(DurableRegistryError::Corrupt),\n"
        "    }\n"
        "}\n\n"
        "const fn role_code(value: PromptRoleV2) -> u8 {",
    )
    replace_once(
        path,
        "            3 => {\n"
        "                let manifest =",
        "            3 | 4 => {\n"
        "                let manifest =",
    )
    replace_once(
        path,
        "        let bytes = serde_json::to_vec(&payloads::StoredV3 {\n"
        "            schema: 3,",
        "        let bytes = serde_json::to_vec(&payloads::StoredV3 {\n"
        "            schema: 4,",
    )


def patch_payload_manifest() -> None:
    path = "codex-rs/hepta-prompt-registry/src/durable_payloads.rs"
    replace_once(
        path,
        "//! Storage-v3 payload extent file under the existing exclusive registry owner.",
        "//! Storage-v4 payload extent file under the existing exclusive registry owner.",
    )
    replace_once(
        path,
        "        if stored.schema != 3\n"
        "            || stored.state.schema != super::STORE_SCHEMA",
        "        if !matches!(stored.schema, 3 | 4)\n"
        "            || stored.state.schema != super::STORE_SCHEMA",
    )


def main() -> None:
    patch_durable_registry()
    patch_payload_manifest()


if __name__ == "__main__":
    main()
