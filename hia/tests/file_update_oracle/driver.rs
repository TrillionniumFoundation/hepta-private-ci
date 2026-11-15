//! Transport-only public API driver. All update algorithms and types come from
//! the complete original or actual feature-selected production crate.
use codex_apply_patch::AppliedPatchDelta;
use codex_apply_patch::ApplyPatchArgs;
use codex_apply_patch::ApplyPatchError;
use codex_apply_patch::ApplyPatchFileChange;
use codex_apply_patch::ApplyPatchFileUpdateMode;
use codex_apply_patch::ApplyPatchOptions;
use codex_apply_patch::Hunk;
use codex_apply_patch::MaybeApplyPatchVerified;
use codex_apply_patch::UpdateFileChunk;
use codex_apply_patch::apply_hunks;
use codex_apply_patch::apply_patch_with_options;
use codex_apply_patch::verify_apply_patch_args_with_mode;
use codex_exec_server::LOCAL_FS;
use codex_utils_path_uri::PathUri;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;

struct Input<'a> {
    remaining: &'a [u8],
}
impl<'a> Input<'a> {
    fn take(&mut self, length: usize) -> Result<&'a [u8], String> {
        if length > self.remaining.len() {
            return Err("truncated harness request".into());
        }
        let (head, tail) = self.remaining.split_at(length);
        self.remaining = tail;
        Ok(head)
    }
    fn number(&mut self) -> Result<usize, String> {
        let bytes: [u8; 8] = self.take(8)?.try_into().map_err(|_| "word width")?;
        usize::try_from(u64::from_le_bytes(bytes)).map_err(|_| "usize overflow".into())
    }
    fn bytes(&mut self) -> Result<Vec<u8>, String> {
        let length = self.number()?;
        Ok(self.take(length)?.to_vec())
    }
    fn string(&mut self) -> Result<String, String> {
        String::from_utf8(self.bytes()?).map_err(|error| error.to_string())
    }
    fn strings(&mut self) -> Result<Vec<String>, String> {
        let count = self.number()?;
        if count > self.remaining.len() / 8 {
            return Err("impossible string count".into());
        }
        (0..count).map(|_| self.string()).collect()
    }
}
fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut value = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        value.push(DIGITS[usize::from(byte >> 4)] as char);
        value.push(DIGITS[usize::from(byte & 15)] as char);
    }
    value
}
fn emit_error(error: &ApplyPatchError) {
    let kind = match error {
        ApplyPatchError::ParseError(_) => "ParseError",
        ApplyPatchError::IoError(_) => "IoError",
        ApplyPatchError::ComputeReplacements(_) => "ComputeReplacements",
        ApplyPatchError::PathUri(_) => "PathUri",
        ApplyPatchError::ImplicitInvocation => "ImplicitInvocation",
    };
    println!("status=error");
    println!("kind={kind}");
    println!("display_hex={}", hex(error.to_string().as_bytes()));
    println!("debug_hex={}", hex(format!("{error:?}").as_bytes()));
}
fn emit_delta(delta: &AppliedPatchDelta) {
    println!("delta_exact={}", delta.is_exact());
    println!("delta_changes={}", delta.changes().len());
    println!("delta_debug_hex={}", hex(format!("{delta:?}").as_bytes()));
}
fn emit_file_state(path: &Path) {
    println!("file_exists={}", path.exists());
    println!("file_is_directory={}", path.is_dir());
    match std::fs::read(path) {
        Ok(bytes) => println!("file_after_hex={}", hex(&bytes)),
        Err(error) => println!("file_read_error_kind={:?}", error.kind()),
    }
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut bytes = Vec::new();
    std::io::stdin().read_to_end(&mut bytes)?;
    let mut input = Input { remaining: &bytes };
    if input.take(8)? != b"HUPD0001" {
        return Err("wrong harness protocol".into());
    }
    let mode = match input.number()? {
        0 => ApplyPatchFileUpdateMode::NormalizeToLf,
        1 => ApplyPatchFileUpdateMode::PreserveLineEndings,
        _ => return Err("unknown harness mode".into()),
    };
    let route = input.number()?;
    let file_kind = input.number()?;
    let original_bytes = input.bytes()?;
    let chunk_count = input.number()?;
    if chunk_count > input.remaining.len() / 40 {
        return Err("impossible chunk count".into());
    }
    let mut chunks = Vec::with_capacity(chunk_count);
    for _ in 0..chunk_count {
        let change_context = match input.number()? {
            0 => None,
            1 => Some(input.string()?),
            _ => return Err("unknown context tag".into()),
        };
        let old_lines = input.strings()?;
        let new_lines = input.strings()?;
        let context_count = input.number()?;
        if context_count > input.remaining.len() / 16 {
            return Err("impossible context count".into());
        }
        let mut context_line_indices = Vec::with_capacity(context_count);
        for _ in 0..context_count {
            context_line_indices.push((input.number()?, input.number()?));
        }
        let is_end_of_file = match input.number()? {
            0 => false,
            1 => true,
            _ => return Err("unknown EOF tag".into()),
        };
        chunks.push(UpdateFileChunk {
            change_context,
            old_lines,
            new_lines,
            context_line_indices,
            is_end_of_file,
        });
    }
    let patch = input.string()?;
    if !input.remaining.is_empty() {
        return Err("trailing harness bytes".into());
    }
    let directory = std::env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .ok_or("a fresh absolute fixture directory is required")?;
    if !directory.is_absolute() {
        return Err("fixture directory must be absolute".into());
    }
    std::fs::create_dir(&directory)?;
    let path = directory.join("input.txt");
    match file_kind {
        0 => std::fs::write(&path, &original_bytes)?,
        1 => {}
        2 => std::fs::create_dir(&path)?,
        _ => return Err("unknown file setup tag".into()),
    }
    let cwd = PathUri::from_host_native_path(&directory)?;
    let file_uri = PathUri::from_host_native_path(&path)?;
    println!("protocol=HUPD0001");
    println!(
        "path_hex={}",
        hex(file_uri.inferred_native_path_string().as_bytes())
    );
    println!(
        "cwd_hex={}",
        hex(cwd.inferred_native_path_string().as_bytes())
    );
    println!(
        "cwd_debug_hex={}",
        hex(format!("{:?}", cwd.inferred_native_path_string()).as_bytes())
    );
    println!("file_before_hex={}", hex(&original_bytes));
    let hunks = vec![Hunk::UpdateFile {
        path: PathBuf::from("input.txt"),
        move_path: None,
        chunks,
    }];
    match route {
        0 => {
            let args = ApplyPatchArgs {
                patch,
                hunks,
                workdir: None,
                environment_id: None,
            };
            match verify_apply_patch_args_with_mode(
                args,
                &cwd,
                mode,
                LOCAL_FS.as_ref(),
                /*sandbox*/ None,
            )
            .await
            {
                MaybeApplyPatchVerified::Body(action) => {
                    if action.changes().len() != 1 {
                        return Err("unexpected public action count".into());
                    }
                    let Some(ApplyPatchFileChange::Update {
                        unified_diff,
                        move_path: None,
                        new_content,
                    }) = action.changes().get(&file_uri)
                    else {
                        return Err("unexpected public action kind".into());
                    };
                    println!("status=success");
                    println!("content_hex={}", hex(new_content.as_bytes()));
                    println!("diff_hex={}", hex(unified_diff.as_bytes()));
                }
                MaybeApplyPatchVerified::CorrectnessError(error) => emit_error(&error),
                other => return Err(format!("unexpected verifier result: {other:?}").into()),
            }
        }
        1 | 2 => {
            let mut stdout = Vec::new();
            let mut stderr = Vec::new();
            let outcome = if route == 1 {
                if mode != ApplyPatchFileUpdateMode::NormalizeToLf {
                    return Err("the real public apply_hunks API uses default mode".into());
                }
                apply_hunks(
                    &hunks,
                    &cwd,
                    &mut stdout,
                    &mut stderr,
                    LOCAL_FS.as_ref(),
                    /*sandbox*/ None,
                )
                .await
            } else {
                apply_patch_with_options(
                    &patch,
                    ApplyPatchOptions {
                        update_file_mode: mode,
                        follow_symlinks: true,
                    },
                    &cwd,
                    &mut stdout,
                    &mut stderr,
                    LOCAL_FS.as_ref(),
                    /*sandbox*/ None,
                )
                .await
            };
            match outcome {
                Ok(delta) => {
                    println!("status=success");
                    emit_delta(&delta);
                }
                Err(failure) => {
                    let (error, delta) = failure.into_parts();
                    emit_error(&error);
                    emit_delta(&delta);
                }
            }
            println!("stdout_hex={}", hex(&stdout));
            println!("stderr_hex={}", hex(&stderr));
        }
        _ => return Err("unknown harness route".into()),
    }
    emit_file_state(&path);
    Ok(())
}
