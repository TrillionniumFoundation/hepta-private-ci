//! Native parity over externally saved checkpoints and actual fresh-reader files.
//! This helper performs no fitting and does not derive reference logits itself.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::io::Write;
use std::path::Path;

use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::MemoryInventoryKindV1;
use codex_hepta_cognitive_types::MemoryInventoryValueV1;
use codex_hepta_neuron::MemoryResidualCellV1;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use serde::Deserialize;
use serde_json::{Value, json};

use crate::MemoryInventorySnapshotPageV1;

const ABSOLUTE_TOLERANCE: f64 = 0.0001;
const RELATIVE_TOLERANCE: f64 = 0.00001;

#[derive(Deserialize)]
struct Reference {
    artifact_sha256: String,
    parameter_sha256: String,
    kind: MemoryCellKindV1,
    rows: Vec<ReferenceRow>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ReferenceRow {
    address_sha256: String,
    raw_logits: Vec<f64>,
    source_ids: Vec<String>,
    value: Option<Vec<u8>>,
    minimum_margin: f64,
    accepted: bool,
}

pub(super) fn verify(directory: &Path, pages: &[MemoryInventorySnapshotPageV1]) -> Value {
    let owner = pages.first().expect("actual owner snapshot");
    for page in pages {
        assert_eq!((&page.owner_agent_id, &page.scope, page.owner_cut_digest),
            (&owner.owner_agent_id, &owner.scope, owner.owner_cut_digest));
    }
    let process_bytes = std::fs::read(directory.join("PROCESSES.json")).expect("actual Python process ledger");
    let processes: Vec<Value> = serde_json::from_slice(&process_bytes).expect("process ledger JSON");
    let producers = processes.iter().enumerate().filter(|(_, row)|
        matches!(row["label"].as_str(), Some("training" | "original-torch"))).collect::<Vec<_>>();
    assert_eq!(producers.len(), 1, "one completed fitting or original-checkpoint reader process");
    assert_eq!(producers[0].1["exit_code"], json!(0));
    let mut models = Vec::new();
    for (name, kind, source_kind, width) in [
        ("semantic", MemoryCellKindV1::Semantic, MemoryInventoryKindV1::Semantic, 12),
        ("procedure", MemoryCellKindV1::Procedure, MemoryInventoryKindV1::Procedure, 28),
    ] {
        let reader_label = format!("read-{name}");
        let readers = processes.iter().enumerate().filter(|(_, row)| row["label"] == reader_label).collect::<Vec<_>>();
        assert_eq!(readers.len(), 1, "one actual fresh reader for each parameter kind");
        assert!(readers[0].0 > producers[0].0);
        assert_eq!(readers[0].1["exit_code"], json!(0));
        let payload = std::fs::read(directory.join(format!("{name}.json"))).expect("actual exported parameter bytes");
        let artifact_digest = Digest32::of_bytes(&payload);
        let model = MemoryResidualCellV1::from_bytes(&payload, artifact_digest).expect("native exact tensor decoder");
        let reference_bytes = std::fs::read(directory.join(format!("{name}-reference.json"))).expect("fresh-process reference file");
        let reference: Reference = serde_json::from_slice(&reference_bytes).expect("actual scalar reader output");
        assert_eq!((model.kind(), reference.kind), (kind, kind));
        assert_eq!(reference.artifact_sha256, artifact_digest.to_string());
        assert_eq!(reference.parameter_sha256, model.parameters_digest().to_string());
        assert_eq!(model.owner_cut_digest(), owner.owner_cut_digest.digest());
        let sources = pages.iter().flat_map(|page| &page.records)
            .filter(|row| row.record.kind == source_kind).collect::<Vec<_>>();
        let expected_supports = sources.iter().map(|row| (
            Digest32::of_bytes(row.record.key.as_str().as_bytes()).to_string(), vec![row.source_id.to_string()],
        )).collect::<BTreeMap<_, _>>();
        assert_eq!(expected_supports.len(), sources.len());
        assert_eq!(model.supports(), &expected_supports);
        let expected_lineage = sources.iter().map(|row| row.source_id.to_string()).collect::<BTreeSet<_>>()
            .into_iter().collect::<Vec<_>>();
        assert_eq!(model.lineage_sources(), expected_lineage.as_slice());
        let references = reference.rows.iter().map(|row| (row.address_sha256.clone(), row)).collect::<BTreeMap<_, _>>();
        assert_eq!(references.len(), reference.rows.len(), "reference addresses must be unique");
        assert_eq!(references.keys().collect::<Vec<_>>(), expected_supports.keys().collect::<Vec<_>>());
        let mut rows = Vec::new();
        for source in sources {
            let address = Digest32::of_bytes(source.record.key.as_str().as_bytes()).to_string();
            let expected = references[&address];
            let prediction = model.predict(source.record.key.as_str()).expect("actual Rust parameter inference");
            assert_eq!(prediction.logits.len(), width);
            assert_eq!(expected.raw_logits.len(), width);
            let mut maximum_error = 0.0_f64;
            for (actual, expected) in prediction.logits.iter().zip(&expected.raw_logits) {
                assert!(actual.is_finite() && expected.is_finite());
                let error = (actual - expected).abs();
                assert!(error <= ABSOLUTE_TOLERANCE + RELATIVE_TOLERANCE * expected.abs(),
                    "{name} address {address}: native {actual} differs from saved reference {expected}");
                maximum_error = maximum_error.max(error);
            }
            assert!(prediction.minimum_margin.is_finite() && expected.minimum_margin.is_finite());
            assert!((prediction.minimum_margin - expected.minimum_margin).abs()
                <= ABSOLUTE_TOLERANCE + RELATIVE_TOLERANCE * expected.minimum_margin.abs());
            let typed = match &prediction.value {
                Some(MemoryInventoryValueV1::Semantic(policy)) => Some(vec![policy.reserve, policy.pack, policy.limit]),
                Some(MemoryInventoryValueV1::Procedure(program)) => Some(program.opcodes.to_vec()),
                None => None,
            };
            assert_eq!(typed, expected.value);
            assert_eq!(prediction.value.is_some(), expected.accepted);
            assert_eq!(prediction.abstain.is_none(), expected.accepted);
            assert_eq!(prediction.kind, kind);
            assert_eq!(prediction.artifact_digest, reference.artifact_sha256);
            assert_eq!(prediction.parameter_digest, reference.parameter_sha256);
            let written_sources = vec![source.source_id.to_string()];
            assert_eq!(expected.source_ids, written_sources);
            let accepted_sources = if expected.accepted { written_sources } else { Vec::new() };
            assert_eq!(prediction.source_ids, accepted_sources);
            rows.push(json!({"key":source.record.key,"address_sha256":address,
                "native_prediction":prediction,"reference_logits":expected.raw_logits,
                "reference_value":expected.value,"reference_minimum_margin":expected.minimum_margin,
                "maximum_absolute_logit_error":maximum_error,"within_declared_tolerance":true}));
        }
        models.push(json!({"kind":name,"artifact_sha256":artifact_digest.to_string(),
            "parameter_sha256":model.parameters_digest().to_string(),"head_sha256":model.head_digest().to_string(),
            "encoder_sha256":model.encoder_digest().to_string(),"numeric_profile":model.numeric_profile(),
            "reference_file_sha256":Digest32::of_bytes(&reference_bytes).to_string(),
            "fresh_reference_process_receipt":readers[0].1,"lineage_sources":model.lineage_sources(),
            "charged_artifact_categories":model.cost(),"rows":rows}));
    }
    let receipt = json!({"schema":"hepta.memory.inventory-native-numeric-actual.v1","status":"passed",
        "native_pid":std::process::id(),"owner_agent_id":owner.owner_agent_id,"scope":owner.scope,
        "owner_cut_digest":owner.owner_cut_digest,"absolute_tolerance":ABSOLUTE_TOLERANCE,
        "relative_tolerance":RELATIVE_TOLERANCE,"python_process_ledger_sha256":Digest32::of_bytes(&process_bytes).to_string(),
        "measurement_scope":"Rust decoder and predictor over the exact artifacts before signed owner installation; reference bytes are from completed external fresh-reader processes",
        "models":models});
    let bytes = serde_json::to_vec_pretty(&receipt).expect("native parity evidence JSON");
    let path = directory.join("RUST_NATIVE_PARITY.json");
    let mut file = std::fs::File::create_new(&path).expect("new immutable native parity receipt");
    file.write_all(&bytes).expect("write native parity receipt");
    file.sync_all().expect("durable native parity receipt");
    json!({"path":path,"sha256":Digest32::of_bytes(&bytes).to_string(),"status":"passed","models":2})
}
