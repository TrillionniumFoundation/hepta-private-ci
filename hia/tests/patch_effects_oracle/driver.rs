//! Public API observer for complete original/candidate codex_apply_patch crates.
//! No production algorithm, replacement result, or filesystem error is supplied
//! by this driver. All fixture paths and patches belong to a fixed local corpus.
mod observed_fs;

use codex_apply_patch::AppliedPatchDelta;
use codex_apply_patch::AppliedPatchFileChange;
use codex_apply_patch::ApplyPatchError;
use codex_apply_patch::ApplyPatchFileUpdateMode;
use codex_apply_patch::ApplyPatchOptions;
use codex_apply_patch::apply_patch_with_options;
use codex_exec_server::FileSystemSandboxContext;
use codex_exec_server::LOCAL_FS;
use codex_utils_path_uri::PathUri;
use observed_fs::ObservedFs;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;

type DriverResult<T> = Result<T, Box<dyn std::error::Error>>;

const CASE_NAMES: &[&str] = &[
    "add_new",
    "add_overwrite",
    "add_nested",
    "add_invalid_utf8",
    "add_directory",
    "add_symlink",
    "delete_existing",
    "delete_missing",
    "delete_directory",
    "delete_invalid_utf8",
    "delete_symlink",
    "update_existing",
    "update_crlf",
    "update_missing",
    "update_directory",
    "update_invalid_utf8",
    "update_symlink",
    "move_new",
    "move_overwrite",
    "move_nested",
    "move_target_directory",
    "move_same_path",
    "move_dot_alias",
    "move_source_symlink",
    "move_destination_symlink",
    "prefix_then_delete_missing",
    "prefix_then_update_missing",
    "mixed_success",
    "empty_patch",
    "invalid_patch",
];

struct Input<'a> {
    remaining: &'a [u8],
}

impl<'a> Input<'a> {
    fn take(&mut self, length: usize) -> Result<&'a [u8], String> {
        if length > self.remaining.len() {
            return Err("truncated observer request".to_string());
        }
        let (head, tail) = self.remaining.split_at(length);
        self.remaining = tail;
        Ok(head)
    }

    fn number(&mut self) -> Result<usize, String> {
        let bytes: [u8; 8] = self.take(8)?.try_into().map_err(|_| "word width")?;
        usize::try_from(u64::from_le_bytes(bytes)).map_err(|_| "usize overflow".to_string())
    }

    fn string(&mut self) -> Result<String, String> {
        let length = self.number()?;
        String::from_utf8(self.take(length)?.to_vec()).map_err(|error| error.to_string())
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

fn patch(body: &str) -> String {
    format!("*** Begin Patch\n{body}\n*** End Patch")
}

fn update(path: &str, destination: Option<&str>, before: &str, after: &str) -> String {
    let moved = destination.map_or_else(String::new, |path| format!("*** Move to: {path}\n"));
    patch(&format!(
        "*** Update File: {path}\n{moved}@@\n-{before}\n+{after}",
    ))
}

#[cfg(unix)]
fn fixture_symlink(target: &str, path: &Path) -> DriverResult<()> {
    std::os::unix::fs::symlink(target, path)?;
    Ok(())
}

#[cfg(not(unix))]
fn fixture_symlink(_target: &str, _path: &Path) -> DriverResult<()> {
    Err("the fixed symlink fixture requires a Unix host".into())
}

fn prepare_fixture(root: &Path, name: &str) -> DriverResult<String> {
    let input = root.join("input.txt");
    let destination = root.join("destination.txt");
    let selected = match name {
        "add_new" => patch("*** Add File: input.txt\n+after"),
        "add_overwrite" => {
            std::fs::write(input, b"before\n")?;
            patch("*** Add File: input.txt\n+after")
        }
        "add_nested" => patch("*** Add File: new/parents/input.txt\n+after"),
        "add_invalid_utf8" => {
            std::fs::write(input, [0xff, 0xfe, 0xfd])?;
            patch("*** Add File: input.txt\n+after")
        }
        "add_directory" => {
            std::fs::create_dir(input)?;
            patch("*** Add File: input.txt\n+after")
        }
        "add_symlink" => {
            std::fs::write(root.join("target.txt"), b"before\n")?;
            fixture_symlink("target.txt", &root.join("link.txt"))?;
            patch("*** Add File: link.txt\n+after")
        }
        "delete_existing" => {
            std::fs::write(input, b"before\n")?;
            patch("*** Delete File: input.txt")
        }
        "delete_missing" => patch("*** Delete File: input.txt"),
        "delete_directory" => {
            std::fs::create_dir(&input)?;
            std::fs::write(input.join("child.txt"), b"child\n")?;
            patch("*** Delete File: input.txt")
        }
        "delete_invalid_utf8" => {
            std::fs::write(input, [0xff, 0xfe, 0xfd])?;
            patch("*** Delete File: input.txt")
        }
        "delete_symlink" => {
            std::fs::write(root.join("target.txt"), b"target\n")?;
            fixture_symlink("target.txt", &root.join("link.txt"))?;
            patch("*** Delete File: link.txt")
        }
        "update_existing" => {
            std::fs::write(input, b"before\n")?;
            update("input.txt", None, "before", "after")
        }
        "update_crlf" => {
            std::fs::write(input, b"one\r\ntwo\r\n")?;
            update("input.txt", None, "two", "TWO")
        }
        "update_missing" => update("input.txt", None, "before", "after"),
        "update_directory" => {
            std::fs::create_dir(&input)?;
            std::fs::write(input.join("child.txt"), b"child\n")?;
            update("input.txt", None, "before", "after")
        }
        "update_invalid_utf8" => {
            std::fs::write(input, [0xff, 0xfe, 0xfd])?;
            update("input.txt", None, "before", "after")
        }
        "update_symlink" => {
            std::fs::write(root.join("target.txt"), b"before\n")?;
            fixture_symlink("target.txt", &root.join("link.txt"))?;
            update("link.txt", None, "before", "after")
        }
        "move_new" => {
            std::fs::write(input, b"before\n")?;
            update("input.txt", Some("destination.txt"), "before", "after")
        }
        "move_overwrite" => {
            std::fs::write(input, b"before\n")?;
            std::fs::write(destination, b"previous destination\n")?;
            update("input.txt", Some("destination.txt"), "before", "after")
        }
        "move_nested" => {
            std::fs::write(input, b"before\n")?;
            update(
                "input.txt",
                Some("new/parents/destination.txt"),
                "before",
                "after",
            )
        }
        "move_target_directory" => {
            std::fs::write(input, b"before\n")?;
            std::fs::create_dir(&destination)?;
            std::fs::write(destination.join("child.txt"), b"child\n")?;
            update("input.txt", Some("destination.txt"), "before", "after")
        }
        "move_same_path" => {
            std::fs::write(input, b"before\n")?;
            update("input.txt", Some("input.txt"), "before", "after")
        }
        "move_dot_alias" => {
            std::fs::write(input, b"before\n")?;
            std::fs::create_dir(root.join("alias"))?;
            update("input.txt", Some("alias/../input.txt"), "before", "after")
        }
        "move_source_symlink" => {
            std::fs::write(root.join("target.txt"), b"before\n")?;
            fixture_symlink("target.txt", &root.join("link.txt"))?;
            update("link.txt", Some("destination.txt"), "before", "after")
        }
        "move_destination_symlink" => {
            std::fs::write(input, b"before\n")?;
            std::fs::write(root.join("target.txt"), b"previous destination\n")?;
            fixture_symlink("target.txt", &root.join("link.txt"))?;
            update("input.txt", Some("link.txt"), "before", "after")
        }
        "prefix_then_delete_missing" => {
            patch("*** Add File: prefix.txt\n+committed\n*** Delete File: missing.txt")
        }
        "prefix_then_update_missing" => patch(
            "*** Add File: prefix.txt\n+committed\n*** Update File: missing.txt\n@@\n-before\n+after",
        ),
        "mixed_success" => {
            std::fs::write(root.join("delete.txt"), b"delete me\n")?;
            std::fs::write(input, b"before\n")?;
            patch(
                "*** Add File: added.txt\n+new\n*** Delete File: delete.txt\n*** Update File: input.txt\n@@\n-before\n+after",
            )
        }
        "empty_patch" => "*** Begin Patch\n*** End Patch".to_string(),
        "invalid_patch" => "not a patch\n".to_string(),
        _ => return Err("unknown fixed fixture".into()),
    };
    Ok(selected)
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

fn emit_optional_text(label: &str, text: Option<&str>) {
    println!("{label}_present={}", text.is_some());
    if let Some(text) = text {
        println!("{label}_hex={}", hex(text.as_bytes()));
    }
}

fn emit_delta(delta: &AppliedPatchDelta) {
    println!("delta_exact={}", delta.is_exact());
    println!("delta_changes={}", delta.changes().len());
    println!("delta_debug_hex={}", hex(format!("{delta:?}").as_bytes()));
    for (index, change) in delta.changes().iter().enumerate() {
        let prefix = format!("delta_{index}");
        println!(
            "{prefix}_path_debug_hex={}",
            hex(format!("{:?}", change.path).as_bytes())
        );
        println!(
            "{prefix}_path_native_hex={}",
            hex(change.path.inferred_native_path_string().as_bytes()),
        );
        match &change.change {
            AppliedPatchFileChange::Add {
                content,
                overwritten_content,
            } => {
                println!("{prefix}_kind=Add");
                println!("{prefix}_content_hex={}", hex(content.as_bytes()));
                emit_optional_text(
                    &format!("{prefix}_overwritten"),
                    overwritten_content.as_deref(),
                );
            }
            AppliedPatchFileChange::Delete { content } => {
                println!("{prefix}_kind=Delete");
                println!("{prefix}_content_hex={}", hex(content.as_bytes()));
            }
            AppliedPatchFileChange::Update {
                move_path,
                old_content,
                overwritten_move_content,
                new_content,
            } => {
                println!("{prefix}_kind=Update");
                println!("{prefix}_move_present={}", move_path.is_some());
                if let Some(path) = move_path {
                    println!(
                        "{prefix}_move_debug_hex={}",
                        hex(format!("{path:?}").as_bytes())
                    );
                    println!(
                        "{prefix}_move_native_hex={}",
                        hex(path.inferred_native_path_string().as_bytes())
                    );
                }
                println!("{prefix}_old_hex={}", hex(old_content.as_bytes()));
                println!("{prefix}_new_hex={}", hex(new_content.as_bytes()));
                emit_optional_text(
                    &format!("{prefix}_overwritten_move"),
                    overwritten_move_content.as_deref(),
                );
            }
        }
    }
}

fn snapshot(root: &Path) -> DriverResult<Vec<String>> {
    fn visit(root: &Path, path: &Path, entries: &mut Vec<String>) -> DriverResult<()> {
        let relative = path.strip_prefix(root)?;
        let relative_hex = hex(relative.as_os_str().as_encoded_bytes());
        let metadata = match std::fs::symlink_metadata(path) {
            Ok(metadata) => metadata,
            Err(error) => {
                entries.push(format!(
                    "path_hex={relative_hex};kind=metadata_error;error_kind={:?};display_hex={};debug_hex={}",
                    error.kind(), hex(error.to_string().as_bytes()),
                    hex(format!("{error:?}").as_bytes()),
                ));
                return Ok(());
            }
        };
        let kind = metadata.file_type();
        if kind.is_symlink() {
            // Record the link itself; do not traverse or read its target here.
            let target = std::fs::read_link(path)?;
            entries.push(format!(
                "path_hex={relative_hex};kind=symlink;target_hex={}",
                hex(target.as_os_str().as_encoded_bytes()),
            ));
        } else if kind.is_dir() {
            entries.push(format!("path_hex={relative_hex};kind=directory"));
            let mut children = std::fs::read_dir(path)?
                .map(|entry| entry.map(|entry| entry.path()))
                .collect::<Result<Vec<_>, _>>()?;
            children.sort();
            for child in children {
                visit(root, &child, entries)?;
            }
        } else if kind.is_file() {
            match std::fs::read(path) {
                Ok(bytes) => entries.push(format!(
                    "path_hex={relative_hex};kind=file;contents_hex={}", hex(&bytes),
                )),
                Err(error) => entries.push(format!(
                    "path_hex={relative_hex};kind=file;read_error_kind={:?};display_hex={};debug_hex={}",
                    error.kind(), hex(error.to_string().as_bytes()),
                    hex(format!("{error:?}").as_bytes()),
                )),
            }
        } else {
            entries.push(format!("path_hex={relative_hex};kind=other"));
        }
        Ok(())
    }
    let mut entries = Vec::new();
    visit(root, root, &mut entries)?;
    Ok(entries)
}

fn emit_snapshot(label: &str, entries: &[String]) {
    println!("{label}_entries={}", entries.len());
    for (index, entry) in entries.iter().enumerate() {
        println!("{label}_{index}_hex={}", hex(entry.as_bytes()));
    }
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> DriverResult<()> {
    let mut request = Vec::new();
    std::io::stdin().read_to_end(&mut request)?;
    let mut input = Input {
        remaining: &request,
    };
    if input.take(8)? != b"HFXO0001" {
        return Err("wrong observer protocol".into());
    }
    let mode = match input.number()? {
        0 => ApplyPatchFileUpdateMode::NormalizeToLf,
        1 => ApplyPatchFileUpdateMode::PreserveLineEndings,
        _ => return Err("unknown update mode".into()),
    };
    let follow_symlinks = match input.number()? {
        0 => false,
        1 => true,
        _ => return Err("unknown follow_symlinks flag".into()),
    };
    let name = input.string()?;
    let context_json = input.string()?;
    if !input.remaining.is_empty() {
        return Err("trailing observer request bytes".into());
    }
    if !CASE_NAMES.contains(&name.as_str()) {
        return Err("unknown fixed fixture".into());
    }
    if name.contains("symlink") && !cfg!(unix) {
        return Err("symlink case requires Unix; it is not a passed or skipped case".into());
    }
    let context: Option<FileSystemSandboxContext> = if context_json.is_empty() {
        None
    } else {
        Some(serde_json::from_str(&context_json)?)
    };
    let mut arguments = std::env::args_os().skip(1);
    let directory = arguments
        .next()
        .map(PathBuf::from)
        .ok_or("one fresh absolute fixture directory is required")?;
    if arguments.next().is_some() || !directory.is_absolute() {
        return Err("exactly one absolute fixture directory is required".into());
    }
    // Exclusive creation refuses an existing fixture tree. No parent tree is
    // created, no external path or arbitrary patch is accepted, and no cleanup
    // runs in this process so the caller can inspect the final filesystem.
    std::fs::create_dir(&directory)?;
    let patch = prepare_fixture(&directory, &name)?;
    let before = snapshot(&directory)?;
    let cwd = PathUri::from_host_native_path(&directory)?;
    let options = ApplyPatchOptions {
        update_file_mode: mode,
        follow_symlinks,
    };
    let sandbox = context.as_ref();
    let filesystem = ObservedFs::new(LOCAL_FS.as_ref(), sandbox);
    let mut stdout = Vec::new();
    let mut stderr = Vec::new();

    println!("protocol=HFXO0001");
    println!("request_hex={}", hex(&request));
    println!("case_name_hex={}", hex(name.as_bytes()));
    println!(
        "fixture_root_hex={}",
        hex(directory.as_os_str().as_encoded_bytes())
    );
    println!("cwd_debug_hex={}", hex(format!("{cwd:?}").as_bytes()));
    println!("patch_hex={}", hex(patch.as_bytes()));
    println!(
        "options_debug_hex={}",
        hex(format!("{options:?}").as_bytes())
    );
    println!("sandbox_present={}", sandbox.is_some());
    println!("sandbox_json_hex={}", hex(context_json.as_bytes()));
    println!(
        "sandbox_debug_hex={}",
        hex(format!("{sandbox:?}").as_bytes())
    );
    println!("stdout_writer=Vec<u8>");
    println!("stderr_writer=Vec<u8>");
    println!("writer_errors_injected=false");
    emit_snapshot("before", &before);

    let outcome = apply_patch_with_options(
        &patch,
        options,
        &cwd,
        &mut stdout,
        &mut stderr,
        &filesystem,
        sandbox,
    )
    .await;
    match outcome {
        Ok(delta) => {
            println!("status=success");
            emit_delta(&delta);
        }
        Err(failure) => {
            println!(
                "failure_debug_hex={}",
                hex(format!("{failure:?}").as_bytes())
            );
            let (error, delta) = failure.into_parts();
            emit_error(&error);
            emit_delta(&delta);
        }
    }
    println!("stdout_hex={}", hex(&stdout));
    println!("stderr_hex={}", hex(&stderr));
    let events = filesystem.transcript();
    println!("fs_events={}", events.len());
    for (index, event) in events.iter().enumerate() {
        println!("fs_event_{index}_hex={}", hex(event.as_bytes()));
    }
    emit_snapshot("after", &snapshot(&directory)?);
    println!("observation_complete=true");
    Ok(())
}
