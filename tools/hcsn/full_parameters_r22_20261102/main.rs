//! Batch process protocol: nine whitespace-delimited parameters per input line.
mod dual;
mod financial;
use std::io::{self, Read, Write};

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let values_only = match args.as_slice() {
        [] => false,
        [mode] if mode == "--values" => true,
        _ => return Err("expected optional --values".into()),
    };
    let mut input = String::new();
    io::stdin().take(1_048_577).read_to_string(&mut input)?;
    if input.len() > 1_048_576 {
        return Err("input capacity exceeded".into());
    }
    let mut models = Vec::new();
    for line in input.lines() {
        let words: Vec<&str> = line.split_whitespace().collect();
        if words.len() != 9 || models.len() >= 128 {
            return Err("expected 1..128 lines of nine parameters".into());
        }
        let mut theta = [0.0; 9];
        for (value, word) in theta.iter_mut().zip(words) {
            *value = word.parse()?;
        }
        models.push(financial::construct(theta)?);
    }
    if models.is_empty() {
        return Err("empty batch".into());
    }
    let mut output = io::BufWriter::new(io::stdout().lock());
    for model in models {
        write!(output,"{{\"lower\":{},\"reset\":{:.17e},\"values\":[", model.lower, model.reset )?;
        for (index, word) in model.words.iter().enumerate() {
            if index != 0 { write!(output,"," )?; }
            write!(output,"{:.17e}", word.v )?;
        }
        write!(output,"]" )?;
        if !values_only {
            write!(output,",\"jacobian\":[" )?;
            for coordinate in 0..9 {
                if coordinate != 0 { write!(output,"," )?; }
                write!(output,"[" )?;
                for (index, word) in model.words.iter().enumerate() {
                    if index != 0 { write!(output,"," )?; }
                    write!(output,"{:.17e}", word.g[coordinate] )?;
                }
                write!(output,"]" )?;
            }
            write!(output,"]" )?;
        }
        writeln!(output,"}}" )?;
    }
    output.flush()?;
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(2);
    }
}
