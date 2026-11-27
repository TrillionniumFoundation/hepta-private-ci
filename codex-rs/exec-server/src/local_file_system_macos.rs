use std::path::Path;
use std::path::PathBuf;

/// Include the verified system alias spelling of a stable Darwin file path.
///
/// F_GETPATH reports paths under /private, while permission entries and globs
/// can use /var, /tmp, or /etc. Keep both spellings for allow and deny checks.
/// Only inspect these fixed system links: resolving a permission entry's
/// mutable suffix could turn a replaced user symlink into a new read grant.
pub(super) fn authorized_read_path_candidates(final_path: &Path) -> Vec<PathBuf> {
    let mut candidates = vec![final_path.to_path_buf()];
    for (alias, expected_target) in [
        ("/var", "/private/var"),
        ("/tmp", "/private/tmp"),
        ("/etc", "/private/etc"),
    ] {
        let expected_target = Path::new(expected_target);
        let Ok(suffix) = final_path.strip_prefix(expected_target) else {
            continue;
        };
        let alias = Path::new(alias);
        let Ok(link_target) = std::fs::read_link(alias) else {
            continue;
        };
        if Path::new("/").join(link_target) != expected_target
            || alias.canonicalize().ok().as_deref() != Some(expected_target)
        {
            continue;
        }
        candidates.push(alias.join(suffix));
    }
    candidates
}
