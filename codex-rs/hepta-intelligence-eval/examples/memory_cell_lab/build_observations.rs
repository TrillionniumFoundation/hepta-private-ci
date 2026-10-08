//! Controlled compiler microbenchmark: generated programs, actual observed rustc
//! outcomes, and independently compiled repair candidates. Not production CI history.
use super::data::HEADER;
use std::fs;
use std::path::Path;
use std::process::Command;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

fn compile(dir: &Path, name: &str, source: &str) -> Result<(bool, String), String> {
    let file = dir.join(format!("{name}.rs"));
    fs::write(&file, source).map_err(|e| e.to_string())?;
    let output = Command::new("rustc")
        .args([
            "--edition=2021",
            "--crate-type=lib",
            "--crate-name=memory_lab_case",
            "--emit=metadata",
        ])
        .arg(&file)
        .arg("-o")
        .arg(dir.join("output.rmeta"))
        .output()
        .map_err(|e| e.to_string())?;
    let stderr = String::from_utf8(output.stderr).map_err(|_| "non-UTF8 compiler output")?;
    fs::write(dir.join(format!("{name}.stderr")), &stderr).map_err(|e| e.to_string())?;
    fs::write(
        dir.join(format!("{name}.status")),
        format!(
            "exit_code={:?}\nsuccess={}\n",
            output.status.code(),
            output.status.success()
        ),
    )
    .map_err(|e| e.to_string())?;
    Ok((output.status.success(), stderr))
}

pub fn generate(output: &Path, generator_commit: &str) -> Result<String, String> {
    if generator_commit.len() != 40 || !generator_commit.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err("build-smoke requires exact generator commit SHA".into());
    }
    let version = Command::new("rustc")
        .arg("--version")
        .arg("--verbose")
        .output()
        .map_err(|e| e.to_string())?;
    if !version.status.success() {
        return Err("compiler unavailable".into());
    }
    let version = String::from_utf8(version.stdout).map_err(|_| "compiler identity encoding")?;
    let environment = version.split_whitespace().collect::<Vec<_>>().join(" ");
    fs::write(output.join("compiler.txt"), &version).map_err(|e| e.to_string())?;
    let root = output.join("build-observations");
    fs::create_dir(&root).map_err(|e| e.to_string())?;
    let mut corpus = format!("{HEADER}\n");
    let repairs = [
        "replace-unbound-name",
        "correct-return-literal",
        "clone-before-consuming",
        "declare-mutable-binding",
    ];
    for (window, split) in ["train", "select", "future-a", "future-b", "retention"]
        .iter()
        .enumerate()
    {
        // Ensure genuinely nonoverlapping *recorded* second-resolution collection
        // ranges, not invented timestamps. These are NOT future calendar windows.
        if window > 0 {
            std::thread::sleep(Duration::from_millis(1100));
        }
        for i in 0..16 {
            let class = i % 4;
            let domain = (i / 4) % 2;
            let n = 1000 + window * 100 + i;
            let code = match class {
                0 => format!(
                    "pub fn value() -> u32 {{ let context = {n}; let _ = context; missing_value }}"
                ),
                1 => format!(
                    "pub fn value() -> u32 {{ let context = {n}; let _ = context; \"oops\" }}"
                ),
                2 => format!("pub fn value() {{ let v = vec![{n}]; drop(v); let _ = v.len(); }}"),
                3 => format!("pub fn value() {{ let v = {n}; v += 1; let _ = v; }}"),
                _ => unreachable!(),
            };
            let case = format!("case-{window}-{i}");
            let dir = root.join(&case);
            fs::create_dir(&dir).map_err(|e| e.to_string())?;
            let (base_passed, stderr) = compile(&dir, "original", &code)?;
            if base_passed {
                return Err("microbenchmark original unexpectedly compiled".into());
            }
            let mut successful = Vec::new();
            let mut ordered = Vec::new();
            for slot in 0..4 {
                let repair = (slot + domain) % 4;
                ordered.push(repairs[repair]);
                let fixed = match repair {
                    0 => code.replace("missing_value", "7"),
                    1 => code.replace("\"oops\"", "7"),
                    2 => code.replace("drop(v)", "drop(v.clone())"),
                    3 => code.replace("let v =", "let mut v ="),
                    _ => unreachable!(),
                };
                if compile(&dir, &format!("candidate-{slot}"), &fixed)?.0 {
                    successful.push(slot);
                }
            }
            if successful.len() != 1 {
                return Err("repair outcome ambiguous or unavailable".into());
            }
            let time = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_err(|e| e.to_string())?
                .as_secs();
            let diagnostic = stderr.replace(&dir.to_string_lossy().to_string(), "<source>");
            let query = format!(
                "{code} {diagnostic} ordered repair candidates {}",
                ordered.join(" ")
            )
            .split_whitespace()
            .collect::<Vec<_>>()
            .join(" ");
            if query.len() > 8192 {
                return Err("compiler observation exceeds query limit".into());
            }
            corpus.push_str(&format!("{case}\t{case}\t{split}\t{time}\tlab-public\t{generator_commit}\t{environment}\tbuild-observations/{case}/original.stderr\t{domain}\t{class}\t{}\t{query}\n", successful[0]));
        }
    }
    fs::write(
        output.join("build-provenance.txt"),
        concat!(
            "source_kind=controlled-generated-programs-with-observed-compiler-results\n",
            "commit_field=generator-source-commit-not-a-production-project-commit\n",
            "cases=80\ncompiler_invocations=400\nrepairs_scored_by_actual_compilation=true\n",
            "production_history=false\nfuture_calendar_qualification=false\n"
        ),
    )
    .map_err(|e| e.to_string())?;
    Ok(corpus)
}
