//! Untrusted deployment/wire data tests. These do not establish Root custody,
//! a retired publisher, or a completed successor.

use super::*;
use crate::authority_host_service::generation_publication::Command;
use crate::authority_host_service::generation_publication::PublicationVersion;
use crate::authority_host_service::generation_publication::Request;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

fn fixture() -> RootSuccessorTaskFilesDataV1 {
    let file = |inode| MaterialData {
        path: std::path::PathBuf::from(format!("/original/successor/{inode}")),
        device: 1,
        inode,
        uid: 1000,
        gid: 1000,
        mode: 0o100600,
    };
    RootSuccessorTaskFilesDataV1 {
        source_configuration: file(/*inode*/ 1),
        target_configuration: file(/*inode*/ 2),
        signed_ingress: file(/*inode*/ 3),
        source_journal: file(/*inode*/ 4),
        source_witness: file(/*inode*/ 5),
        cell_journal: file(/*inode*/ 6),
        cell_witness: file(/*inode*/ 7),
        inference_control: file(/*inode*/ 8),
        cell_witness_scope: [1; 32],
        cell_witness_objective: [2; 32],
        cell_witness_generation: 1,
        cell_witness_records: 16,
        maximum_cell_records: 16,
        inference_capacity: 2,
        worker_generation: 1,
    }
}

#[test]
fn successor_deployment_requires_every_original_pin_and_bounded_context() -> anyhow::Result<()> {
    let value = serde_json::to_value(fixture())?;
    fixture().require_bounds()?;
    let fields = value
        .as_object()
        .ok_or_else(|| anyhow::anyhow!("object fixture"))?;
    for name in fields.keys() {
        let mut missing = fields.clone();
        missing.remove(name);
        assert!(
            serde_json::from_value::<RootSuccessorTaskFilesDataV1>(Value::Object(missing)).is_err(),
            "missing {name}"
        );
    }
    for field in [
        "source_configuration",
        "target_configuration",
        "signed_ingress",
        "source_journal",
        "source_witness",
        "cell_journal",
        "cell_witness",
        "inference_control",
    ] {
        let mut changed = value.clone();
        changed[field]["inode"] = json!(0);
        let changed: RootSuccessorTaskFilesDataV1 = serde_json::from_value(changed)?;
        assert!(changed.require_bounds().is_err(), "zero identity {field}");
    }
    for (field, invalid) in [
        ("cell_witness_records", 4097),
        ("maximum_cell_records", 17),
        ("inference_capacity", 65),
        ("worker_generation", 0),
    ] {
        let mut changed = value.clone();
        changed[field] = json!(invalid);
        assert!(
            serde_json::from_value::<RootSuccessorTaskFilesDataV1>(changed)?
                .require_bounds()
                .is_err(),
            "unbounded {field}"
        );
    }
    let mut unknown = value;
    unknown["retired"] = json!(true);
    assert!(serde_json::from_value::<RootSuccessorTaskFilesDataV1>(unknown).is_err());
    Ok(())
}

#[test]
fn successor_deployment_rejects_path_and_inode_aliases() -> anyhow::Result<()> {
    let original = serde_json::to_value(fixture())?;
    let fields = [
        "source_configuration",
        "target_configuration",
        "signed_ingress",
        "source_journal",
        "source_witness",
        "cell_journal",
        "cell_witness",
        "inference_control",
    ];
    for (index, field) in fields.iter().enumerate() {
        for prior in &fields[..index] {
            for alias in ["path", "inode"] {
                let mut changed = original.clone();
                changed[*field][alias] = original[*prior][alias].clone();
                assert!(
                    serde_json::from_value::<RootSuccessorTaskFilesDataV1>(changed)?
                        .require_bounds()
                        .is_err(),
                    "{field} aliases {prior} through {alias}"
                );
            }
        }
    }
    Ok(())
}

#[test]
fn successor_capture_and_read_commands_accept_no_peer_business_fields() -> anyhow::Result<()> {
    for kind in ["capture_retired_task", "read_finalized_task"] {
        let original = json!({"kind": kind});
        let command: Command = serde_json::from_value(original.clone())?;
        assert_eq!(serde_json::to_value(command)?, original);
        for field in [
            "retired", "identity", "profile", "cut", "path", "intent", "phase",
        ] {
            let mut changed = original.clone();
            changed[field] = json!(true);
            assert!(
                serde_json::from_value::<Command>(changed).is_err(),
                "peer {field}"
            );
        }
        let mut request = json!({"schema": 2, "purpose": PublicationVersion::DurableV2.purpose(), "request_id": 3, "profile": "exact", "command": original});
        let _: Request = serde_json::from_value(request.clone())?;
        request["successor"] = json!({"phase":"finalized"});
        assert!(serde_json::from_value::<Request>(request).is_err());
    }
    Ok(())
}
