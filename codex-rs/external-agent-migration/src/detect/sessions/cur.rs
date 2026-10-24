use super::common::SessionFileCandidate;
use super::common::detect_recent_sessions;
use crate::model::ExternalAgentSessionImportLimits;
use crate::sessions::ExternalAgentSessionMigration;
use crate::sessions::SessionRecordFormat;
use std::fs;
use std::io;
use std::path::Path;
use std::path::PathBuf;

const MAX_CUR_PROJECT_PATH_PROBES: usize = 128;
const MAX_CUR_DIRECTORY_NAMES: usize = 512;
const MAX_CUR_TOTAL_DIRECTORY_NAMES: usize = 2048;
const CUR_PROJECT_SEPARATORS: [&str; 11] =
    ["-", "_", ".", " ", "--", "..", "__", "  ", "+", "@", "&"];

pub fn detect_recent_cur_sessions(
    external_agent_home: &Path,
    codex_home: &Path,
) -> io::Result<Vec<ExternalAgentSessionMigration>> {
    detect_recent_cur_sessions_with_limits(
        external_agent_home,
        codex_home,
        ExternalAgentSessionImportLimits::default(),
    )
}

pub(crate) fn detect_recent_cur_sessions_with_limits(
    external_agent_home: &Path,
    codex_home: &Path,
    limits: ExternalAgentSessionImportLimits,
) -> io::Result<Vec<ExternalAgentSessionMigration>> {
    let projects_root = external_agent_home.join("projects");
    if !projects_root.is_dir() {
        return Ok(Vec::new());
    }

    let mut candidates = Vec::new();
    for project_entry in fs::read_dir(projects_root)? {
        let Ok(project_entry) = project_entry else {
            continue;
        };
        let project_storage = project_entry.path();
        if !project_storage.is_dir() {
            continue;
        }
        let fallback_cwd = cur_project_cwd(&project_storage, external_agent_home);
        for path in cur_transcript_files(&project_storage.join("agent-transcripts")) {
            candidates.push(SessionFileCandidate {
                path,
                fallback_cwd: fallback_cwd.clone(),
                record_format: SessionRecordFormat::Cur,
            });
        }
    }
    detect_recent_sessions(
        codex_home, candidates, /*require_existing_cwd*/ false, limits,
    )
}

fn cur_transcript_files(transcripts_root: &Path) -> Vec<PathBuf> {
    let mut files = Vec::new();
    let mut pending = vec![transcripts_root.to_path_buf()];
    while let Some(directory) = pending.pop() {
        let Ok(entries) = fs::read_dir(directory) else {
            continue;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            let Ok(file_type) = entry.file_type() else {
                continue;
            };
            if file_type.is_dir() {
                if entry.file_name() != "subagents" {
                    pending.push(path);
                }
            } else if file_type.is_file()
                && path.extension().and_then(|extension| extension.to_str()) == Some("jsonl")
            {
                files.push(path);
            }
        }
    }
    files.sort();
    files
}

fn cur_project_cwd(project_storage: &Path, external_agent_home: &Path) -> Option<PathBuf> {
    let encoded = project_storage.file_name()?.to_str()?;
    // Cursor stores projectless chats under this reserved project name.
    if encoded == "empty-window" {
        let external_agent_home = if external_agent_home.is_absolute() {
            external_agent_home.to_path_buf()
        } else {
            std::env::current_dir().ok()?.join(external_agent_home)
        };
        return external_agent_home.parent().map(Path::to_path_buf);
    }
    decode_cur_project_path(encoded)
}

fn decode_cur_project_path(encoded: &str) -> Option<PathBuf> {
    let mut remaining_names = MAX_CUR_TOTAL_DIRECTORY_NAMES;
    decode_cur_project_path_with_probes(encoded, Path::is_dir, |directory| {
        if remaining_names == 0 {
            return None;
        }
        let entries = fs::read_dir(directory).ok()?;
        let entry_limit = remaining_names.min(MAX_CUR_DIRECTORY_NAMES + 1);
        let mut count = 0;
        let mut names = std::collections::HashSet::new();
        for entry in entries.take(entry_limit) {
            count += 1;
            remaining_names -= 1;
            if count > MAX_CUR_DIRECTORY_NAMES {
                return None;
            }
            let name = entry.ok()?.file_name().into_string().ok()?;
            if !name.is_ascii() {
                return None;
            }
            names.insert(name.to_ascii_lowercase());
        }
        if count == entry_limit {
            return None;
        }
        Some(names)
    })
}

fn decode_cur_project_path_with_probes(
    encoded: &str,
    mut is_directory: impl FnMut(&Path) -> bool,
    mut directory_names: impl FnMut(&Path) -> Option<std::collections::HashSet<String>>,
) -> Option<PathBuf> {
    #[cfg(not(windows))]
    let root = PathBuf::from("/");

    #[cfg(windows)]
    let (encoded, root) = {
        let (drive, encoded) = decode_cur_windows_project_drive(encoded)?;
        (encoded, PathBuf::from(format!("{drive}:\\")))
    };

    let encoded = encoded.strip_prefix('-').unwrap_or(encoded);
    let components = encoded.split('-').collect::<Vec<_>>();
    if components.iter().any(|component| {
        component.is_empty()
            || matches!(*component, "." | "..")
            || component.contains(['/', '\\', ':'])
    }) {
        return None;
    }

    let mut matched_path = None;
    let mut pending = vec![(root, 0)];
    let mut probes = 0;
    while let Some((prefix, start)) = pending.pop() {
        if probes == MAX_CUR_PROJECT_PATH_PROBES {
            return None;
        }
        probes += 1;
        // Only a complete bounded listing can exclude names. Every remaining candidate still
        // requires its own directory probe; a large or non-ASCII listing uses normal lookups.
        let names = directory_names(&prefix);
        for end in start + 1..=components.len() {
            let separators = if end == start + 1 {
                &[""][..]
            } else {
                &CUR_PROJECT_SEPARATORS[..]
            };
            for separator in separators {
                let candidate = prefix.join(components[start..end].join(separator));
                let known_missing = names.as_ref().is_some_and(|names| {
                    let Some(name) = candidate.file_name().and_then(|name| name.to_str()) else {
                        return false;
                    };
                    // Keep platform path aliases on the normal probe path.
                    name.is_ascii()
                        && !name.contains('~')
                        && !name.ends_with(['.', ' '])
                        && !names.contains(&name.to_ascii_lowercase())
                });
                if known_missing {
                    continue;
                }
                if probes == MAX_CUR_PROJECT_PATH_PROBES {
                    return None;
                }
                probes += 1;
                if !is_directory(&candidate) {
                    continue;
                }
                if end != components.len() {
                    pending.push((candidate, end));
                    continue;
                }
                if matched_path
                    .as_ref()
                    .is_some_and(|matched_path| matched_path != &candidate)
                {
                    return None;
                }
                matched_path = Some(candidate);
            }
        }
    }
    matched_path
}

#[cfg(any(windows, test))]
fn decode_cur_windows_project_drive(encoded: &str) -> Option<(char, &str)> {
    let drive = encoded.as_bytes().first().copied()?;
    if !drive.is_ascii_alphabetic() || encoded.as_bytes().get(1) != Some(&b'-') {
        return None;
    }

    Some((char::from(drive), encoded.get(2..)?))
}

#[cfg(test)]
#[path = "cur_tests.rs"]
mod tests;
