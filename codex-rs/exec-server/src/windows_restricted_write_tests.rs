use std::path::Path;

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use codex_protocol::models::ManagedFileSystemPermissions;
use codex_protocol::models::PermissionProfile;
use codex_protocol::permissions::NetworkSandboxPolicy;
use codex_utils_path_uri::PathUri;
use pretty_assertions::assert_eq;

use crate::ExecutorFileSystem;
use crate::FileSystemSandboxContext;
use crate::WriteFileOptions;
use crate::fs_helper::FsHelperRequest;
use crate::fs_helper::run_direct_request;
use crate::local_file_system::LocalFileSystem;
use crate::protocol::FsWriteFileParams;

fn write_request(
    path: &Path,
    bytes: &[u8],
    follow_symlinks: bool,
) -> anyhow::Result<FsHelperRequest> {
    Ok(FsHelperRequest::WriteFile(FsWriteFileParams {
        path: PathUri::from_host_native_path(path)?,
        data_base64: STANDARD.encode(bytes),
        follow_symlinks: Some(follow_symlinks),
        sandbox: None,
    }))
}

#[tokio::test]
async fn restricted_helper_rejects_existing_hard_links_without_modification() -> anyhow::Result<()> {
    for follow_symlinks in [true, false] {
        let directory = tempfile::tempdir()?;
        let outside = directory.path().join("outside.txt");
        let workspace = directory.path().join("workspace");
        std::fs::create_dir(&workspace)?;
        let link = workspace.join("link.txt");
        std::fs::write(&outside, b"original outside bytes")?;
        std::fs::hard_link(&outside, &link)?;

        let error = run_direct_request(write_request(&link, b"replacement", follow_symlinks)?)
            .await
            .expect_err("the helper must reject an existing multi-link file");
        assert_eq!(error.code, -32600);
        assert_eq!(
            error.message,
            "restricted filesystem write requires a file with exactly one hard link"
        );
        assert_eq!(std::fs::read(&outside)?.as_slice(), b"original outside bytes");
        assert_eq!(std::fs::read(&link)?.as_slice(), b"original outside bytes");
        std::fs::write(&outside, b"still the same file")?;
        assert_eq!(std::fs::read(&link)?.as_slice(), b"still the same file");
    }
    Ok(())
}

#[tokio::test]
async fn restricted_helper_creates_and_rewrites_single_link_files() -> anyhow::Result<()> {
    for follow_symlinks in [true, false] {
        let directory = tempfile::tempdir()?;
        let path = directory.path().join("file.txt");
        for bytes in [b"initial longer contents".as_slice(), b"x".as_slice()] {
            run_direct_request(write_request(&path, bytes, follow_symlinks)?)
                .await
                .expect("a single-link write must succeed")
                .expect_write_file()
                .expect("the helper must return the existing write response");
            assert_eq!(std::fs::read(&path)?.as_slice(), bytes);
        }
    }
    Ok(())
}

#[tokio::test]
async fn unrestricted_filesystem_keeps_existing_hard_link_behavior() -> anyhow::Result<()> {
    let profiles = [
        PermissionProfile::Disabled,
        PermissionProfile::Managed {
            file_system: ManagedFileSystemPermissions::Unrestricted,
            network: NetworkSandboxPolicy::Restricted,
        },
        PermissionProfile::External {
            network: NetworkSandboxPolicy::Restricted,
        },
    ];
    let file_system = LocalFileSystem::unsandboxed();
    for profile in profiles {
        let sandbox = FileSystemSandboxContext::from_permission_profile(profile);
        for follow_symlinks in [true, false] {
            let directory = tempfile::tempdir()?;
            let original = directory.path().join("original.txt");
            let link = directory.path().join("link.txt");
            std::fs::write(&original, b"original contents")?;
            std::fs::hard_link(&original, &link)?;
            ExecutorFileSystem::write_file(
                &file_system,
                &PathUri::from_host_native_path(&link)?,
                b"updated".to_vec(),
                WriteFileOptions { follow_symlinks },
                Some(&sandbox),
            )
            .await?;
            assert_eq!(std::fs::read(&original)?.as_slice(), b"updated");
            assert_eq!(std::fs::read(&link)?.as_slice(), b"updated");
            std::fs::write(&original, b"same file after write")?;
            assert_eq!(std::fs::read(&link)?.as_slice(), b"same file after write");
        }
    }
    Ok(())
}
