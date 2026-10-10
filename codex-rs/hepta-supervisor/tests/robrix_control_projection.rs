use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fs;

use anyhow::Context;
use anyhow::Result;
use codex_hepta_supervisor::CORPUS_FILE;
use codex_hepta_supervisor::GENERATED_CONSTANTS_FILE;
use codex_hepta_supervisor::MANIFEST_FILE;
use codex_hepta_supervisor::MATRIXD_SCHEMA_FILE;
use codex_hepta_supervisor::SUPERVISORD_SCHEMA_FILE;
use codex_hepta_supervisor::generated_robrix_control_artifacts;
use codex_hepta_supervisor::verify_robrix_control_corpus;
use codex_hepta_supervisor::write_robrix_control_projection;
use jsonschema::Keyword;
use jsonschema::ValidationError;
use jsonschema::paths::LazyLocation;
use jsonschema::paths::Location;
use serde_json::Map;
use serde_json::Value;

#[test]
fn robrix_control_v2_generated_projection_and_cross_parser_corpus() -> Result<()> {
    let expected = generated_robrix_control_artifacts()?;
    let tracked = read_tracked_artifacts()?;
    assert_eq!(
        tracked, expected,
        "tracked projection must match the writer"
    );

    verify_robrix_control_corpus(
        expected
            .get(CORPUS_FILE)
            .context("generated corpus is missing")?,
    )?;
    verify_generated_schema_parity(
        expected
            .get(SUPERVISORD_SCHEMA_FILE)
            .context("generated supervisord schema is missing")?,
        expected
            .get(MATRIXD_SCHEMA_FILE)
            .context("generated Matrix schema is missing")?,
        expected
            .get(MANIFEST_FILE)
            .context("generated manifest is missing")?,
        expected
            .get(CORPUS_FILE)
            .context("generated corpus is missing")?,
    )?;

    let constants = std::str::from_utf8(
        expected
            .get(GENERATED_CONSTANTS_FILE)
            .context("generated constants are missing")?,
    )?;
    assert!(constants.contains("ROBRIX_SUPERVISORD_MAX_FRAME_BYTES: usize = 65536"));
    assert!(constants.contains("MAX_MATRIXD_CONTROL_FRAME_BYTES: usize = 1048576"));
    assert!(constants.contains("[\"health\", \"roster\", \"snapshot\"]"));
    for mutation in [
        "start", "drain", "stop", "kill", "restart", "upgrade", "rollback",
    ] {
        assert!(
            !constants.contains(&format!("\"{mutation}\"")),
            "generated Robrix supervisord projection exposed {mutation}"
        );
    }
    Ok(())
}

fn verify_generated_schema_parity(
    supervisord_schema_bytes: &[u8],
    matrixd_schema_bytes: &[u8],
    manifest_bytes: &[u8],
    corpus_bytes: &[u8],
) -> Result<()> {
    let supervisord_schema: Value =
        serde_json::from_slice(supervisord_schema_bytes).context("parse supervisord schema")?;
    let matrixd_schema: Value =
        serde_json::from_slice(matrixd_schema_bytes).context("parse Matrix schema")?;
    let supervisord_validator = jsonschema::options()
        .with_keyword("x-hepta-max-utf8-bytes", max_utf8_bytes_factory)
        .with_keyword("x-hepta-safe-text-profile", safe_text_profile_factory)
        .build(&supervisord_schema)
        .context("compile generated supervisord schema")?;
    let matrixd_validator = jsonschema::options()
        .with_keyword("x-hepta-max-utf8-bytes", max_utf8_bytes_factory)
        .with_keyword("x-hepta-safe-text-profile", safe_text_profile_factory)
        .build(&matrixd_schema)
        .context("compile generated Matrix schema")?;
    let manifest: Value = serde_json::from_slice(manifest_bytes).context("parse manifest")?;
    let corpus: Value = serde_json::from_slice(corpus_bytes).context("parse generated corpus")?;
    let cases = corpus
        .get("cases")
        .and_then(Value::as_array)
        .context("generated corpus cases are missing")?;

    let validation_role = manifest
        .get("json_schema_validation_role")
        .and_then(Value::as_str)
        .context("manifest is missing JSON Schema validation role")?;
    assert_eq!(
        validation_role,
        "structural_and_locally_expressible_invariants_only"
    );
    let semantic_validator = manifest
        .get("authoritative_semantic_validator")
        .and_then(Value::as_str)
        .context("manifest is missing authoritative semantic validator")?;
    assert_eq!(
        semantic_validator,
        "generated_cross_parser_corpus_with_rust_protocol_validation"
    );
    let allowed_gap_classes = string_set(&manifest, "json_schema_non_schema_invariant_classes")?;
    assert_eq!(
        allowed_gap_classes,
        BTreeSet::from([
            "cross_element_key_uniqueness",
            "cross_field_ordering",
            "cross_object_field_equality",
            "requested_cursor_contiguity",
            "selected_process_context",
        ])
    );
    for schema in [&supervisord_schema, &matrixd_schema] {
        assert_eq!(
            schema
                .get("x-hepta-validation-role")
                .and_then(Value::as_str),
            Some(validation_role)
        );
        assert_eq!(
            schema
                .get("x-hepta-authoritative-semantic-validator")
                .and_then(Value::as_str),
            Some(semantic_validator)
        );
        assert_eq!(
            string_set(schema, "x-hepta-non-schema-invariant-classes")?,
            allowed_gap_classes
        );
        assert!(
            !string_set(schema, "x-hepta-non-schema-invariants")?.is_empty(),
            "schema must enumerate its non-schema invariants"
        );
    }

    let mut checked = BTreeMap::<String, usize>::new();
    for case in cases {
        let id = case
            .get("id")
            .and_then(Value::as_str)
            .context("corpus case is missing its ID")?;
        let plane = case
            .get("plane")
            .and_then(Value::as_str)
            .with_context(|| format!("{id} is missing plane"))?;
        let direction = case
            .get("direction")
            .and_then(Value::as_str)
            .with_context(|| format!("{id} is missing direction"))?;
        *checked.entry(format!("{plane}:{direction}")).or_default() += 1;
        let wire = case
            .get("wire_utf8")
            .and_then(Value::as_str)
            .with_context(|| format!("{id} is missing wire_utf8"))?;
        let instance: Value =
            serde_json::from_str(wire).with_context(|| format!("parse {id} wire"))?;
        let schema_validate = match plane {
            "supervisord" => supervisord_validator.is_valid(&instance),
            "matrixd" => matrixd_validator.is_valid(&instance),
            other => anyhow::bail!("{id} has unknown plane {other}"),
        };
        let expected = case
            .get("expected")
            .with_context(|| format!("{id} is missing expectations"))?;
        let semantic_validate = expected
            .get("backend_projection_validate")
            .and_then(Value::as_bool)
            .with_context(|| format!("{id} is missing semantic expectation"))?;
        assert_eq!(
            schema_validate,
            expected
                .get("backend_json_schema_validate")
                .and_then(Value::as_bool)
                .with_context(|| format!("{id} is missing schema expectation"))?,
            "{id} generated JSON Schema expectation drifted"
        );
        let declared_gap = expected
            .get("json_schema_semantic_gap")
            .and_then(Value::as_str);
        if schema_validate == semantic_validate {
            assert_eq!(
                declared_gap, None,
                "{id} declares a JSON Schema semantic gap without a verdict divergence"
            );
        } else {
            assert!(
                schema_validate && !semantic_validate,
                "{id} schema must never reject a semantically valid corpus case"
            );
            let declared_gap = declared_gap
                .with_context(|| format!("{id} has an undeclared schema/semantic gap"))?;
            assert!(
                allowed_gap_classes.contains(declared_gap),
                "{id} declares unknown schema gap class {declared_gap}"
            );
        }
    }
    assert_eq!(checked.get("supervisord:request").copied(), Some(12));
    assert_eq!(checked.get("supervisord:response").copied(), Some(8));
    assert!(checked.get("matrixd:request").copied().unwrap_or_default() >= 19);
    assert!(checked.get("matrixd:response").copied().unwrap_or_default() >= 21);
    Ok(())
}

fn string_set<'a>(value: &'a Value, field: &str) -> Result<BTreeSet<&'a str>> {
    value
        .get(field)
        .and_then(Value::as_array)
        .with_context(|| format!("missing {field}"))?
        .iter()
        .map(|entry| {
            entry
                .as_str()
                .with_context(|| format!("{field} contains a non-string"))
        })
        .collect()
}

struct MaxUtf8Bytes(usize);

impl Keyword for MaxUtf8Bytes {
    fn validate<'i>(
        &self,
        instance: &'i Value,
        location: &LazyLocation,
    ) -> Result<(), ValidationError<'i>> {
        if self.is_valid(instance) {
            Ok(())
        } else {
            Err(ValidationError::custom(
                Location::new(),
                location.into(),
                instance,
                format!("string exceeds {} UTF-8 bytes", self.0),
            ))
        }
    }

    fn is_valid(&self, instance: &Value) -> bool {
        instance.as_str().is_none_or(|value| value.len() <= self.0)
    }
}

fn max_utf8_bytes_factory<'a>(
    _parent: &'a Map<String, Value>,
    value: &'a Value,
    path: Location,
) -> Result<Box<dyn Keyword>, ValidationError<'a>> {
    let maximum = value
        .as_u64()
        .and_then(|value| usize::try_from(value).ok())
        .filter(|value| *value > 0)
        .ok_or_else(|| {
            ValidationError::custom(
                Location::new(),
                path,
                value,
                "x-hepta-max-utf8-bytes must be a positive integer",
            )
        })?;
    Ok(Box::new(MaxUtf8Bytes(maximum)))
}

#[derive(Clone, Copy)]
enum SafeTextProfile {
    RuntimeIdentifier,
    SafeMessage,
}

struct SafeTextProfileKeyword(SafeTextProfile);

impl Keyword for SafeTextProfileKeyword {
    fn validate<'i>(
        &self,
        instance: &'i Value,
        location: &LazyLocation,
    ) -> Result<(), ValidationError<'i>> {
        if self.is_valid(instance) {
            Ok(())
        } else {
            Err(ValidationError::custom(
                Location::new(),
                location.into(),
                instance,
                "string violates the required safe-text profile",
            ))
        }
    }

    fn is_valid(&self, instance: &Value) -> bool {
        instance.as_str().is_none_or(|value| {
            !value.chars().any(|character| {
                character.is_control()
                    || is_forbidden_directional_character(character)
                    || (matches!(self.0, SafeTextProfile::RuntimeIdentifier)
                        && character.is_whitespace())
            })
        })
    }
}

fn safe_text_profile_factory<'a>(
    _parent: &'a Map<String, Value>,
    value: &'a Value,
    path: Location,
) -> Result<Box<dyn Keyword>, ValidationError<'a>> {
    let profile = match value.as_str() {
        Some("runtime_identifier") => SafeTextProfile::RuntimeIdentifier,
        Some("safe_message") => SafeTextProfile::SafeMessage,
        _ => {
            return Err(ValidationError::custom(
                Location::new(),
                path,
                value,
                "unknown x-hepta-safe-text-profile",
            ));
        }
    };
    Ok(Box::new(SafeTextProfileKeyword(profile)))
}

fn is_forbidden_directional_character(character: char) -> bool {
    matches!(
        character,
        '\u{061c}'
            | '\u{200e}'..='\u{200f}'
            | '\u{202a}'..='\u{202e}'
            | '\u{2066}'..='\u{2069}'
    )
}

#[test]
fn writer_reproduces_the_tracked_artifact_set_byte_for_byte() -> Result<()> {
    let output = tempfile::tempdir()?;
    write_robrix_control_projection(output.path())?;
    assert_eq!(read_artifacts(output.path())?, read_tracked_artifacts()?);
    Ok(())
}

fn read_tracked_artifacts() -> Result<BTreeMap<String, Vec<u8>>> {
    read_artifacts(
        &std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("fixtures/robrix-control-v2"),
    )
}

fn read_artifacts(root: &std::path::Path) -> Result<BTreeMap<String, Vec<u8>>> {
    let mut artifacts = BTreeMap::new();
    for entry in fs::read_dir(root).with_context(|| format!("read {}", root.display()))? {
        let entry = entry?;
        let file_type = entry.file_type()?;
        if !file_type.is_file() {
            anyhow::bail!(
                "artifact set contains a non-file: {}",
                entry.path().display()
            );
        }
        let name = entry
            .file_name()
            .into_string()
            .map_err(|_| anyhow::anyhow!("artifact name is not UTF-8"))?;
        artifacts.insert(name, fs::read(entry.path())?);
    }
    Ok(artifacts)
}
