//! Self-contained Linux FP64 research inference/streaming executable.
mod codec;
mod math;
mod model;
mod state;
mod stream;
use codec::{Packet, Result, immutable_write, sha256};
use model::Model;
use std::path::Path;

fn summary(s: &stream::Session) -> Result<String> {
    let mut cursors = Vec::new();
    for m in model::MODALITIES {
        cursors.push(format!(
            "\"{m}\":{}",
            s.record.text(&format!("cursor.{m}"))?
        ));
    }
    Ok(format!(
        "{{\"head\":\"{}\",\"sequence\":{},\"steps\":{},\"stopped\":{},\"operation\":\"{}\",\"argument\":\"{}\",\"cursors\":{{{}}}}}",
        s.head,
        s.sequence,
        s.state.steps,
        s.state.stopped,
        s.record.text("operation")?,
        s.record.text("argument")?,
        cursors.join(",")
    ))
}
fn run() -> Result<String> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() == 3 && args[1] == "hash" {
        return Ok(sha256(&std::fs::read(&args[2]).map_err(|e| e.to_string())?));
    }
    if args.len() < 5 {
        return Err("usage: native COMMAND WEIGHTS PUBLIC SESSION [arguments]".into());
    }
    let wp = Path::new(&args[2]);
    let ip = Path::new(&args[3]);
    let dir = Path::new(&args[4]);
    let weights = Packet::read(wp)?;
    let public = Packet::read(ip)?;
    let wh = sha256(&weights.encode()?);
    let ih = sha256(&public.encode()?);
    let model = Model::new(weights)?;
    model.validate_input(&public)?;
    match args[1].as_str() {
        "init" if args.len() == 7 => {
            let seed = args[5].parse::<u64>().map_err(|e| e.to_string())?;
            summary(&stream::create(
                dir, &model, &public, &wh, &ih, seed, &args[6],
            )?)
        }
        "status" if args.len() == 5 || args.len() == 6 => {
            let session = stream::load(dir, &model, &public, &wh, &ih)?;
            if args
                .get(5)
                .is_some_and(|expected| *expected != session.head)
            {
                return Err("independent head witness mismatch".into());
            }
            summary(&session)
        }
        "inspect" if args.len() == 7 => {
            let s = stream::load(dir, &model, &public, &wh, &ih)?;
            let remaining = args[6].parse::<f64>().map_err(|e| e.to_string())?;
            let mut p = model.inspect(&s.state, remaining)?;
            p.meta.insert("journal_head".into(), s.head.clone());
            p.meta.insert("weights".into(), wh);
            p.meta.insert("input".into(), ih);
            for m in model::MODALITIES {
                p.meta.insert(
                    format!("cursor.{m}"),
                    s.record.text(&format!("cursor.{m}"))?.into(),
                );
                p.vector(
                    &format!("prefix.{m}"),
                    s.record.get(&format!("prefix.{m}"))?.to_vec(),
                );
            }
            immutable_write(Path::new(&args[5]), &p.encode()?)?;
            summary(&s)
        }
        "step" if args.len() == 7 => summary(&stream::mutate(
            dir, &model, &public, &wh, &ih, &args[5], "step", &args[6], 0, "",
        )?),
        "auto" if args.len() == 7 => {
            let s = stream::load(dir, &model, &public, &wh, &ih)?;
            let remaining = args[6].parse::<f64>().map_err(|e| e.to_string())?;
            let inspection = model.inspect(&s.state, remaining)?;
            let law = inspection.get("policy.probabilities")?;
            let max = law.iter().copied().fold(f64::NEG_INFINITY, f64::max);
            let action = model::ACTIONS[law.iter().position(|v| *v == max).unwrap()];
            summary(&stream::mutate(
                dir, &model, &public, &wh, &ih, &args[5], "step", action, 0, "",
            )?)
        }
        "commit" if args.len() == 8 || args.len() == 9 => {
            let count = args[7].parse::<usize>().map_err(|e| e.to_string())?;
            let fault = args.get(8).map_or("", String::as_str);
            if !["", "after_chunk", "after_event"].contains(&fault) {
                return Err("unknown fault point".into());
            }
            summary(&stream::mutate(
                dir, &model, &public, &wh, &ih, &args[5], "commit", &args[6], count, fault,
            )?)
        }
        "export" if args.len() == 8 => {
            let s = stream::load(dir, &model, &public, &wh, &ih)?;
            let rate = args[6].parse::<u32>().map_err(|e| e.to_string())?;
            let frame = args[7].parse::<u16>().map_err(|e| e.to_string())?;
            stream::export(dir, &s, Path::new(&args[5]), rate, frame)
        }
        _ => Err("unknown command or argument count".into()),
    }
}
fn main() {
    match run() {
        Ok(value) => println!("{value}"),
        Err(error) => {
            eprintln!("native_generation: {error}");
            std::process::exit(2);
        }
    }
}
