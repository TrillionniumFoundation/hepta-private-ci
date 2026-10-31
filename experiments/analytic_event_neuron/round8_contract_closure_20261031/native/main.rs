//! Linux CPU research owner; actions are consumed by the unchanged R7 broker.
mod kernels;
mod model;
mod owner;
mod port;
use std::io::BufRead;
use std::io::Write;
use std::path::Path;
use std::time::Instant;

fn run() -> Result<(), String> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 7 {
        return Err("usage: native MODEL OWNER SEED HEAD DEPLOYMENT ACK".into());
    }
    let start = Instant::now();
    let bytes = owner::read(Path::new(&args[1]), /*limit*/ 2_000_000)?;
    let loaded = model::Model::load(&bytes)?;
    let identity = model::Identity {
        model_sha256: loaded.digest.clone(),
        kernel_version: model::KERNEL_VERSION.into(),
        seed: args[3].parse::<u64>().map_err(|e| e.to_string())?,
        head: args[4].parse::<usize>().map_err(|e| e.to_string())?,
        deployment: args[5].clone(),
    };
    let model_load_nanos = model::nanos(start);
    let start = Instant::now();
    let mut owner = owner::Owner::open(loaded, identity, Path::new(&args[2]), &args[6])?;
    println!(
        "{}",
        serde_json::json!({"ok":true,"ready":true,"pair":owner.pair,"pair_after":owner.pair_digest,
        "model_load_nanos":model_load_nanos,"recovery_nanos":model::nanos(start),"pid":std::process::id(),
        "source_digest":env!("HEPTA_TASK_NATIVE_SOURCE_DIGEST"),"authority":"DENY_ALL","production_activation":false})
    );
    std::io::stdout().flush().map_err(|e| e.to_string())?;
    let mut reader = std::io::stdin().lock();
    loop {
        let mut bytes = Vec::new();
        let size = std::io::Read::take(&mut reader, 32769)
            .read_until(b'\n', &mut bytes)
            .map_err(|e| e.to_string())?;
        if size == 0 {
            break;
        }
        if size > 32768 || bytes.last() != Some(&b'\n') {
            return Err("request length/framing".into());
        }
        let result = serde_json::from_slice::<model::Request>(&bytes)
            .map_err(|e| e.to_string())
            .and_then(|r| owner.step(r));
        let output = match result {
            Ok(receipt) => serde_json::json!({"ok":true,"receipt":receipt}),
            Err(error) => serde_json::json!({"ok":false,"error":error}),
        };
        println!("{output}");
        std::io::stdout().flush().map_err(|e| e.to_string())?;
    }
    Ok(())
}
fn main() {
    if let Err(error) = run() {
        println!("{}", serde_json::json!({"ok":false,"error":error}));
        std::process::exit(1);
    }
}

#[cfg(test)]
#[path = "native_tests.rs"]
mod tests;
