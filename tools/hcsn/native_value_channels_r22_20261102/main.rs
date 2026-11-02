//! Linux FP64 scalar value-channel process, one ten-coordinate row per line.
mod channels;
mod dual;
use std::io::{self, Read, Write};

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let values_only = match args.as_slice() {
        [] => false,
        [mode] if mode == "--values" => true,
        _ => return Err("expected optional --values".into()),
    };
    let mut text = String::new();
    io::stdin().take(1_048_577).read_to_string(&mut text)?;
    if text.len() > 1_048_576 { return Err("input capacity".into()); }
    let mut outputs = Vec::new();
    for line in text.lines() {
        let words: Vec<&str> = line.split_whitespace().collect();
        if words.len() != 10 || outputs.len() >= 128 { return Err("row capacity or arity".into()); }
        let mut values = [0.0; 10];
        for (value, word) in values.iter_mut().zip(words) { *value = word.parse()?; }
        outputs.push(channels::evaluate(values)?);
    }
    if outputs.is_empty() { return Err("empty batch".into()); }
    let mut stream = io::BufWriter::new(io::stdout().lock());
    for outputs in outputs {
        write!(stream, "{{\"values\":[")?;
        for (index, output) in outputs.iter().enumerate() {
            if index != 0 { write!(stream, ",")?; }
            write!(stream, "{:.17e}", output.v)?;
        }
        write!(stream, "]")?;
        if !values_only {
            write!(stream, ",\"jacobian\":[")?;
            for (index, output) in outputs.iter().enumerate() {
                if index != 0 { write!(stream, ",")?; }
                write!(stream, "[")?;
                for (coordinate, tangent) in output.g.iter().enumerate() {
                    if coordinate != 0 { write!(stream, ",")?; }
                    write!(stream, "{tangent:.17e}")?;
                }
                write!(stream, "]")?;
            }
            write!(stream, "]")?;
        }
        writeln!(stream, "}}")?;
    }
    stream.flush()?;
    Ok(())
}

fn main() {
    if let Err(error) = run() { eprintln!("{error}"); std::process::exit(2); }
}
