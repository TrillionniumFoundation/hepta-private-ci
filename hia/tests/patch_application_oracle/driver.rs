//! Three real public APIs from the complete original/actual Cargo owner crate.
mod fixtures;
mod native_trace;
#[path = "../patch_effects_oracle/observed_fs.rs"]
mod observed_fs;
mod values;
mod writers;

use codex_apply_patch::ApplyPatchFileUpdateMode;
use codex_apply_patch::ApplyPatchOptions;
use codex_exec_server::FileSystemSandboxContext;
use codex_exec_server::LOCAL_FS;
use codex_utils_path_uri::PathUri;
use observed_fs::ObservedFs;
use std::cell::RefCell;
use std::io::Read;
use std::path::PathBuf;
use std::rc::Rc;
use writers::Policy;
use writers::Trace;
use writers::Writer;

type DriverResult<T> = Result<T, Box<dyn std::error::Error>>;

struct Input<'a> {
    remaining: &'a [u8],
}

impl<'a> Input<'a> {
    fn take(&mut self, length: usize) -> Result<&'a [u8], String> {
        if length > self.remaining.len() {
            return Err("truncated application observer request".to_string());
        }
        let (head, tail) = self.remaining.split_at(length);
        self.remaining = tail;
        Ok(head)
    }

    fn number(&mut self) -> Result<usize, String> {
        let word: [u8; 8] = self.take(8)?.try_into().map_err(|_| "word width")?;
        usize::try_from(u64::from_le_bytes(word)).map_err(|_| "usize overflow".to_string())
    }

    fn string(&mut self) -> Result<String, String> {
        let length = self.number()?;
        String::from_utf8(self.take(length)?.to_vec()).map_err(|error| error.to_string())
    }

    fn policy(&mut self) -> Result<Policy, String> {
        Policy {
            style: self.number()?,
            mode: self.number()?,
            point: self.number()?,
            fragment: self.number()?,
        }
        .validate()
    }
}

fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::new();
    for byte in bytes {
        output.push(char::from(DIGITS[usize::from(byte >> 4)]));
        output.push(char::from(DIGITS[usize::from(byte & 15)]));
    }
    output
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> DriverResult<()> {
    let mut request = Vec::new();
    std::io::stdin().read_to_end(&mut request)?;
    let mut input = Input {
        remaining: &request,
    };
    if input.take(8)? != b"HPAO0001" {
        return Err("wrong application observer protocol".into());
    }
    let entry = input.number()?;
    let mode = input.number()?;
    let follow = input.number()?;
    let out_policy = input.policy()?;
    let err_policy = input.policy()?;
    let name = input.string()?;
    let sandbox_json = input.string()?;
    if !input.remaining.is_empty()
        || entry > 2
        || mode > 1
        || follow > 1
        || (entry != 0 && (mode != 0 || follow != 1))
    {
        return Err("invalid public entry/options or trailing request bytes".into());
    }
    if name.starts_with("manual_") && entry != 2 {
        return Err("typed-only fixture requires apply_hunks".into());
    }
    let args = std::env::args_os().skip(1).collect::<Vec<_>>();
    if args.len() != 1 {
        return Err("exactly one owned fresh fixture directory is required".into());
    }
    let directory = PathBuf::from(&args[0]);
    if !directory.is_absolute() || directory.exists() {
        return Err("fixture directory must be absolute and absent".into());
    }
    std::fs::create_dir(&directory)?;
    let patch_text = fixtures::prepare_fixture(&directory, &name)?;
    let before = values::snapshot(&directory)?;
    let cwd = PathUri::from_host_native_path(&directory)?;
    let options = ApplyPatchOptions {
        update_file_mode: match mode {
            0 => ApplyPatchFileUpdateMode::NormalizeToLf,
            1 => ApplyPatchFileUpdateMode::PreserveLineEndings,
            _ => unreachable!("validated update mode"),
        },
        follow_symlinks: follow == 1,
    };
    let sandbox_value: Option<FileSystemSandboxContext> = if sandbox_json.is_empty() {
        None
    } else {
        Some(serde_json::from_str(&sandbox_json)?)
    };
    let sandbox = sandbox_value.as_ref();
    let filesystem = ObservedFs::new(LOCAL_FS.as_ref(), sandbox);
    let completed_fs_events = || filesystem.transcript().len();
    let events = Rc::new(RefCell::new(Vec::new()));
    let mut stdout = Trace::new(
        "stdout",
        out_policy,
        Rc::clone(&events),
        &completed_fs_events,
    );
    let mut stderr = Trace::new(
        "stderr",
        err_policy,
        Rc::clone(&events),
        &completed_fs_events,
    );
    let hunks = if entry == 2 {
        Some(fixtures::direct_hunks(&name, &patch_text)?)
    } else {
        None
    };

    println!("protocol=HPAO0001");
    println!("request_hex={}", hex(&request));
    println!("entry={entry}");
    println!("case_name_hex={}", hex(name.as_bytes()));
    println!(
        "fixture_root_hex={}",
        hex(directory.as_os_str().as_encoded_bytes())
    );
    println!("cwd_debug_hex={}", hex(format!("{cwd:?}").as_bytes()));
    println!("patch_hex={}", hex(patch_text.as_bytes()));
    println!(
        "direct_hunks_debug_hex={}",
        hex(format!("{hunks:?}").as_bytes())
    );
    println!(
        "options_debug_hex={}",
        hex(format!("{options:?}").as_bytes())
    );
    println!("sandbox_present={}", sandbox.is_some());
    println!("sandbox_json_hex={}", hex(sandbox_json.as_bytes()));
    println!(
        "sandbox_debug_hex={}",
        hex(format!("{sandbox:?}").as_bytes())
    );
    println!("filesystem_result_substitution=false");
    println!(
        "stdout_policy_debug_hex={}",
        hex(format!("{out_policy:?}").as_bytes())
    );
    println!(
        "stderr_policy_debug_hex={}",
        hex(format!("{err_policy:?}").as_bytes())
    );
    values::emit_snapshot("before", &before);
    let result = {
        let mut out = Writer(&mut stdout);
        let mut err = Writer(&mut stderr);
        match entry {
            0 => {
                codex_apply_patch::apply_patch_with_options(
                    &patch_text,
                    options,
                    &cwd,
                    &mut out,
                    &mut err,
                    &filesystem,
                    sandbox,
                )
                .await
            }
            1 => {
                codex_apply_patch::apply_patch(
                    &patch_text,
                    &cwd,
                    &mut out,
                    &mut err,
                    &filesystem,
                    sandbox,
                )
                .await
            }
            2 => {
                codex_apply_patch::apply_hunks(
                    hunks
                        .as_deref()
                        .unwrap_or_else(|| panic!("typed fixture missing")),
                    &cwd,
                    &mut out,
                    &mut err,
                    &filesystem,
                    sandbox,
                )
                .await
            }
            _ => unreachable!("validated public entry"),
        }
    };
    match result {
        Ok(delta) => {
            println!("status=success");
            values::emit_delta(&delta);
        }
        Err(failure) => {
            println!(
                "failure_debug_hex={}",
                hex(format!("{failure:?}").as_bytes())
            );
            let (error, delta) = failure.into_parts();
            values::emit_error(&error);
            values::emit_delta(&delta);
        }
    }
    for (name, trace) in [("stdout", &stdout), ("stderr", &stderr)] {
        println!("{name}_hex={}", hex(&trace.bytes));
        println!("{name}_writes={}", trace.writes);
        println!("{name}_formats={}", trace.formats);
        println!("{name}_flushes={}", trace.flushes);
    }
    let trace = events.borrow();
    println!("writer_events={}", trace.len());
    for (index, event) in trace.iter().enumerate() {
        println!("writer_event_{index}_hex={}", hex(event.as_bytes()));
    }
    let actual_fs = filesystem.transcript();
    println!("fs_events={}", actual_fs.len());
    for (index, event) in actual_fs.iter().enumerate() {
        println!("fs_event_{index}_hex={}", hex(event.as_bytes()));
    }
    values::emit_snapshot("after", &values::snapshot(&directory)?);
    native_trace::emit();
    println!("observation_complete=true");
    Ok(())
}
