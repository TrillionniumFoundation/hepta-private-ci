//! The existing request binding uses the protocol's fallible policy seam codec.
use anyhow::Result;
use codex_protocol::permissions::FileSystemSandboxPolicy;
use codex_protocol::permissions::NetworkSandboxPolicy;
use codex_protocol::permissions::RawFileSystemSandboxPolicy;

pub(crate) fn value(
    policy: &FileSystemSandboxPolicy,
    network: NetworkSandboxPolicy,
) -> Result<serde_json::Value> {
    // Runtime policies intentionally do not implement Serialize. Refuse a path
    // the existing protocol codec cannot represent; never omit its permissions.
    let file_system =
        RawFileSystemSandboxPolicy::try_from(policy.clone()).map_err(anyhow::Error::msg)?;
    Ok(serde_json::json!({"file_system": file_system, "network": network}))
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_protocol::permissions::FileSystemAccessMode;
    use codex_protocol::permissions::FileSystemPath;
    use codex_protocol::permissions::FileSystemSandboxEntry;
    use codex_protocol::permissions::FileSystemSandboxKind;
    use codex_protocol::permissions::FileSystemSpecialPath::Root;
    use pretty_assertions::assert_eq;

    fn policy() -> FileSystemSandboxPolicy {
        let mut policy =
            FileSystemSandboxPolicy::restricted(vec![FileSystemSandboxEntry::skip_missing_path(
                FileSystemPath::Special { value: Root },
                FileSystemAccessMode::Read,
            )]);
        policy.glob_scan_max_depth = Some(7);
        policy
    }

    #[test]
    fn request_binding_roundtrips_every_runtime_filesystem_field() {
        let policy = policy();
        let binding = value(&policy, NetworkSandboxPolicy::Restricted).expect("binding");
        let raw: RawFileSystemSandboxPolicy =
            serde_json::from_value(binding["file_system"].clone()).expect("protocol codec");
        assert_eq!(
            FileSystemSandboxPolicy::try_from(raw).expect("runtime policy"),
            policy
        );
        assert_eq!(
            binding["network"],
            serde_json::to_value(NetworkSandboxPolicy::Restricted).expect("network")
        );
    }

    #[test]
    fn request_binding_changes_with_each_permission_input() {
        let policy = policy();
        let original = value(&policy, NetworkSandboxPolicy::Restricted).expect("binding");
        let mut depth = policy.clone();
        depth.glob_scan_max_depth = Some(8);
        let mut entries = policy.clone();
        entries.entries[0].access = FileSystemAccessMode::Write;
        let mut missing = policy.clone();
        missing.entries[0].missing_path_behavior = None;
        let mut kind = policy.clone();
        kind.kind = FileSystemSandboxKind::Unrestricted;
        for changed in [depth, entries, missing, kind] {
            assert_ne!(
                value(&changed, NetworkSandboxPolicy::Restricted).expect("changed binding"),
                original
            );
        }
        assert_ne!(
            value(&policy, NetworkSandboxPolicy::Enabled).expect("network binding"),
            original
        );
    }
}
