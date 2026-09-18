use hepta_native::update::run_update_request;
use std::path::PathBuf;

fn main() {
    if let Err(error) = run() {
        eprintln!("hepta-native-updater: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args_os().skip(1);
    if args.next().as_deref() != Some(std::ffi::OsStr::new("--request")) {
        return Err("usage: hepta-native-updater --request PATH".into());
    }
    let request = args
        .next()
        .map(PathBuf::from)
        .ok_or("missing request path")?;
    if args.next().is_some() {
        return Err("unexpected updater arguments".into());
    }
    let result = run_update_request(&request)?;
    println!("{}", serde_json::to_string(&result)?);
    Ok(())
}
