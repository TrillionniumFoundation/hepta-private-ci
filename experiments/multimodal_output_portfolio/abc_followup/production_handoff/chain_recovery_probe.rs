//! Exercise recovery on private copies of the retained real 1,600-tick stream.
mod neuron_chain_recovery;

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use codex_hepta_neuron::{JournalAnchor, JournalScope, SparseConfig};
use codex_hepta_types::{Digest32, Generation};
use neuron_chain_recovery::{NeuronSegmentDescriptorV1, recover_neuron_chain_v1, select_neuron_segments_v1};
use serde_json::{Value, json};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
const Q: i64 = 1 << 24;

fn read(path: &Path) -> Result<Value> {
    Ok(serde_json::from_slice(&fs::read(path)?)?)
}

fn digest(value: &Value, field: &str) -> Result<Digest32> {
    Ok(value[field].as_str().ok_or("missing digest")?.parse()?)
}

fn hashes(paths: &[PathBuf]) -> Result<BTreeMap<String, String>> {
    paths.iter().map(|path| Ok((path.display().to_string(), Digest32::of_bytes(&fs::read(path)?).to_string()))).collect()
}

fn refused<T>(checks: &mut Vec<Value>, name: &str, result: Result<T>) -> Result<()> {
    match result {
        Ok(_) => Err(format!("unexpected acceptance: {name}").into()),
        Err(error) => {
            checks.push(json!({"case": name, "status": "rejected", "error": error.to_string()}));
            Ok(())
        }
    }
}

fn main() -> Result<()> {
    let args: Vec<_> = std::env::args_os().collect();
    if args.len() != 4 {
        return Err("usage: chain-recovery-probe packet.json completed-native-run new-output".into());
    }
    let packet_path = Path::new(&args[1]);
    let run = Path::new(&args[2]);
    let output = Path::new(&args[3]);
    fs::create_dir(output)?;
    let packet = read(packet_path)?;
    let result = read(&run.join("result.json"))?;
    let context = read(&run.join("case-0000/context.json"))?;
    let ticks: Vec<Value> = fs::read_to_string(run.join("ticks.jsonl"))?.lines()
        .map(serde_json::from_str).collect::<std::result::Result<_, _>>()?;
    if packet["future_contract"] != "future_correctness" || packet["dynamics_profile"] != "bounded_balanced"
        || result["packet_sha256"] != Digest32::of_bytes(&fs::read(packet_path)?).to_string()
        || result["final_sequence"] != 1600 || result["segment_rollovers"] != 12
        || ticks.len() != 1600 || context != ticks[1599]
    {
        return Err("not the retained frozen future 13-segment artifact".into());
    }
    let pins = &packet["pins"];
    let head = Digest32::of_bytes(format!("{}:{}:{}", pins["weights"].as_str().ok_or("weights")?,
        pins["calibration"].as_str().ok_or("calibration")?, pins["feature_profile"].as_str().ok_or("features")?).as_bytes());
    let config = SparseConfig {
        model_digest: head,
        normalization_digest: Digest32::of_bytes(b"abc4.future-probability-carrier.observed-coordinates-cancel.v1"),
        generation: Generation::new(1)?, width: 33, top_k: 4,
        temporal_decay_q24: Q / 2, inhibition_gain_q24: Q, inhibition: vec![],
        activity_decay_q24: Q / 2, target_activity_q24: 4 * Q / 33,
        threshold_rate_q24: Q / 8, threshold_min_q24: -3 * Q, threshold_max_q24: 3 * Q,
        eligibility_decay_q24: Q / 2,
    };
    let scope = JournalScope { scope_digest: digest(&context, "subject_scope")?, objective_digest: digest(&context, "objective")? };
    let anchor = JournalAnchor { sequence: 1600, checkpoint_digest: digest(&context, "anchor")? };
    let original: Vec<_> = (0..13).map(|index| run.join(format!("case-0000/neuron-{index:04}.journal"))).collect();
    let before = hashes(&original)?;
    let mut segments = Vec::new();
    for (index, source) in original.iter().enumerate() {
        let path = output.join(format!("neuron-{index:04}.journal"));
        fs::copy(source, &path)?;
        segments.push(NeuronSegmentDescriptorV1 { journal_path: path, max_records: 128 });
    }
    let selected = select_neuron_segments_v1(None, None, Some(&segments))?;
    let recovered = recover_neuron_chain_v1(&selected, config.clone(), scope, anchor)?;
    let checkpoint = recovered.current()?.ok_or("missing recovered state")?;
    let expected_eligibility: Vec<i64> = serde_json::from_value(context["eligibility_q24"].clone())?;
    if checkpoint.sequence() != 1600 || checkpoint.digest() != anchor.checkpoint_digest
        || checkpoint.eligibility_q24() != expected_eligibility
    {
        return Err("real chain state or eligibility differs from retained context".into());
    }
    drop(recovered);
    let mut checks = vec![json!({"case": "real_13_segment_exact_anchor_and_eligibility", "status": "passed"})];
    let one = select_neuron_segments_v1(Some(&segments[0].journal_path), Some(128), None)?;
    let root_anchor = JournalAnchor { sequence: 128, checkpoint_digest: digest(&ticks[127], "anchor")? };
    let legacy = recover_neuron_chain_v1(&one, config.clone(), scope, root_anchor)?;
    if legacy.current()?.ok_or("missing root state")?.digest() != root_anchor.checkpoint_digest {
        return Err("single-file compatibility failed".into());
    }
    drop(legacy);
    checks.push(json!({"case": "legacy_single_file", "status": "passed"}));
    refused(&mut checks, "ambiguous_descriptor", select_neuron_segments_v1(Some(&segments[0].journal_path), Some(128), Some(&segments)))?;
    refused(&mut checks, "explicit_empty_chain_with_single", select_neuron_segments_v1(Some(&segments[0].journal_path), Some(128), Some(&[])))?;
    refused(&mut checks, "legacy_capacity_with_chain", select_neuron_segments_v1(None, Some(128), Some(&segments)))?;
    refused(&mut checks, "empty_descriptor", select_neuron_segments_v1(None, None, None))?;
    refused(&mut checks, "empty_chain", recover_neuron_chain_v1(&[], config.clone(), scope, anchor))?;
    for name in ["duplicate_path", "missing_middle_segment", "wrong_order", "missing_file", "wrong_capacity"] {
        let mut changed = segments.clone();
        match name {
            "duplicate_path" => changed[6].journal_path = changed[5].journal_path.clone(),
            "missing_middle_segment" => { changed.remove(6); }
            "wrong_order" => changed.swap(6, 7),
            "missing_file" => changed[6].journal_path = output.join("never-created.journal"),
            "wrong_capacity" => changed[6].max_records = 127,
            _ => return Err("unknown rejection case".into()),
        }
        refused(&mut checks, name, recover_neuron_chain_v1(&changed, config.clone(), scope, anchor))?;
    }
    let mut changed = config.clone(); changed.generation = Generation::new(2)?;
    refused(&mut checks, "wrong_generation", recover_neuron_chain_v1(&segments, changed, scope, anchor))?;
    let wrong_scope = JournalScope { scope_digest: Digest32::of_bytes(b"wrong-scope"), ..scope };
    refused(&mut checks, "wrong_scope", recover_neuron_chain_v1(&segments, config.clone(), wrong_scope, anchor))?;
    let wrong_objective = JournalScope { objective_digest: Digest32::of_bytes(b"wrong-objective"), ..scope };
    refused(&mut checks, "wrong_objective", recover_neuron_chain_v1(&segments, config.clone(), wrong_objective, anchor))?;
    for (name, other_anchor) in [
        ("wrong_final_digest", JournalAnchor { checkpoint_digest: Digest32::of_bytes(b"wrong-anchor"), ..anchor }),
        ("missing_final_record", JournalAnchor { sequence: 1601, ..anchor }),
        ("unacknowledged_final_suffix", JournalAnchor { sequence: 1599, checkpoint_digest: digest(&ticks[1598], "anchor")? }),
    ] {
        refused(&mut checks, name, recover_neuron_chain_v1(&segments, config.clone(), scope, other_anchor))?;
    }
    #[cfg(unix)]
    {
        let mut changed = segments.clone();
        let alias = output.join("same-inode.journal");
        fs::hard_link(&changed[5].journal_path, &alias)?;
        changed[6].journal_path = alias;
        refused(&mut checks, "hardlink_alias", recover_neuron_chain_v1(&changed, config.clone(), scope, anchor))?;
        let alias = output.join("symlink.journal");
        std::os::unix::fs::symlink(&segments[6].journal_path, &alias)?;
        changed = segments.clone(); changed[6].journal_path = alias;
        refused(&mut checks, "symlink_segment", recover_neuron_chain_v1(&changed, config.clone(), scope, anchor))?;
    }
    let empty = output.join("empty.journal"); fs::write(&empty, [])?;
    let mut changed = segments.clone(); changed[6].journal_path = empty.clone();
    refused(&mut checks, "empty_segment_no_bootstrap", recover_neuron_chain_v1(&changed, config, scope, anchor))?;
    if fs::metadata(&empty)?.len() != 0 || hashes(&original)? != before {
        return Err("input history was modified or an empty segment was bootstrapped".into());
    }
    let report = json!({"schema": "hepta.production-handoff.chain-probe.v1", "status": "passed", "checks": checks,
        "source_segment_sha256": before, "source_files_unchanged": true,
        "actual_segments": 13, "actual_sequence": 1600, "actual_anchor": anchor.checkpoint_digest.to_string(),
        "actual_eligibility_matched": true, "new_native_ticks": 0, "new_independent_samples": 0,
        "production_admission": false, "trust_activated": false, "applied_model_update": false,
        "scope": "recovery of copied real artifacts through original pinned journal API; not a deployed daemon"});
    fs::write(output.join("result.json"), serde_json::to_vec_pretty(&report)?)?;
    println!("{report}");
    Ok(())
}
