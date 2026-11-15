//! Natural, owned filesystem inputs; no filesystem result substitution.
use crate::DriverResult;
use std::path::Path;

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

pub fn prepare_fixture(root: &Path, name: &str) -> DriverResult<String> {
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
        "invalid_hunk" => patch("*** Add File: input.txt\nnot prefixed"),
        "invalid_after_valid_hunk" => {
            patch("*** Add File: prefix.txt\n+not committed\n*** Add File: input.txt\nnot prefixed")
        }
        "invalid_unicode" => patch("*** Update File: 文档.txt\n@@\n?错误😀"),
        "unchanged_update" => {
            std::fs::write(input, b"before\n")?;
            update("input.txt", None, "before", "before")
        }
        "mismatched_update" => {
            std::fs::write(input, b"actual\n")?;
            update("input.txt", None, "missing", "after")
        }
        "prefix_then_mismatch" => {
            std::fs::write(input, b"actual\n")?;
            patch("*** Add File: prefix.txt\n+committed\n*** Update File: input.txt\n@@\n-missing\n+after")
        }
        "unicode_add" => patch("*** Add File: 文档😀.txt\n+é\n+e\u{301}\n+NUL:\0:tail"),
        "unicode_move" => {
            std::fs::write(root.join("文档.txt"), "甲\r\n乙😀\r\n")?;
            update("文档.txt", Some("目标😀.txt"), "乙😀", "丙é")
        }
        "mixed_line_endings" => {
            std::fs::write(input, b"one\r\ntwo\rthree\nfour")?;
            update("input.txt", None, "three", "THREE")
        }
        "nul_path" => patch("*** Add File: bad\0name.txt\n+after"),
        "prefix_then_nul_path" => {
            patch("*** Add File: prefix.txt\n+committed\n*** Add File: bad\0name.txt\n+after")
        }
        "heredoc_unicode" => "\u{2003}<<'PATCH'\n*** Begin Patch\n*** Add File: 文档.txt\n+内容😀\n*** End Patch\nPATCH\u{2003}".to_string(),
        "large_content" => patch(&format!("*** Add File: input.txt\n+{}", "甲😀\0".repeat(16 * 1024))),
        "manual_nonutf8_path" | "manual_embedded_lines" | "manual_empty" => String::new(),
        _ => return Err("unknown fixed fixture".into()),
    };
    Ok(selected)
}

/// Typed inputs exercise apply_hunks without deriving the input from a parser.
pub fn direct_hunks(name: &str, patch_text: &str) -> DriverResult<Vec<codex_apply_patch::Hunk>> {
    use codex_apply_patch::Hunk;
    use std::ffi::OsString;
    use std::os::unix::ffi::OsStringExt;
    use std::path::PathBuf;

    match name {
        "manual_nonutf8_path" => Ok(vec![
            Hunk::AddFile {
                path: PathBuf::from("prefix.txt"),
                contents: "committed\n".to_string(),
            },
            Hunk::AddFile {
                path: PathBuf::from(OsString::from_vec(b"nonutf8-\xff.txt".to_vec())),
                contents: "after\n".to_string(),
            },
        ]),
        "manual_embedded_lines" => Ok(vec![Hunk::AddFile {
            path: PathBuf::from("typed.txt"),
            contents: "one\r\ntwo\rthree\n\0😀".to_string(),
        }]),
        "manual_empty" => Ok(Vec::new()),
        _ => Ok(codex_apply_patch::parse_patch(patch_text)?.hunks),
    }
}
