//! Executable qualification lab. No production ingress, selection or model installation.
#[path = "memory_cell_lab/build_observations.rs"]
mod build_observations;
#[path = "memory_cell_lab/controls.rs"]
mod controls;
#[path = "memory_cell_lab/data.rs"]
mod data;
#[path = "memory_cell_lab/model.rs"]
mod model;
#[path = "memory_cell_lab/report.rs"]
mod report;
#[path = "memory_cell_lab/retrieval.rs"]
mod retrieval;
#[path = "memory_cell_lab/transfer.rs"]
mod transfer;

use std::error::Error;
use std::fs;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;

fn retained_bytes(dir: &Path) -> std::io::Result<u64> {
    let mut bytes = 0;
    for entry in fs::read_dir(dir)? {
        let entry = entry?;
        let metadata = entry.metadata()?;
        if metadata.is_dir() {
            bytes += retained_bytes(&entry.path())?;
        } else if metadata.is_file() {
            bytes += metadata.len();
        }
    }
    Ok(bytes)
}

fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.first().map(String::as_str) == Some("infer-transfer") {
        return match args.as_slice() {
            [_, input, output] => transfer::infer(Path::new(input), Path::new(output), None)
                .map_err(Into::into),
            [_, input, output, revoked] => transfer::infer(
                Path::new(input),
                Path::new(output),
                Some(Path::new(revoked)),
            )
            .map_err(Into::into),
            _ => Err("usage: infer-transfer INPUT_DIR OUTPUT.tsv [CURRENT_REVOCATIONS]".into()),
        };
    }
    let usage = "usage: memory_cell_lab smoke OUT | run CORPUS.tsv OUT | build-smoke GENERATOR_SHA OUT";
    let output = PathBuf::from(args.last().ok_or(usage)?);
    if !matches!(
        args.first().map(String::as_str),
        Some("smoke" | "run" | "build-smoke")
    ) {
        return Err(usage.into());
    }
    fs::create_dir(&output)?;
    let (corpus, smoke) = match args.as_slice() {
        [mode, _] if mode == "smoke" => (data::smoke_corpus(), true),
        [mode, input, _] if mode == "run" => {
            let mut text = String::new();
            fs::File::open(input)?
                .take(16 * 1024 * 1024 + 1)
                .read_to_string(&mut text)?;
            (text, false)
        }
        [mode, commit, _] if mode == "build-smoke" => {
            (build_observations::generate(&output, commit)?, true)
        }
        _ => return Err(usage.into()),
    };
    let rows = data::parse(&corpus)?;
    fs::write(output.join("corpus.tsv"), &corpus)?;
    fs::write(
        output.join("protocol.txt"),
        concat!(
            "MCELL-LAB-1\nselection=select-only\ntrain-ops-estimate-ceiling=8000000\n",
            "primary-capacity-pair=static_2x4,dynamic_equal_capacity\nencoder=hashed-words-32:v1\n",
            "confidence=Hoeffding-source-root-means-Bonferroni-21\nalpha=0.05\n",
            "snapshot-minimum=3\nfuture-calendar-window-minimum=2\nsource-root-minimum=200\n",
            "relative-old-task-regression-maximum=0.02\ncitation-precision-minimum=0.99\n",
            "deletion-resurrection-maximum=0\nproduction-authority=false\n"
        ),
    )?;
    let mut arms = controls::train_arms(&rows)?;
    for arm in &mut arms {
        if let Some(bundle) = &arm.bundle {
            let path = output.join(format!("{}.bundle", arm.name));
            fs::write(&path, bundle.encode())?;
            let clean = model::Bundle::decode(&fs::read_to_string(path)?)?;
            if clean != *bundle {
                return Err("bundle roundtrip mismatch".into());
            }
            arm.bundle = Some(clean);
        }
    }
    let transfer_bundle = arms
        .iter()
        .find(|arm| arm.name == "dynamic_equal_capacity")
        .and_then(|arm| arm.bundle.as_ref())
        .ok_or("missing transfer bundle")?;
    transfer::export(
        transfer_bundle,
        &rows,
        &output.join("transfer-input"),
        &output.join("transfer-expected.tsv"),
    )?;
    let text = report::experiment_report(&arms, &rows, corpus.len(), smoke)?;
    fs::write(output.join("report.json"), text)?;
    let actual_bytes = retained_bytes(&output)?;
    fs::write(
        output.join("storage.txt"),
        format!("retained_regular_file_bytes_before_this_receipt={actual_bytes}\nincludes_corpus_all_control_artifacts_and_compiler_observations=true\n"),
    )?;
    println!("qualification_only=true superiority_claim=false");
    Ok(())
}
