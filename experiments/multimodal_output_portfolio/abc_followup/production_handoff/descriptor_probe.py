"""Check exact patched serde declarations without replacing Agentd owner types."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


CASES = r'''
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

fn selected(value: serde_json::Value) -> Result<Vec<NeuronSegmentDescriptorV1>> {
    // These declarations are copied byte-for-byte from the actual target patch.
    let parsed: NeuronDescriptorV1 = serde_json::from_value(value)?;
    if parsed.config.width != 33 || parsed.config.top_k != 4 || parsed.anchor_sequence != 1600 {
        return Err("descriptor payload was not preserved".into());
    }
    select_neuron_segments_v1(parsed.journal_path.as_deref(), parsed.max_records,
                              parsed.segment_chain.as_deref())
}

fn main() -> Result<()> {
    let output = std::env::args_os().nth(1).ok_or("missing new output")?;
    let mut common = serde_json::json!({
        "owner_id":"descriptor-parser-only", "scope_digest":"not-authority",
        "objective_digest":"not-authority", "anchor_sequence":1600,
        "anchor_checkpoint_digest":"not-authority",
        "config":{"model_digest":"not-authority", "normalization_digest":"not-authority",
            "generation":1,"width":33,"top_k":4,"temporal_decay_q24":8388608,
            "inhibition_gain_q24":16777216,"inhibition":[],"activity_decay_q24":8388608,
            "target_activity_q24":2033601,"threshold_rate_q24":2097152,
            "threshold_min_q24":-50331648,"threshold_max_q24":50331648,
            "eligibility_decay_q24":8388608}
    });
    let mut single = common.clone();
    single["journal_path"] = serde_json::json!("/descriptor-only/root.journal");
    single["max_records"] = serde_json::json!(128);
    let mut chain = common.clone();
    chain["segment_chain"] = serde_json::json!([
        {"journal_path":"/descriptor-only/root.journal","max_records":128},
        {"journal_path":"/descriptor-only/next.journal","max_records":128}
    ]);
    let mut checks = Vec::new();
    for (name,value,expected) in [("legacy_single_json",single.clone(),1),
                                  ("new_chain_json",chain.clone(),2)] {
        let roundtrip: serde_json::Value = serde_json::from_str(&serde_json::to_string(&value)?)?;
        let a = selected(value)?; let b = selected(roundtrip)?;
        let shape = |x: Vec<NeuronSegmentDescriptorV1>| x.into_iter()
            .map(|s|(s.journal_path,s.max_records)).collect::<Vec<_>>();
        if a.len()!=expected || shape(a)!=shape(b) {return Err("JSON roundtrip differs".into());}
        checks.push(serde_json::json!({"case":name,"status":"passed"}));
    }
    let mut nullable = chain.clone(); nullable["journal_path"] = serde_json::Value::Null;
    nullable["max_records"] = serde_json::Value::Null;
    if selected(nullable)?.len()!=2 {return Err("null option semantics changed".into());}
    checks.push(serde_json::json!({"case":"null_legacy_fields_are_none","status":"passed"}));
    let mut nullable = single.clone(); nullable["segment_chain"] = serde_json::Value::Null;
    if selected(nullable)?.len()!=1 {return Err("null chain semantics changed".into());}
    checks.push(serde_json::json!({"case":"null_chain_is_none","status":"passed"}));
    for name in ["both_sources","single_plus_empty_chain","empty_chain","missing_single_capacity",
                 "capacity_without_path","unknown_neuron_field","unknown_segment_field",
                 "negative_segment_capacity","wrong_chain_type","missing_required_owner",
                 "unknown_config_field"] {
        let mut value = match name {
            "both_sources"|"single_plus_empty_chain"|"missing_single_capacity" => single.clone(),
            "capacity_without_path" => common.clone(),
            _ => chain.clone(),
        };
        match name {
            "both_sources" => value["segment_chain"] = chain["segment_chain"].clone(),
            "single_plus_empty_chain"|"empty_chain" => value["segment_chain"] = serde_json::json!([]),
            "missing_single_capacity" => {value.as_object_mut().ok_or("object")?.remove("max_records");},
            "capacity_without_path" => value["max_records"] = serde_json::json!(128),
            "unknown_neuron_field" => value["unexpected"] = serde_json::json!(1),
            "unknown_segment_field" => value["segment_chain"][0]["unexpected"] = serde_json::json!(1),
            "negative_segment_capacity" => value["segment_chain"][0]["max_records"] = serde_json::json!(-1),
            "wrong_chain_type" => value["segment_chain"] = serde_json::json!({"path":"wrong"}),
            "missing_required_owner" => {value.as_object_mut().ok_or("object")?.remove("owner_id");},
            "unknown_config_field" => value["config"]["unexpected"] = serde_json::json!(1),
            _ => return Err("unknown case".into()),
        }
        let error = selected(value).err().ok_or("unexpected JSON acceptance")?;
        checks.push(serde_json::json!({"case":name,"status":"rejected","error":error.to_string()}));
    }
    // The strings above deliberately cannot be a valid signed owner bundle.
    // No file opening, runtime/error replacement, trust or owner API is called.
    common.as_object_mut().ok_or("object")?.clear();
    let result = serde_json::json!({"schema":"hepta.production-handoff.descriptor-serde.v1",
        "checks":checks,"status":"passed","original_loader_called":false,
        "runtime_or_error_stub_used":false,"owner_authority_claim":false,
        "journal_files_opened":false,"new_independent_samples":0,
        "scope":"exact patched serde declaration and real source-selection helper only; no Agentd loader/body/runtime composition qualification"});
    let file = std::fs::OpenOptions::new().write(true).create_new(true).open(output)?;
    serde_json::to_writer_pretty(&file,&result)?; file.sync_all()?;
    println!("{result}"); Ok(())
}
'''


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args):
    area = Path(__file__).resolve().parent
    declaration = args.patched_source.read_text()
    receipt = json.loads((area / "CHAIN_RECOVERY_VALIDATION.json").read_text())
    if sha(args.patched_source) != receipt["patched_bootstrap_sha256"]:
        raise ValueError("Descriptor source is not the exact validated target patch")
    if sha(area / "neuron_chain_recovery.rs") != receipt["build"]["sources"]["neuron_chain_recovery.rs"]:
        raise ValueError("Chain helper differs from the actual validated source")
    start = declaration.index("#[derive(Debug, Deserialize)]\n#[serde(deny_unknown_fields)]\nstruct InhibitoryEdgeDescriptorV1 {")
    end = declaration.index("#[derive(Debug, Deserialize)]\n#[serde(deny_unknown_fields)]\nstruct SignalBindingDescriptorV1 {", start)
    snippet = declaration[start:end]
    args.output.mkdir(parents=True, exist_ok=False)
    if hasattr(os, "sched_getaffinity"):
        os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    source = args.output / "descriptor-serde-probe.rs"
    source.write_text("use std::path::PathBuf;\nuse serde::Deserialize;\n"
        + '#[path = "' + str(area / "neuron_chain_recovery.rs") + '"]\nmod neuron_chain_recovery;\n'
        + "use neuron_chain_recovery::{NeuronSegmentDescriptorV1,select_neuron_segments_v1};\n"
        + snippet + CASES)
    binary = args.output / "codex-descriptor-serde-probe"
    command = [str(args.rustc), "--edition=2024", "-C", "opt-level=1", "-C", "debuginfo=0",
               str(source), "-L", "dependency=" + str(args.dependencies), "-o", str(binary)]
    libraries = {}
    for name in ("codex_hepta_neuron", "serde", "serde_json"):
        found = list(args.dependencies.glob("lib" + name + "-*.rlib"))
        if len(found) != 1:
            raise ValueError("Expected one known native dependency: " + name)
        libraries[name] = {"path": str(found[0]), "sha256": sha(found[0])}
        command.extend(("--extern", name + "=" + str(found[0])))
    before = time.monotonic_ns()
    with (args.output / "build.log").open("xb") as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    with (args.output / "probe.log").open("xb") as log:
        subprocess.run([str(binary), str(args.output / "result.json")], stdout=log, stderr=subprocess.STDOUT, check=True)
    result = json.loads((args.output / "result.json").read_text())
    result["build"] = {"runner_sha256": sha(Path(__file__)), "patched_bootstrap_sha256": sha(args.patched_source),
        "exact_descriptor_snippet_sha256": hashlib.sha256(snippet.encode()).hexdigest(),
        "generated_probe_sha256": sha(source), "helper_sha256": sha(area / "neuron_chain_recovery.rs"),
        "binary_sha256": sha(binary), "rlibs": libraries, "wall_ns": time.monotonic_ns() - before,
        "rustc_sha256": sha(args.rustc), "single_cpu_affinity": sorted(os.sched_getaffinity(0))}
    (args.output / "validation.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "checks": len(result["checks"])}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("rustc", "dependencies", "patched-source", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    run(parser.parse_args())
