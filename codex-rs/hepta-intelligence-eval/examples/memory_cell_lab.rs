//! Executable qualification lab. No production ingress, selection or model installation.
#[path = "memory_cell_lab/data.rs"]
mod data;
#[path = "memory_cell_lab/model.rs"]
mod model;
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
    let mut bundle = model::Bundle::new(rows[0].query.scope.clone(), &[8])?;
    let mut meter = model::Meter::default();
    bundle.train(&rows, &mut meter, 8_000_000)?;
    fs::write(output.join("shared.bundle"), bundle.encode())?;
    let clean = model::Bundle::decode(&fs::read_to_string(output.join("shared.bundle"))?)?;
    let future: Vec<_> = rows.iter().filter(|r| r.split == data::Split::FutureA).collect();
    let mut correct = 0;
    for row in &future {
        let p = clean.infer(&row.query)?;
        correct += usize::from([model::argmax(&p[0]), model::argmax(&p[1])] == row.targets);
    }
    println!("qualification_only=true future_a={correct}/{} train_updates={} train_ops_estimate={}", future.len(), meter.updates, meter.train_ops);
    Ok(())
}
