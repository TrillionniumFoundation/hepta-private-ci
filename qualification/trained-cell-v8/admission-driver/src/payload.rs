//! Authenticate the full-state envelope and the externally pinned controller
//! family. This layer does not execute or reinterpret a controller algorithm.
use crate::Result;
use crate::ensure;
use crate::profile::Profile;
use crate::profile::family;
use crate::report::array;
use crate::report::hash;
use crate::report::read;
use crate::report::string;
use codex_hepta_types::Digest32;
use hepta_handoff_recovery_v7::handoff_version::Handoff;
use serde_json::Value;
use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::path::Path;

pub fn verify(
    profile: &Profile,
    gate: &Value,
    conversion_path: &Path,
    contracts_path: &Path,
    predecessor: &[u8],
    candidate: &[u8],
) -> Result<()> {
    ensure(
        conversion_path
            .file_name()
            .is_some_and(|name| name == "manifest.json"),
        "parity conversion must be the exact manifest.json used by the owner",
    )?;
    let conversion_bytes = read(conversion_path)?;
    let contracts_bytes = read(contracts_path)?;
    ensure(
        Digest32::of_bytes(&conversion_bytes) == hash(gate, "conversion_manifest_sha256")?
            && Digest32::of_bytes(&contracts_bytes)
                == hash(profile.value(), "controller_contracts_sha256")?,
        "conversion or externally pinned controller contracts changed",
    )?;
    let conversion: Value = serde_json::from_slice(&conversion_bytes)?;
    let contracts: Value = serde_json::from_slice(&contracts_bytes)?;
    let protocol = hash(profile.value(), "protocol_sha256")?;
    ensure(
        conversion["scope"] == profile.value()["conversion_scope"]
            && contracts["schema"] == "hepta.controller-contract-family.v1"
            && hash(&contracts, "protocol_sha256")? == protocol,
        "conversion scope or contract profile differs",
    )?;
    let expected = contracts["cells"]
        .as_object()
        .ok_or("controller family missing")?;
    ensure(
        expected.keys().cloned().collect::<BTreeSet<_>>() == family(),
        "externally pinned controller family is incomplete",
    )?;
    let root = conversion_path
        .parent()
        .ok_or("conversion directory missing")?;
    // Only legacy data enters its historical whole-buffer path. Large V8
    // vectors/references use the independently bounded full-stream reader.
    if profile.version() == 7 {
        for name in [
            "predecessor.bin",
            "candidate.bin",
            "vectors.bin",
            "expected.bin",
        ] {
            read(&root.join(name))?;
        }
    }
    let parity = hepta_handoff_recovery_v7::parity_profile::Inputs::load(root)?;
    ensure(
        parity.manifest() == &conversion,
        "parity reader observed a different conversion manifest",
    )?;
    match (&parity, profile.version()) {
        (hepta_handoff_recovery_v7::parity_profile::Inputs::Legacy(_), 7) => {}
        (hepta_handoff_recovery_v7::parity_profile::Inputs::Streaming(stream), 8) => ensure(
            stream.header_digest == hash(profile.value(), "parity_header_sha256")?,
            "full-row stream header differs from its pre-evaluation host pin",
        )?,
        _ => return Err("controller and parity mode substitution".into()),
    }
    parity.verify_family(&protocol.to_string())?;
    let versions = array(parity.data_manifest(), "versions")?;
    let mut bundles = Vec::new();
    for (index, bytes) in [predecessor, candidate].into_iter().enumerate() {
        let bundle = Handoff::decode(bytes, Digest32::of_bytes(bytes))?;
        let meta = &versions[index];
        let name = ["predecessor", "candidate"][index];
        let id = ["all12-typed-warmup-v5", "all12-typed-candidate-v5"][index];
        ensure(
            bundle.version() == profile.version()
                && bundle.protocol_digest() == protocol
                && bundle.artifact_id().as_str() == id
                && bundle.generation().get() == index as u64 + 1
                && meta["name"] == name
                && bundle.serving().encode() == parity.payloads()[index]
                && hash(meta, "handoff_payload_sha256")? == bundle.content_digest()
                && hash(meta, "source_bundle_sha256")?
                    == hash(gate, &format!("source_{name}_bundle_sha256"))?,
            "full-state, serving or source-bundle binding differs",
        )?;
        let binding = bundle.serving().input_binding();
        ensure(
            binding.encoder_digest == hash(meta, "encoder_sha256")?
                && binding.projection_digest == hash(meta, "projection_sha256")?
                && binding.normalization_digest == hash(meta, "normalization_sha256")?,
            "serving input identity differs",
        )?;
        for checkpoint in bundle.checkpoints() {
            let wrapper: Value = serde_json::from_slice(checkpoint.controller_metadata_json())?;
            let source_text = string(&wrapper, "source_controller_json")?;
            let source: Value = serde_json::from_str(source_text)?;
            let contract = &source["contract"];
            ensure(
                expected.get(checkpoint.cell_id().as_str()) == Some(contract)
                    && source["schema"] == profile.value()["controller_schema"]
                    && hash(contract, "controller_source_sha256")?
                        == hash(profile.value(), "training_code_sha256")?,
                "controller algorithm, complete contract or source closure differs",
            )?;
            // Preserve Python's exact canonical float spelling, including 1e-08.
            // Re-serializing these values with Rust's formatter would change hashes.
            let raw: BTreeMap<String, &serde_json::value::RawValue> =
                serde_json::from_str(source_text)?;
            let raw: BTreeMap<String, &serde_json::value::RawValue> =
                serde_json::from_str(raw.get("contract").ok_or("raw contract missing")?.get())?;
            let get = |key: &str| -> Result<&str> {
                Ok(raw.get(key).ok_or("raw contract field missing")?.get())
            };
            let panels = format!(
                "{{\"current_panel_sha256\":{},\"old_panel_sha256\":{},\"training_sha256\":{}}}",
                get("current_panel_sha256")?,
                get("old_panel_sha256")?,
                get("training_sha256")?
            );
            for (field, bytes) in [
                ("controller_config_sha256", get("configuration")?.as_bytes()),
                (
                    "panel_anchors_sha256",
                    get("original_old_anchors")?.as_bytes(),
                ),
                ("panel_identity_sha256", panels.as_bytes()),
            ] {
                ensure(
                    hash(&wrapper, field)? == Digest32::of_bytes(bytes),
                    "controller configuration or original panel commitment differs",
                )?;
            }
        }
        bundles.push(bundle);
    }
    ensure(
        bundles[0].predecessor_digest().is_none()
            && bundles[1].predecessor_digest() == Some(bundles[0].content_digest()),
        "immutable full-state predecessor differs",
    )?;
    for (before, after) in bundles[0]
        .checkpoints()
        .iter()
        .zip(bundles[1].checkpoints())
    {
        let old: Value = serde_json::from_slice(before.state_metadata_json())?;
        let new: Value = serde_json::from_slice(after.state_metadata_json())?;
        let start: Value = serde_json::from_slice(before.controller_metadata_json())?;
        let end: Value = serde_json::from_slice(after.controller_metadata_json())?;
        ensure(
            before.cell_id() == after.cell_id()
                && old["bindings"] == new["bindings"]
                && old["protocol"] == new["protocol"]
                && old["contexts"] == new["contexts"]
                && start["absolute_step"] == 0
                && end["original_warmup_state_sha256"] == start["state_sha256"]
                && end["warmup_step_count"] == old["step_count"],
            "candidate does not extend the exact original optimizer warmup",
        )?;
    }
    Ok(())
}
