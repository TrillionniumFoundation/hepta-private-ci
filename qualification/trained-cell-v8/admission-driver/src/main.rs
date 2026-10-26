use codex_hepta_types::Digest32;
use hepta_profile_admission_v8::Result;
use hepta_profile_admission_v8::admission;
use hepta_profile_admission_v8::profile::Profile;
use hepta_profile_admission_v8::report;
use std::fs;
use std::io::Write;
use std::path::Path;

fn main() -> Result<()> {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    let mode = args
        .first()
        .and_then(|v| v.to_str())
        .ok_or("reject, prepare or execute required")?;
    let count = match mode {
        "reject" => 11,
        "prepare" => 13,
        "execute" => 14,
        _ => return Err("unknown admission mode".into()),
    };
    if args.len() != count {
        return Err("MODE PROFILE HOST_PROFILE_SHA PROTOCOL EVALUATION GATE PREDECESSOR_HANDOFF CANDIDATE_HANDOFF CONVERSION_MANIFEST CONTRACTS [REPLAY_AUDIT STATISTICS_AUDIT] OUTPUT [SIGNATURE]".into());
    }
    let pin: Digest32 = args[2]
        .to_str()
        .ok_or("host profile pin must be text")?
        .parse()?;
    let profile = Profile::load(Path::new(&args[1]), pin)?;
    let paths = report::Paths {
        protocol: Path::new(&args[3]),
        evaluation: Path::new(&args[4]),
        gate: Path::new(&args[5]),
        predecessor: Path::new(&args[6]),
        candidate: Path::new(&args[7]),
        conversion: Path::new(&args[8]),
        contracts: Path::new(&args[9]),
    };
    let loaded = report::load(&profile, &paths)?;
    let output = Path::new(&args[if mode == "reject" { 10 } else { 12 }]);
    let mut receipt = if mode == "reject" {
        let result = admission::reject(&loaded)?;
        fs::create_dir(output)?;
        result
    } else {
        admission::positive(
            mode,
            &profile,
            &loaded,
            [
                Path::new(&args[10]),
                Path::new(&args[11]),
                paths.conversion,
                paths
                    .conversion
                    .parent()
                    .ok_or("conversion parent missing")?,
            ],
            output,
            if mode == "execute" {
                Some(Path::new(&args[13]))
            } else {
                None
            },
        )?
    };
    receipt["native_profile_sha256"] = profile.digest().to_string().into();
    receipt["admission_adapter"] = "hepta.host-pinned-native-profile.v1".into();
    let bytes = serde_json::to_vec_pretty(&receipt)?;
    let receipt_path = output.join(format!("{mode}-receipt.json"));
    match fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&receipt_path)
    {
        Ok(mut file) => file.write_all(&bytes)?,
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            if report::read(&receipt_path)? != bytes {
                return Err("existing adapter receipt differs".into());
            }
        }
        Err(error) => return Err(error.into()),
    }
    println!("{}", String::from_utf8(bytes)?);
    Ok(())
}
