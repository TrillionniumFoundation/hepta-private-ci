//! Exact ordinary deployment data. Only the real Root loader authenticates
//! these files and derives frozen scope; this module writes no owner state.

use std::path::PathBuf;

use codex_hepta_types::Digest32;
use serde_json::Map;
use serde_json::Value;
use serde_json::json;

use super::deployment::digest;
use super::observer::read_private;
use super::post_a_file::OriginalFileData;
use super::post_a_plan::EPOCHS;
use super::post_a_plan::LEARNING_RATE_Q24;
use super::post_a_plan::OriginalPostAResources;
use super::post_a_plan::SNAPSHOT_ID;
use super::root::write_json;

pub(super) struct OriginalPostARootPlans {
    pub(super) historical: PathBuf,
    pub(super) learning: PathBuf,
    pub(super) publication: PathBuf,
    pub(super) independent_b: PathBuf,
    pub(super) publication_inputs: crate::authority_host_runtime::PublicationInputData,
}

pub(super) fn write_original_root_plans(
    resources: &OriginalPostAResources,
    profile: &crate::HostAuthorityLearningProfileV1,
) -> anyhow::Result<OriginalPostARootPlans> {
    let original = &resources.original;
    let directory = original.plan.protected.path();
    let initial = profile.original_initial_data()?;
    let trust_mapping = directory.join("post-a-trust-mapping.json");
    write_json(
        &trust_mapping,
        &json!({
            "schema":1,"purpose":"runtime.learning.historical-trust-deployment.v1",
            "mode":"pinned_genesis_v1","initial":initial.head_digest.to_string(),
            "target":original.plan.deployment.target,
            "learning_scope":Digest32::from_array(resources.trust.payload.distribution.scope_digest).to_string(),
            "signed_payload":resources.trust.payload_file,
            "freeze_evaluator":resources.trust.freezer
        }),
    )?;
    let source: Value = serde_json::from_slice(&read_private(&original.plan.root.source, 65_536)?)?;
    let ledger = source["ledger_deployment"]
        .as_str()
        .ok_or_else(|| anyhow::anyhow!("actual A original Ledger deployment absent"))?;
    let historical = directory.join("post-a-historical.json");
    write_json(
        &historical,
        &json!({
            "schema_version":1,"purpose":"runtime.learning.historical-task-deployment.v1",
            "initial":profile,"target":original.plan.deployment.target,
            "source_deployment":original.plan.root.source,
            "run_start_deployment":original.plan.root.run_start,
            "ledger_deployment":ledger,"learning_trust_deployment":trust_mapping
        }),
    )?;
    let baseline = original.plan.runtime.path().join("model");
    let baseline_pins = json!({
        "base":OriginalFileData::capture(&baseline.join("base"))?,
        "encoder":OriginalFileData::capture(&baseline.join("encoder"))?,
        "heads":OriginalFileData::capture(&baseline.join("heads"))?,
        "organ_adapter":null,"cell_adapter":null
    });
    let learning = directory.join("post-a-learning.json");
    let mut learning_data = Map::new();
    for (name, value) in [
        ("schema", json!(1)),
        ("purpose", json!("runtime.learning.post-a-deployment.v1")),
        ("initial", json!(initial.head_digest.to_string())),
        (
            "target",
            json!(Digest32::from_array(original.plan.deployment.target.digest()?).to_string()),
        ),
        (
            "learning_trust_mapping",
            json!(Digest32::of_bytes(&read_private(&trust_mapping, 65_536)?).to_string()),
        ),
        ("mode", json!("register")),
        ("baseline", baseline_pins),
        ("freeze", resources.owners.root_freeze_data()?),
        ("model_reservation", json!(resources.model_reservation)),
        ("snapshot_id", json!(SNAPSHOT_ID)),
        ("head", json!("drive")),
        ("index", json!(0)),
        ("epochs", json!(EPOCHS)),
        ("learning_rate_q24", json!(LEARNING_RATE_Q24)),
        ("input_width", json!(2)),
        (
            "inherited_inclusion_policy",
            json!(digest("ordinary-original-dataset-inclusion")),
        ),
        (
            "unit_profile",
            json!(digest("ordinary-observed-scalar-q24")),
        ),
        (
            "maximum_signature_lifetime_seconds",
            json!(resources.owners.signature_lifetime_seconds()),
        ),
    ] {
        learning_data.insert(name.into(), value);
    }
    write_json(&learning, &learning_data)?;
    let publication_inputs = original_publication_inputs(resources)?;
    let publication = directory.join("post-a-publication.json");
    write_json(
        &publication,
        &json!({
            "schema":2,"purpose":"runtime.learning.post-a-publication-deployment.v2",
            "initial":initial.head_digest.to_string(),"inputs":publication_inputs,
            "material":resources.c.publication_material,
            "successor":resources.c.root_successor_data()
        }),
    )?;
    Ok(OriginalPostARootPlans {
        historical,
        learning,
        publication,
        // The actual source child identity is fixed before Root exec. Its B
        // producer writes this separate original deployment, never a new grant.
        independent_b: directory.join("post-a-independent-b.json"),
        publication_inputs,
    })
}

pub(super) fn original_daemon_data(resources: &OriginalPostAResources) -> anyhow::Result<Vec<u8>> {
    let baseline = resources.original.plan.runtime.path().join("model");
    let mut value = Map::new();
    for (name, data) in [
        (
            "schema",
            json!("hepta.agentd.original_post_a_q24_launch.v1"),
        ),
        (
            "identity_digest",
            json!(
                crate::neuron_generation_process_identity_digest_v1(&resources.successor.identity)?
                    .to_string()
            ),
        ),
        (
            "baseline",
            json!({"base":baseline.join("base"),"encoder":baseline.join("encoder"),"heads":baseline.join("heads"),"organ_adapter":null,"cell_adapter":null}),
        ),
        ("head", json!({"kind":"drive","index":0})),
        ("epochs", json!(EPOCHS)),
        ("learning_rate_q24", json!(LEARNING_RATE_Q24)),
        (
            "inherited_inclusion_policy",
            json!(digest("ordinary-original-dataset-inclusion")),
        ),
        (
            "unit_profile_digest",
            json!(digest("ordinary-observed-scalar-q24")),
        ),
        ("snapshot_id", json!(SNAPSHOT_ID)),
        ("freeze", resources.owners.freeze_data()?),
        ("freeze_mode", json!("create")),
        ("stages", resources.owners.stage_data()),
        ("delivery", resources.owners.delivery_data()?),
        ("delivery_mode", json!("create")),
        ("queue_capacity", json!(4)),
        (
            "continuation",
            json!({"artifacts":resources.owners.artifact_data(),"task":resources.c.daemon_task_data(),"generation":resources.owners.generation_data()}),
        ),
    ] {
        value.insert(name.into(), data);
    }
    Ok(serde_json::to_vec(&value)?)
}

fn original_publication_inputs(
    resources: &OriginalPostAResources,
) -> anyhow::Result<crate::authority_host_runtime::PublicationInputData> {
    let original = &resources.original;
    let previous: Value =
        serde_json::from_slice(&read_private(&original.plan.root.initial, 65_536)?)?;
    let mut inputs = Map::new();
    for name in [
        "current_directory",
        "artifact_root",
        "owner_trust",
        "retained_current",
        "storage_binding",
        "withdrawal_file",
        "withdrawal",
        "selector_trust",
        "consumer",
        "consumer_state_root",
        "issuer_keys",
    ] {
        inputs.insert(
            name.into(),
            previous
                .get(name)
                .ok_or_else(|| anyhow::anyhow!("original Initial field absent: {name}"))?
                .clone(),
        );
    }
    for (name, data) in [
        ("mode", json!("reserve")),
        ("previous_journal", json!(original.plan.target_journal)),
        ("previous_witness", json!(original.plan.target_witness)),
        (
            "previous",
            previous
                .get("target")
                .ok_or_else(|| anyhow::anyhow!("actual A target absent"))?
                .clone(),
        ),
        ("target_journal", json!(resources.c.generation_journal.path)),
        ("target_witness", json!(resources.c.generation_witness.path)),
    ] {
        inputs.insert(name.into(), data);
    }
    // Decode the product's strict DTO. This authenticates no ownership; the
    // original Root later opens every actual file and verifies its old Current.
    Ok(serde_json::from_value(Value::Object(inputs))?)
}
