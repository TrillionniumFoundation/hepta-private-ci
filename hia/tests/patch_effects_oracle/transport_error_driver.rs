//! Observe the public API when its own native planner reports a transport error.
//! Every filesystem operation uses LOCAL_FS in one newly created fixture folder.
use codex_apply_patch::ApplyPatchError;
use codex_apply_patch::Hunk;
use codex_apply_patch::UpdateFileChunk;
use codex_apply_patch::apply_hunks;
use codex_exec_server::LOCAL_FS;
use codex_utils_path_uri::PathUri;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static CALLS: AtomicU64 = AtomicU64::new(0);
static FORWARDED: AtomicU64 = AtomicU64::new(0);
static RETURN_ERROR_ON: AtomicU64 = AtomicU64::new(0);

unsafe extern "C" {
    fn __real_codex_hia_patch_effects(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

#[unsafe(no_mangle)]
unsafe extern "C" fn __wrap_codex_hia_patch_effects(
    source: *const u8,
    source_len: u64,
    output: *mut u8,
    output_capacity: u64,
    workspace: *mut u8,
    workspace_len: u64,
) -> u64 {
    let ordinal = CALLS.fetch_add(1, Ordering::SeqCst) + 1;
    if ordinal == RETURN_ERROR_ON.load(Ordering::SeqCst) {
        // A declared no-write transport result, without changing any buffer.
        return u64::from(u32::MAX);
    }
    FORWARDED.fetch_add(1, Ordering::SeqCst);
    // SAFETY: forward the original live, disjoint buffers without alterations.
    unsafe {
        __real_codex_hia_patch_effects(
            source,
            source_len,
            output,
            output_capacity,
            workspace,
            workspace_len,
        )
    }
}

fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut text = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        text.push(DIGITS[usize::from(byte >> 4)] as char);
        text.push(DIGITS[usize::from(byte & 15)] as char);
    }
    text
}

fn update(move_path: Option<PathBuf>) -> Hunk {
    Hunk::UpdateFile {
        path: PathBuf::from("source.txt"),
        move_path,
        chunks: vec![UpdateFileChunk {
            change_context: None,
            old_lines: vec!["old".into()],
            new_lines: vec!["new".into()],
            context_line_indices: Vec::new(),
            is_end_of_file: false,
        }],
    }
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 4 {
        return Err("fixture path, scenario and error ordinal are required".into());
    }
    let directory = PathBuf::from(&args[1]);
    if !directory.is_absolute() || directory.exists() {
        return Err("a new absolute fixture directory is required".into());
    }
    let fail: u64 = args[3].parse()?;
    if fail > 32 {
        return Err("error ordinal exceeds the fixture bound".into());
    }
    std::fs::create_dir(&directory)?;
    let hunks = match args[2].as_str() {
        "add" => vec![Hunk::AddFile {
            path: "target.txt".into(),
            contents: "new\n".into(),
        }],
        "prefix" => vec![
            Hunk::AddFile {
                path: "first.txt".into(),
                contents: "first\n".into(),
            },
            Hunk::AddFile {
                path: "target.txt".into(),
                contents: "new\n".into(),
            },
        ],
        "delete" => {
            std::fs::write(directory.join("source.txt"), "old\n")?;
            vec![Hunk::DeleteFile {
                path: "source.txt".into(),
            }]
        }
        "inplace" => {
            std::fs::write(directory.join("source.txt"), "old\n")?;
            vec![update(None)]
        }
        "move" => {
            std::fs::write(directory.join("source.txt"), "old\n")?;
            std::fs::write(directory.join("target.txt"), "overwritten\n")?;
            vec![update(Some("target.txt".into()))]
        }
        "update-missing" => vec![update(None)],
        "delete-missing" => vec![Hunk::DeleteFile {
            path: "source.txt".into(),
        }],
        _ => return Err("unknown fixture scenario".into()),
    };
    let cwd = PathUri::from_host_native_path(&directory)?;
    let mut stdout = Vec::new();
    let mut stderr = Vec::new();
    RETURN_ERROR_ON.store(fail, Ordering::SeqCst);
    let outcome = apply_hunks(
        &hunks,
        &cwd,
        &mut stdout,
        &mut stderr,
        LOCAL_FS.as_ref(),
        None,
    )
    .await;
    let delta = match outcome {
        Ok(delta) => {
            println!("status=success");
            delta
        }
        Err(failure) => {
            let (error, delta) = failure.into_parts();
            println!("status=error");
            let kind = match error {
                ApplyPatchError::ParseError(_) => "ParseError",
                ApplyPatchError::IoError(_) => "IoError",
                ApplyPatchError::ComputeReplacements(_) => "ComputeReplacements",
                ApplyPatchError::PathUri(_) => "PathUri",
                ApplyPatchError::ImplicitInvocation => "ImplicitInvocation",
            };
            println!("kind={kind}");
            println!("error_hex={}", hex(error.to_string().as_bytes()));
            delta
        }
    };
    println!("delta_exact={}", delta.is_exact());
    println!("delta_changes={}", delta.changes().len());
    println!("delta_hex={}", hex(format!("{delta:?}").as_bytes()));
    println!("stdout_hex={}", hex(&stdout));
    println!("stderr_hex={}", hex(&stderr));
    println!("planner_call_attempts={}", CALLS.load(Ordering::SeqCst));
    println!("native_forwarded_calls={}", FORWARDED.load(Ordering::SeqCst));
    for name in ["first.txt", "source.txt", "target.txt"] {
        match std::fs::read(directory.join(name)) {
            Ok(bytes) => println!("file_{name}={}", hex(&bytes)),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                println!("file_{name}=absent")
            }
            Err(error) => return Err(error.into()),
        }
    }
    Ok(())
}
