//! Executable qualification lab. No production ingress, selection or model installation.
#[path = "memory_cell_lab/data.rs"]
mod data;
#[path = "memory_cell_lab/model.rs"]
mod model;
#[path = "memory_cell_lab/retrieval.rs"]
mod retrieval;
#[path = "memory_cell_lab/controls.rs"]
mod controls;
use std::error::Error;
use std::fs;
use std::path::PathBuf;

fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    let (corpus, output) = match args.as_slice() {
        [mode, out] if mode == "smoke" => (data::smoke_corpus(), PathBuf::from(out)),
        [mode, input, out] if mode == "run" => (fs::read_to_string(input)?, PathBuf::from(out)),
        _ => return Err("usage: memory_cell_lab smoke OUT | run CORPUS.tsv OUT".into()),
    };
    let rows = data::parse(&corpus)?;
    fs::create_dir(&output)?;
    fs::write(output.join("corpus.tsv"), &corpus)?;
    fs::write(output.join("protocol.txt"), "MCELL-LAB-1\nselection=select-only\ntrain-ops-estimate-ceiling=8000000\nprimary-capacity-pair=static_2x4,dynamic_equal_capacity\nencoder=hashed-words-32:v1\nproduction-authority=false\n")?;
    for arm in controls::train_arms(&rows)? {
        if let Some(bundle) = &arm.bundle {
            let bytes = bundle.encode();
            let clean = model::Bundle::decode(&bytes)?;
            if clean != *bundle { return Err("bundle roundtrip mismatch".into()); }
            fs::write(output.join(format!("{}.bundle", arm.name)), bytes)?;
        }
        for split in [data::Split::FutureA, data::Split::FutureB, data::Split::Retention] {
            let future: Vec<_> = rows.iter().filter(|r| r.split == split).collect();
            let mut correct = 0;
            let mut read_ops = 0;
            let mut refs = 0;
            let mut scans = 0;
            for row in &future {
                let result = controls::predict(&arm, &rows, &row.query)?;
                let p = result.probabilities;
                correct += usize::from([model::argmax(&p[0]), model::argmax(&p[1])] == row.targets);
                read_ops += result.ops_estimate;
                refs += result.evidence.len();
                scans += result.scanned;
            }
            println!("arm={} split={split:?} correct={correct}/{} train_ops_estimate={} train_us={} read_ops_estimate={read_ops} evidence_refs={refs} scanned={scans} decisions={:?}", arm.name, future.len(), arm.meter.train_ops, arm.training_micros, arm.decisions);
        }
    }
    println!("qualification_only=true superiority_claim=false");
    Ok(())
}
