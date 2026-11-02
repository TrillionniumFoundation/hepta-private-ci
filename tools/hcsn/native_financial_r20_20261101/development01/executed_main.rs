//! Inspect the native finite financial model; stdout contains no expected states.
mod financial;

fn execute() -> financial::Result<()> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() == 3 && args[1] == "cdf" {
        println!("{:.17e}", financial::normal_cdf(args[2].parse()?)?);
        return Ok(());
    }
    if args.len() != 4 {
        return Err("usage: financial SIGMA LIQUIDITY MATURITY".into());
    }
    let model = financial::construct(args[1].parse()?, args[2].parse()?, args[3].parse()?)?;
    let values: Vec<f64> = std::iter::once(model.boundary)
        .chain(model.q.iter().flatten().copied())
        .chain(model.read.iter().flatten().copied())
        .chain(model.refresh.iter().flatten().copied())
        .chain(model.prior)
        .collect();
    println!(
        "[{}]",
        values
            .iter()
            .map(|x| format!("{x:.17e}"))
            .collect::<Vec<_>>()
            .join(",")
    );
    Ok(())
}

fn main() {
    if let Err(error) = execute() {
        eprintln!("{error}");
        std::process::exit(2);
    }
}
