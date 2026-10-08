//! Executable qualification lab. No production ingress, selection or model installation.
#[path = "memory_cell_lab/data.rs"]
mod data;
#[path = "memory_cell_lab/model.rs"]
mod model;
#[path = "memory_cell_lab/retrieval.rs"]
mod retrieval;
#[path = "memory_cell_lab/controls.rs"]
mod controls;
#[path = "memory_cell_lab/report.rs"]
mod report;
use std::error::Error;
use std::fs;
use std::path::PathBuf;

fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    let (corpus, output, smoke) = match args.as_slice() {
        [mode, out] if mode == "smoke" => (data::smoke_corpus(), PathBuf::from(out), true),
        [mode, input, out] if mode == "run" => (fs::read_to_string(input)?, PathBuf::from(out), false),
        _ => return Err("usage: memory_cell_lab smoke OUT | run CORPUS.tsv OUT".into()),
    };
    let rows = data::parse(&corpus)?;
    fs::create_dir(&output)?;
    fs::write(output.join("corpus.tsv"), &corpus)?;
    fs::write(output.join("protocol.txt"), concat!(
        "MCELL-LAB-1\nselection=select-only\ntrain-ops-estimate-ceiling=8000000\n",
        "primary-capacity-pair=static_2x4,dynamic_equal_capacity\nencoder=hashed-words-32:v1\n",
        "confidence=Hoeffding-source-root-means-Bonferroni-21\nalpha=0.05\n",
        "snapshot-minimum=3\nfuture-calendar-window-minimum=2\nsource-root-minimum=200\n",
        "relative-old-task-regression-maximum=0.02\ncitation-precision-minimum=0.99\n",
        "deletion-resurrection-maximum=0\nproduction-authority=false\n"))?;
    let mut arms = controls::train_arms(&rows)?;
    for arm in &mut arms {
        if let Some(bundle) = &arm.bundle {
            let path = output.join(format!("{}.bundle", arm.name));
            fs::write(&path, bundle.encode())?;
            // Evaluate an artifact reload, not a live trainer object or its buffers.
            let clean = model::Bundle::decode(&fs::read_to_string(path)?)?;
            if clean != *bundle { return Err("bundle roundtrip mismatch".into()); }
            arm.bundle = Some(clean);
        }
    }
    let text = report::experiment_report(&arms, &rows, corpus.len(), smoke)?;
    fs::write(output.join("report.json"), text)?;
    let actual_bytes: u64 = fs::read_dir(&output)?.map(|e| e.and_then(|e| e.metadata()).map(|m| m.len())).collect::<Result<Vec<_>, _>>()?.iter().sum();
    fs::write(output.join("storage.txt"), format!("retained_regular_file_bytes_before_this_receipt={actual_bytes}\nincludes_corpus_and_all_control_artifacts=true\n"))?;
    println!("qualification_only=true superiority_claim=false");
    Ok(())
}
