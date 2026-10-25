use super::*;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

#[test]
fn writable_root_metadata_order_is_stable_across_entry_order_and_presence() {
    let orders = [
        [".git", ".agents", ".codex"],
        [".git", ".codex", ".agents"],
        [".agents", ".git", ".codex"],
        [".agents", ".codex", ".git"],
        [".codex", ".git", ".agents"],
        [".codex", ".agents", ".git"],
    ];
    for present in 0..8 {
        for order in orders {
            let tmp = TempDir::new().expect("tempdir");
            let root = AbsolutePathBuf::from_absolute_path(
                tmp.path().canonicalize().expect("canonical root"),
            )
            .expect("absolute root");
            for (index, name) in PROTECTED_METADATA_PATH_NAMES.iter().enumerate() {
                if present & (1 << index) != 0 {
                    std::fs::create_dir(root.join(*name)).expect("create metadata directory");
                }
            }
            let first_custom = root.join("nested/.git");
            let last_custom = root.join("private");
            let mut entries = vec![
                FileSystemSandboxEntry::new(root.clone().into(), FileSystemAccessMode::Write),
                FileSystemSandboxEntry::new(
                    first_custom.clone().into(),
                    FileSystemAccessMode::Read,
                ),
            ];
            entries.extend(order.into_iter().map(|name| {
                FileSystemSandboxEntry::new(root.join(name).into(), FileSystemAccessMode::Read)
            }));
            entries.push(FileSystemSandboxEntry::new(
                last_custom.clone().into(),
                FileSystemAccessMode::Read,
            ));
            let policy = FileSystemSandboxPolicy::restricted(entries);
            let expected = vec![WritableRoot {
                root: root.clone(),
                read_only_subpaths: vec![
                    root.join(".git"),
                    root.join(".agents"),
                    root.join(".codex"),
                    first_custom,
                    last_custom,
                ],
                protected_metadata_names: PROTECTED_METADATA_PATH_NAMES
                    .iter()
                    .map(|name| (*name).to_string())
                    .collect(),
            }];
            assert_eq!(policy.get_writable_roots_with_cwd(root.as_path()), expected);
            assert_eq!(
                policy.get_writable_roots_with_cwd_preserving_mutable_paths(root.as_path()),
                expected
            );
            assert!(
                policy.can_write_path_with_cwd(root.join("allowed.txt").as_path(), root.as_path())
            );
            for path in &expected[0].read_only_subpaths {
                assert!(!policy.can_write_path_with_cwd(path.as_path(), root.as_path()));
            }
        }
    }
}
