use std::collections::BTreeSet;

use codex_hepta_memory::KgEntityFactDraft;
use codex_hepta_memory::KgFactSetDraft;
use codex_hepta_memory::KgRelationFactDraft;
use codex_hepta_memory::MemoryVerification;
use serde::Deserialize;

use super::secret_like;

pub(super) const MAX_STRUCTURED_KG_ENTITIES: usize = 64;
pub(super) const MAX_STRUCTURED_KG_RELATIONS: usize = 128;
pub(super) const MAX_STRUCTURED_KG_KEY_BYTES: usize = 256;
pub(super) const MAX_STRUCTURED_KG_TYPE_BYTES: usize = 128;
pub(super) const MAX_STRUCTURED_KG_LABEL_BYTES: usize = 1_024;
pub(super) const MAX_STRUCTURED_KG_RELATION_BYTES: usize = 128;

/// Host-owned extractor for bounded, caller-supplied structured cognitive facts.
///
/// This component does not infer facts from prose. It normalizes and validates
/// the explicit structured fact set before the atomic store writer sees it.
#[derive(Clone, Copy, Debug, Default)]
pub(super) struct StructuredCognitiveKgExtractor;

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct StructuredKgInput {
    #[serde(default)]
    pub(super) entities: Vec<StructuredKgEntityInput>,
    #[serde(default)]
    pub(super) relations: Vec<StructuredKgRelationInput>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct StructuredKgEntityInput {
    pub(super) key: String,
    pub(super) entity_type: String,
    pub(super) label: String,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct StructuredKgRelationInput {
    pub(super) key: String,
    pub(super) from_entity_key: String,
    pub(super) to_entity_key: String,
    pub(super) relation: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) enum StructuredKgError {
    Invalid(String),
    Limit(String),
    Secret(String),
    Duplicate(String),
    Dangling(String),
    ProvisionalFacts,
}

impl StructuredKgError {
    pub(super) fn code(&self) -> &'static str {
        match self {
            Self::Invalid(_) => "hepta_cognitive_invalid_kg",
            Self::Limit(_) => "hepta_cognitive_kg_limit",
            Self::Secret(_) => "hepta_cognitive_secret_like_content",
            Self::Duplicate(_) => "hepta_cognitive_kg_duplicate",
            Self::Dangling(_) => "hepta_cognitive_kg_dangling_relation",
            Self::ProvisionalFacts => "hepta_cognitive_kg_provisional_facts",
        }
    }

    pub(super) fn message(&self) -> String {
        match self {
            Self::Invalid(message)
            | Self::Limit(message)
            | Self::Secret(message)
            | Self::Duplicate(message)
            | Self::Dangling(message) => message.clone(),
            Self::ProvisionalFacts => {
                "provisional memory cannot carry structured KG facts".to_string()
            }
        }
    }
}

impl StructuredCognitiveKgExtractor {
    pub(super) fn extract(
        self,
        input: StructuredKgInput,
        verification: MemoryVerification,
    ) -> Result<KgFactSetDraft, StructuredKgError> {
        if input.entities.len() > MAX_STRUCTURED_KG_ENTITIES {
            return Err(StructuredKgError::Limit(format!(
                "kg.entities exceeds the {MAX_STRUCTURED_KG_ENTITIES}-item limit"
            )));
        }
        if input.relations.len() > MAX_STRUCTURED_KG_RELATIONS {
            return Err(StructuredKgError::Limit(format!(
                "kg.relations exceeds the {MAX_STRUCTURED_KG_RELATIONS}-item limit"
            )));
        }
        if verification == MemoryVerification::Provisional
            && (!input.entities.is_empty() || !input.relations.is_empty())
        {
            return Err(StructuredKgError::ProvisionalFacts);
        }

        let mut entity_keys = BTreeSet::new();
        let mut entities = Vec::with_capacity(input.entities.len());
        for entity in input.entities {
            let key = normalize_key("kg.entities[].key", entity.key)?;
            if !entity_keys.insert(key.clone()) {
                return Err(StructuredKgError::Duplicate(format!(
                    "duplicate kg entity key `{key}`"
                )));
            }
            entities.push(KgEntityFactDraft {
                key,
                entity_type: normalize_token(
                    "kg.entities[].entity_type",
                    entity.entity_type,
                    MAX_STRUCTURED_KG_TYPE_BYTES,
                )?,
                label: normalize_text(
                    "kg.entities[].label",
                    entity.label,
                    MAX_STRUCTURED_KG_LABEL_BYTES,
                )?,
            });
        }

        let mut relation_keys = BTreeSet::new();
        let mut relations = Vec::with_capacity(input.relations.len());
        for relation in input.relations {
            let key = normalize_key("kg.relations[].key", relation.key)?;
            if !relation_keys.insert(key.clone()) {
                return Err(StructuredKgError::Duplicate(format!(
                    "duplicate kg relation key `{key}`"
                )));
            }
            let from_entity_key =
                normalize_key("kg.relations[].from_entity_key", relation.from_entity_key)?;
            let to_entity_key =
                normalize_key("kg.relations[].to_entity_key", relation.to_entity_key)?;
            for endpoint in [&from_entity_key, &to_entity_key] {
                if !entity_keys.contains(endpoint) {
                    return Err(StructuredKgError::Dangling(format!(
                        "kg relation `{key}` references missing entity `{endpoint}`"
                    )));
                }
            }
            relations.push(KgRelationFactDraft {
                key,
                from_entity_key,
                to_entity_key,
                relation: normalize_token(
                    "kg.relations[].relation",
                    relation.relation,
                    MAX_STRUCTURED_KG_RELATION_BYTES,
                )?,
            });
        }

        Ok(KgFactSetDraft {
            entities,
            relations,
        })
    }
}

fn normalize_key(label: &str, value: String) -> Result<String, StructuredKgError> {
    let normalized = normalize_text(label, value, MAX_STRUCTURED_KG_KEY_BYTES)?;
    let normalized = normalized.to_ascii_lowercase();
    validate_normalized_length(label, &normalized, MAX_STRUCTURED_KG_KEY_BYTES)?;
    Ok(normalized)
}

fn normalize_token(
    label: &str,
    value: String,
    max_bytes: usize,
) -> Result<String, StructuredKgError> {
    let normalized = normalize_text(label, value, max_bytes)?.to_ascii_lowercase();
    validate_normalized_length(label, &normalized, max_bytes)?;
    Ok(normalized)
}

fn normalize_text(
    label: &str,
    value: String,
    max_bytes: usize,
) -> Result<String, StructuredKgError> {
    if value.contains('\0') {
        return Err(StructuredKgError::Invalid(format!(
            "{label} contains a NUL byte"
        )));
    }
    if secret_like(value.as_bytes()) {
        return Err(StructuredKgError::Secret(format!(
            "{label} contains secret-like content and was not persisted"
        )));
    }
    let normalized = value.split_whitespace().collect::<Vec<_>>().join(" ");
    if normalized.is_empty() {
        return Err(StructuredKgError::Invalid(format!(
            "{label} must not be empty"
        )));
    }
    validate_normalized_length(label, &normalized, max_bytes)?;
    Ok(normalized)
}

fn validate_normalized_length(
    label: &str,
    value: &str,
    max_bytes: usize,
) -> Result<(), StructuredKgError> {
    if value.len() > max_bytes {
        return Err(StructuredKgError::Limit(format!(
            "{label} exceeds the {max_bytes}-byte limit"
        )));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn entity(key: &str) -> StructuredKgEntityInput {
        StructuredKgEntityInput {
            key: key.to_string(),
            entity_type: " Project ".to_string(),
            label: " Hepta   vNext ".to_string(),
        }
    }

    #[test]
    fn extractor_normalizes_and_resolves_structured_facts() {
        let facts = StructuredCognitiveKgExtractor
            .extract(
                StructuredKgInput {
                    entities: vec![entity(" Hepta "), entity(" Rust ")],
                    relations: vec![StructuredKgRelationInput {
                        key: " Uses ".to_string(),
                        from_entity_key: " HEPTA ".to_string(),
                        to_entity_key: " Rust ".to_string(),
                        relation: " Uses Language ".to_string(),
                    }],
                },
                MemoryVerification::Verified,
            )
            .expect("valid structured facts");

        assert_eq!(facts.entities[0].key, "hepta");
        assert_eq!(facts.entities[0].entity_type, "project");
        assert_eq!(facts.entities[0].label, "Hepta vNext");
        assert_eq!(facts.relations[0].from_entity_key, "hepta");
        assert_eq!(facts.relations[0].relation, "uses language");
    }

    #[test]
    fn extractor_rejects_duplicate_dangling_secret_nul_limits_and_provisional_facts() {
        let extractor = StructuredCognitiveKgExtractor;
        let duplicate = StructuredKgInput {
            entities: vec![entity("Hepta"), entity(" hepta ")],
            relations: Vec::new(),
        };
        assert!(matches!(
            extractor.extract(duplicate, MemoryVerification::Verified),
            Err(StructuredKgError::Duplicate(_))
        ));

        let dangling = StructuredKgInput {
            entities: vec![entity("hepta")],
            relations: vec![StructuredKgRelationInput {
                key: "uses".to_string(),
                from_entity_key: "hepta".to_string(),
                to_entity_key: "missing".to_string(),
                relation: "uses".to_string(),
            }],
        };
        assert!(matches!(
            extractor.extract(dangling, MemoryVerification::Verified),
            Err(StructuredKgError::Dangling(_))
        ));

        assert!(matches!(
            extractor.extract(
                StructuredKgInput {
                    entities: vec![StructuredKgEntityInput {
                        key: "secret".to_string(),
                        entity_type: "credential".to_string(),
                        label: "api_key=do-not-store".to_string(),
                    }],
                    relations: Vec::new(),
                },
                MemoryVerification::Verified,
            ),
            Err(StructuredKgError::Secret(_))
        ));
        assert!(matches!(
            extractor.extract(
                StructuredKgInput {
                    entities: vec![StructuredKgEntityInput {
                        key: "nul\0key".to_string(),
                        entity_type: "project".to_string(),
                        label: "label".to_string(),
                    }],
                    relations: Vec::new(),
                },
                MemoryVerification::Verified,
            ),
            Err(StructuredKgError::Invalid(_))
        ));
        assert!(matches!(
            extractor.extract(
                StructuredKgInput {
                    entities: vec![StructuredKgEntityInput {
                        key: "x".repeat(MAX_STRUCTURED_KG_KEY_BYTES + 1),
                        entity_type: "project".to_string(),
                        label: "label".to_string(),
                    }],
                    relations: Vec::new(),
                },
                MemoryVerification::Verified,
            ),
            Err(StructuredKgError::Limit(_))
        ));

        assert_eq!(
            extractor.extract(
                StructuredKgInput {
                    entities: vec![entity("hepta")],
                    relations: Vec::new(),
                },
                MemoryVerification::Provisional,
            ),
            Err(StructuredKgError::ProvisionalFacts)
        );

        assert!(matches!(
            extractor.extract(
                StructuredKgInput {
                    entities: (0..=MAX_STRUCTURED_KG_ENTITIES)
                        .map(|index| entity(format!("entity-{index}").as_str()))
                        .collect(),
                    relations: Vec::new(),
                },
                MemoryVerification::Verified,
            ),
            Err(StructuredKgError::Limit(_))
        ));
        assert!(matches!(
            extractor.extract(
                StructuredKgInput {
                    entities: vec![entity("hepta")],
                    relations: vec![
                        StructuredKgRelationInput {
                            key: "relation".to_string(),
                            from_entity_key: "hepta".to_string(),
                            to_entity_key: "hepta".to_string(),
                            relation: "references".to_string(),
                        };
                        MAX_STRUCTURED_KG_RELATIONS + 1
                    ],
                },
                MemoryVerification::Verified,
            ),
            Err(StructuredKgError::Limit(_))
        ));
    }

    #[test]
    fn structured_input_denies_unknown_fields_at_every_level() {
        assert!(
            serde_json::from_value::<StructuredKgInput>(serde_json::json!({
                "entities": [],
                "relations": [],
                "unexpected": true
            }))
            .is_err()
        );
        assert!(
            serde_json::from_value::<StructuredKgInput>(serde_json::json!({
                "entities": [{
                    "key": "hepta",
                    "entity_type": "project",
                    "label": "Hepta",
                    "unexpected": true
                }]
            }))
            .is_err()
        );
    }
}
