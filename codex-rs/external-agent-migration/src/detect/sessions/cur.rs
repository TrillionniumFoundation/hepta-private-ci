use super::common::SessionFileCandidate;
use super::common::detect_recent_sessions;
use crate::model::ExternalAgentSessionImportLimits;
use crate::sessions::ExternalAgentSessionMigration;
use crate::sessions::SessionRecordFormat;
use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fs;
use std::io;
use std::path::Path;
use std::path::PathBuf;

// Bound both the search frontier and native metadata calls, including misses.
// The latter can be comparatively expensive on a network filesystem.
const MAX_CUR_PROJECT_PATH_PREFIXES: usize = 128;
const MAX_CUR_PROJECT_PATH_PROBES: usize = 4096;
const MAX_CUR_PROJECT_COMPONENT_PARTS: usize = 4;
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
    #[cfg(not(windows))]
    let root = PathBuf::from("/");

    #[cfg(windows)]
    let (encoded, root) = {
        let (drive, encoded) = decode_cur_windows_project_drive(encoded)?;
        (encoded, PathBuf::from(format!("{drive}:\\")))
    };

    let encoded = encoded.strip_prefix('-').unwrap_or(encoded);
    let parts = encoded.split('-').collect::<Vec<_>>();
    for component in &parts {
        if component.is_empty()
            || matches!(*component, "." | "..")
            || component.contains(['/', '\\', ':'])
        {
            return None;
        }
    }

    let mut matched_path = None;
    let mut probes = 0;
    let mut pending = vec![(root, 0)];
    let mut visited = BTreeSet::new();
    while let Some((parent, start)) = pending.pop() {
        if !visited.insert((parent.clone(), start)) {
            continue;
        }
        if visited.len() > MAX_CUR_PROJECT_PATH_PREFIXES {
            return None;
        }
        if start == parts.len() {
            if matched_path
                .as_ref()
                .is_some_and(|matched_path| matched_path != &parent)
            {
                return None;
            }
            matched_path = Some(parent);
            continue;
        }

        // Search every existing prefix, rather than repairing only one suffix
        // or ancestor. Several components can contain encoded separators, and
        // each complete interpretation must be considered before accepting it.
        // Keep all consumed lengths if two spellings produce the same name.
        let mut component_ends: BTreeMap<String, Vec<usize>> = BTreeMap::new();
        component_ends.insert(parts[start].to_string(), vec![start + 1]);
        for length in 2..=MAX_CUR_PROJECT_COMPONENT_PARTS.min(parts.len() - start) {
            let end = start + length;
            for separator in CUR_PROJECT_SEPARATORS {
                component_ends
                    .entry(parts[start..end].join(separator))
                    .or_default()
                    .push(end);
            }
        }
        for (name, ends) in component_ends {
            if probes >= MAX_CUR_PROJECT_PATH_PROBES {
                return None;
            }
            probes += 1;
            let candidate = parent.join(name);
            // Let the filesystem resolve case, aliases, and traversal rights.
            // Comparing read_dir names would silently reject valid Windows
            // short names or paths on a case-insensitive filesystem.
            let metadata = match fs::metadata(&candidate) {
                Ok(metadata) => metadata,
                Err(error) if error.kind() == io::ErrorKind::NotFound => continue,
                Err(_) => return None,
            };
            if metadata.is_dir() {
                for end in ends {
                    pending.push((candidate.clone(), end));
                }
            }
        }
    }

    // Exhausted budgets or unreadable candidates return above, even after a
    // match: an incomplete search cannot establish that the cwd is unique.
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
