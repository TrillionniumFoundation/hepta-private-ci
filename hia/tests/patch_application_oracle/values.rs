//! Public values and actual filesystem snapshots; no normalization.
use crate::hex;
use crate::DriverResult;
use codex_apply_patch::AppliedPatchDelta;
use codex_apply_patch::AppliedPatchFileChange;
use codex_apply_patch::ApplyPatchError;
use std::path::Path;

pub fn emit_error(error: &ApplyPatchError) {
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
    let mut chain: Option<&(dyn std::error::Error + 'static)> = Some(error);
    let mut count = 0;
    while let Some(current) = chain {
        println!(
            "error_chain_{count}_display_hex={}",
            hex(current.to_string().as_bytes())
        );
        println!(
            "error_chain_{count}_debug_hex={}",
            hex(format!("{current:?}").as_bytes())
        );
        if let Some(io) = current.downcast_ref::<std::io::Error>() {
            println!("error_chain_{count}_io_kind={:?}", io.kind());
            println!("error_chain_{count}_raw_os_error={:?}", io.raw_os_error());
            println!(
                "error_chain_{count}_inner_present={}",
                io.get_ref().is_some()
            );
        }
        chain = current.source();
        count += 1;
        assert!(count < 64, "unexpected cyclic public error chain");
    }
    println!("error_chain_count={count}");
}

fn emit_optional_text(label: &str, text: Option<&str>) {
    println!("{label}_present={}", text.is_some());
    if let Some(text) = text {
        println!("{label}_hex={}", hex(text.as_bytes()));
    }
}

pub fn emit_delta(delta: &AppliedPatchDelta) {
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

pub fn snapshot(root: &Path) -> DriverResult<Vec<String>> {
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

pub fn emit_snapshot(label: &str, entries: &[String]) {
    println!("{label}_entries={}", entries.len());
    for (index, entry) in entries.iter().enumerate() {
        println!("{label}_{index}_hex={}", hex(entry.as_bytes()));
    }
}
