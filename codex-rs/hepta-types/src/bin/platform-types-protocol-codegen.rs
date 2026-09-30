//! Generate candidate-bound protocol catalog projections from Rust descriptors.

use std::error::Error;
use std::fs;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::protocol_catalog_v2::PLATFORM_TYPES_PROTOCOL_CATALOG_V2;
use codex_hepta_types::protocol_catalog_v2::ProtocolDescriptorV2;
use codex_hepta_types::protocol_catalog_v2::identity_fields_for_protocol_v2;
use codex_hepta_types::protocol_catalog_v2::identity_profile_for_protocol_field_v2;

fn main() {
    if let Err(error) = run() {
        eprintln!("platform.types protocol codegen failed: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn Error>> {
    let arguments = std::env::args().collect::<Vec<_>>();
    if arguments.len() != 5 || arguments[1] != "--json" || arguments[3] != "--markdown" {
        return Err(
            "usage: platform-types-protocol-codegen --json <path> --markdown <path>".into(),
        );
    }
    verify_executable_schemas()?;
    write(Path::new(&arguments[2]), &render_json())?;
    write(Path::new(&arguments[4]), &render_markdown())?;
    println!(
        "platform.types protocol catalog: {} Rust-owned descriptors",
        PLATFORM_TYPES_PROTOCOL_CATALOG_V2.len()
    );
    Ok(())
}

fn verify_executable_schemas() -> Result<(), Box<dyn Error>> {
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    for protocol in PLATFORM_TYPES_PROTOCOL_CATALOG_V2 {
        let Some(relative) = protocol.transport_schema else {
            continue;
        };
        let path = manifest.join(relative);
        let schema = fs::read_to_string(&path)?;
        for field in protocol.fields {
            let needle = format!("\"{}\"", field.name);
            if !schema.contains(&needle) {
                return Err(format!(
                    "{} is missing field {} from Rust descriptor",
                    path.display(),
                    field.name
                )
                .into());
            }
        }
    }
    Ok(())
}

fn write(path: &Path, value: &str) -> Result<(), Box<dyn Error>> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(path, value)?;
    Ok(())
}

fn render_json() -> String {
    let mut output = String::from(
        "{\n  \"schema\": \"hepta.platform-types.protocol-catalog.v2\",\n  \"schemaVersion\": 2,\n  \"normativeSource\": \"codex-rs/hepta-types/src/protocol_catalog_v2.rs\",\n",
    );
    output.push_str(&format!(
        "  \"protocolCount\": {},\n  \"protocols\": [\n",
        PLATFORM_TYPES_PROTOCOL_CATALOG_V2.len()
    ));
    for (protocol_index, protocol) in PLATFORM_TYPES_PROTOCOL_CATALOG_V2.iter().enumerate() {
        output.push_str("    {\n");
        push_json_string(&mut output, "      ", "id", protocol.id, true);
        output.push_str(&format!("      \"version\": {},\n", protocol.version));
        push_json_string(
            &mut output,
            "      ",
            "semanticTypeId",
            protocol.semantic_type_id,
            true,
        );
        push_json_string(
            &mut output,
            "      ",
            "semanticEncoding",
            protocol.semantic_encoding,
            true,
        );
        match protocol.transport_schema {
            Some(value) => push_json_string(&mut output, "      ", "transportSchema", value, true),
            None => output.push_str("      \"transportSchema\": null,\n"),
        }
        push_json_string(
            &mut output,
            "      ",
            "codecOwner",
            protocol.codec_owner,
            true,
        );
        push_json_string(
            &mut output,
            "      ",
            "compatibility",
            protocol.compatibility,
            true,
        );
        output.push_str("      \"fields\": [\n");
        for (field_index, field) in protocol.fields.iter().enumerate() {
            output.push_str("        {\n");
            push_json_string(&mut output, "          ", "name", field.name, true);
            push_json_string(&mut output, "          ", "wireType", field.wire_type, true);
            output.push_str(&format!(
                "          \"required\": {},\n",
                if field.required { "true" } else { "false" }
            ));
            if let Some(maximum) = field.maximum_encoded_bytes {
                output.push_str(&format!("          \"maximumEncodedBytes\": {maximum},\n"));
            }
            match identity_profile_for_protocol_field_v2(protocol.id, field.name) {
                Some(profile) => push_json_string(
                    &mut output,
                    "          ",
                    "identityProfile",
                    profile.id(),
                    false,
                ),
                None => output.push_str("          \"identityProfile\": null\n"),
            }
            output.push_str("        }");
            if field_index + 1 != protocol.fields.len() {
                output.push(',');
            }
            output.push('\n');
        }
        output.push_str("      ],\n");
        output.push_str("      \"identityFields\": [\n");
        let identity_fields = identity_fields_for_protocol_v2(protocol.id).unwrap_or(&[]);
        for (identity_index, identity) in identity_fields.iter().enumerate() {
            output.push_str("        {\n");
            push_json_string(&mut output, "          ", "path", identity.path, true);
            push_json_string(
                &mut output,
                "          ",
                "profile",
                identity.profile.id(),
                false,
            );
            output.push_str("        }");
            if identity_index + 1 != identity_fields.len() {
                output.push(',');
            }
            output.push('\n');
        }
        output.push_str("      ]\n    }");
        if protocol_index + 1 != PLATFORM_TYPES_PROTOCOL_CATALOG_V2.len() {
            output.push(',');
        }
        output.push('\n');
    }
    output.push_str("  ]\n}\n");
    output
}

fn push_json_string(output: &mut String, indentation: &str, name: &str, value: &str, comma: bool) {
    output.push_str(indentation);
    output.push('"');
    output.push_str(name);
    output.push_str("\": \"");
    output.push_str(&json_escape(value));
    output.push('"');
    if comma {
        output.push(',');
    }
    output.push('\n');
}

fn json_escape(value: &str) -> String {
    value
        .replace('\\', "\\\\")
        .replace('"', "\\\"")
        .replace('\n', "\\n")
        .replace('\r', "\\r")
        .replace('\t', "\\t")
}

fn render_markdown() -> String {
    let mut output = String::from(
        "# platform.types generated protocol catalog V2\n\nNormative source: `codex-rs/hepta-types/src/protocol_catalog_v2.rs`. This file is generated; edit the Rust descriptors, not this table.\n\n",
    );
    for protocol in PLATFORM_TYPES_PROTOCOL_CATALOG_V2 {
        render_protocol_markdown(&mut output, protocol);
    }
    output
}

fn render_protocol_markdown(output: &mut String, protocol: &ProtocolDescriptorV2) {
    output.push_str(&format!("## {} V{}\n\n", protocol.id, protocol.version));
    output.push_str(&format!(
        "- Semantic identity: `{}`\n- Encoding: `{}`\n- Transport schema: `{}`\n- Codec owner: `{}`\n- Compatibility: `{}`\n\n",
        protocol.semantic_type_id,
        protocol.semantic_encoding,
        protocol.transport_schema.unwrap_or("native-only"),
        protocol.codec_owner,
        protocol.compatibility,
    ));
    output.push_str(
        "| Field | Wire type | Required | Maximum encoded bytes | Identity profile |\n|---|---|---:|---:|---|\n",
    );
    for field in protocol.fields {
        let maximum = field
            .maximum_encoded_bytes
            .map_or_else(|| "—".to_owned(), |value| value.to_string());
        let identity_profile = identity_profile_for_protocol_field_v2(protocol.id, field.name)
            .map_or("—", |profile| profile.id());
        output.push_str(&format!(
            "| `{}` | `{}` | {} | {} | `{}` |\n",
            field.name,
            field.wire_type,
            if field.required { "yes" } else { "no" },
            maximum,
            identity_profile,
        ));
    }
    let identity_fields = identity_fields_for_protocol_v2(protocol.id).unwrap_or(&[]);
    if !identity_fields.is_empty() {
        output.push_str("\nIdentity-bearing paths:\n\n");
        for identity in identity_fields {
            output.push_str(&format!(
                "- `{}` → `{}`\n",
                identity.path,
                identity.profile.id(),
            ));
        }
    }
    output.push('\n');
}
