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
    if !codex_utils_cargo_bin::runfiles_available() {
        // Cargo keeps strict enumeration of the source fixture directory.
        return read_artifacts(
            &std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("fixtures/robrix-control-v2"),
        );
    }
    let mut resources = Vec::new();
    for name in [
        MANIFEST_FILE,
        CORPUS_FILE,
        GENERATED_CONSTANTS_FILE,
        MATRIXD_SCHEMA_FILE,
        SUPERVISORD_SCHEMA_FILE,
    ] {
        // Resolve every declared resource before following delivery symlinks.
        let resource = format!("fixtures/robrix-control-v2/{name}");
        resources.push((name, codex_utils_cargo_bin::find_resource!(resource)?));
    }
    read_artifacts(&validated_fixture_backing_root(&resources)?)
}

// Bazel may deliver declared data through symlinks, including in manifest mode.
// Only the five successfully resolved resources may establish the backing root.
fn validated_fixture_backing_root(
    resources: &[(&str, std::path::PathBuf)],
) -> std::io::Result<std::path::PathBuf> {
    use std::io::{Error, ErrorKind};
    let invalid = |message| Error::new(ErrorKind::InvalidData, message);
    let expected: BTreeSet<_> = resources.iter().map(|(name, _)| *name).collect();
    if resources.len() != 5 || expected.len() != 5 {
        return Err(invalid(
            "exactly five distinct fixture resources are required",
        ));
    }
    let mut root = None;
    for (name, delivered) in resources {
        let backing = fs::canonicalize(delivered)?;
        if !fs::metadata(&backing)?.is_file()
            || backing.file_name() != Some(std::ffi::OsStr::new(name))
        {
            return Err(invalid(
                "fixture backing must be a regular file with its declared name",
            ));
        }
        let parent = backing
            .parent()
            .ok_or_else(|| invalid("fixture has no parent"))?;
        if let Some(expected_root) = &root {
            if expected_root != parent {
                return Err(invalid(
                    "fixture resources have different backing directories",
                ));
            }
        } else {
            root = Some(parent.to_path_buf());
        }
    }
    let root = root.ok_or_else(|| invalid("fixture root is missing"))?;
    let mut actual = BTreeSet::new();
    for entry in fs::read_dir(&root)? {
        let entry = entry?;
        if !entry.file_type()?.is_file() {
            return Err(invalid("fixture backing directory contains a non-file"));
        }
        actual.insert(
            entry
                .file_name()
                .into_string()
                .map_err(|_| invalid("fixture name is not UTF-8"))?,
        );
    }
    if actual.iter().map(String::as_str).collect::<BTreeSet<_>>() != expected {
        return Err(invalid(
            "fixture backing directory does not match the declared set",
        ));
    }
    Ok(root)
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

#[cfg(all(test, unix))]
mod fixture_backing_tests {
    use super::*;
    use std::path::PathBuf;
    use std::sync::atomic::{AtomicUsize, Ordering};
    const NAMES: [&str; 5] = [
        "manifest.json",
        "corpus.json",
        "constants.rs",
        "matrix.json",
        "supervisor.json",
    ];
    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> std::io::Result<Self> {
            static NEXT: AtomicUsize = AtomicUsize::new(0);
            for _ in 0..1024 {
                let path = std::env::temp_dir().join(format!(
                    "hepta-backing-{}-{}",
                    std::process::id(),
                    NEXT.fetch_add(1, Ordering::Relaxed)
                ));
                match fs::create_dir(&path) {
                    Ok(()) => {
                        let fixture = Self(path);
                        fs::create_dir(fixture.0.join("physical"))?;
                        for name in NAMES {
                            fs::write(fixture.0.join("physical").join(name), name)?;
                        }
                        return Ok(fixture);
                    }
                    Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
                    Err(error) => return Err(error),
                }
            }
            Err(std::io::Error::new(
                std::io::ErrorKind::AlreadyExists,
                "could not reserve a fresh fixture directory",
            ))
        }
        fn resources(&self) -> Vec<(&'static str, PathBuf)> {
            NAMES
                .into_iter()
                .map(|n| (n, self.0.join("physical").join(n)))
                .collect()
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            if let Err(error) = fs::remove_dir_all(&self.0) {
                panic!("remove fixture directory {}: {error}", self.0.display());
            }
        }
    }
    #[test]
    fn regular_backing_passes() {
        let f = Fixture::new().unwrap();
        assert_eq!(
            validated_fixture_backing_root(&f.resources()).unwrap(),
            fs::canonicalize(f.0.join("physical")).unwrap()
        );
    }
    #[test]
    fn symlink_delivery_passes() {
        let f = Fixture::new().unwrap();
        fs::create_dir(f.0.join("delivery")).unwrap();
        let resources: Vec<_> = f
            .resources()
            .into_iter()
            .map(|(n, p)| {
                let link = f.0.join("delivery").join(n);
                std::os::unix::fs::symlink(p, &link).unwrap();
                (n, link)
            })
            .collect();
        assert_eq!(
            validated_fixture_backing_root(&resources).unwrap(),
            fs::canonicalize(f.0.join("physical")).unwrap()
        );
    }
    #[test]
    fn missing_resource_rejected_even_when_backing_exists() {
        let f = Fixture::new().unwrap();
        let mut r = f.resources();
        r[1].1 = f.0.join("missing-delivery");
        assert!(validated_fixture_backing_root(&r).is_err());
    }
    #[test]
    fn partial_declaration_rejected() {
        let f = Fixture::new().unwrap();
        assert!(validated_fixture_backing_root(&f.resources()[..4]).is_err());
    }
    #[test]
    fn different_parent_rejected() {
        let f = Fixture::new().unwrap();
        fs::create_dir(f.0.join("other")).unwrap();
        let mut r = f.resources();
        let p = f.0.join("other").join(NAMES[1]);
        fs::write(&p, b"same").unwrap();
        r[1].1 = p;
        assert!(validated_fixture_backing_root(&r).is_err());
    }
    #[test]
    fn extra_file_rejected() {
        let f = Fixture::new().unwrap();
        fs::write(f.0.join("physical/extra"), b"extra").unwrap();
        assert!(validated_fixture_backing_root(&f.resources()).is_err());
    }
    #[test]
    fn directory_entry_rejected() {
        let f = Fixture::new().unwrap();
        fs::create_dir(f.0.join("physical/extra")).unwrap();
        assert!(validated_fixture_backing_root(&f.resources()).is_err());
    }
    #[test]
    fn backing_symlink_entry_rejected() {
        let f = Fixture::new().unwrap();
        std::os::unix::fs::symlink("manifest.json", f.0.join("physical/extra")).unwrap();
        assert!(validated_fixture_backing_root(&f.resources()).is_err());
    }
    #[test]
    fn renamed_backing_rejected() {
        let f = Fixture::new().unwrap();
        let mut r = f.resources();
        r[1].1 = r[0].1.clone();
        assert!(validated_fixture_backing_root(&r).is_err());
    }
    #[test]
    fn nonregular_resource_rejected() {
        let f = Fixture::new().unwrap();
        fs::remove_file(f.0.join("physical/manifest.json")).unwrap();
        fs::create_dir(f.0.join("physical/manifest.json")).unwrap();
        assert!(validated_fixture_backing_root(&f.resources()).is_err());
    }
}
