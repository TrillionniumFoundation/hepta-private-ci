//! A separate retained-handle deletion contract; the original Win32 gate is unchanged.

#[path = "token_delete_native_disposition_calls.rs"]
mod calls;
#[path = "token_delete_native_open_facts.rs"]
mod facts;
#[path = "token_delete_integrity_observations.rs"]
mod integrity;

use super::support;
use super::support::Dacl;
use super::support::Kind;
use super::support::RestrictedToken;
use super::support::Restriction;
use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;

#[derive(Clone, Copy, Debug)]
enum Scenario {
    Target,
    NullParent,
    NullTarget,
    Neither,
}

#[test]
fn delete_only_handle_marks_closes_and_removes_owned_directory() -> Result<()> {
    let token = RestrictedToken::new(Restriction::Full)?;
    let mut completed = 0;
    for scenario in [
        Scenario::Target,
        Scenario::NullParent,
        Scenario::NullTarget,
        Scenario::Neither,
    ] {
        let fixture = tempfile::tempdir()?;
        let parent = fixture.path().join("parent");
        let target = parent.join("target");
        std::fs::create_dir(&parent)?;
        let parent_policy = match scenario {
            Scenario::NullParent => Dacl::Null,
            Scenario::Neither => Dacl::Identity(FILE_ALL_ACCESS),
            Scenario::Target | Scenario::NullTarget => {
                Dacl::Identity(FILE_ALL_ACCESS & !FILE_DELETE_CHILD)
            }
        };
        support::set_dacl(&parent, parent_policy)
            .with_context(|| format!("disposition parent: {scenario:?}"))?;
        support::create_target(&target, Kind::Directory)?;
        let target_policy = match scenario {
            Scenario::Target => Dacl::Capability(DELETE),
            Scenario::NullParent => Dacl::Identity(FILE_ALL_ACCESS & !DELETE),
            Scenario::NullTarget => Dacl::Null,
            Scenario::Neither => Dacl::Identity(FILE_ALL_ACCESS),
        };
        support::set_dacl(&target, target_policy)
            .with_context(|| format!("disposition target: {scenario:?}"))?;
        let name = format!("{scenario:?}");
        let descriptors = (
            facts::descriptor_bytes(&parent)?,
            facts::descriptor_bytes(&target)?,
        );
        let objects = (
            integrity::object_facts(&parent)?,
            integrity::object_facts(&target)?,
        );
        ensure!(
            std::fs::read_dir(&target)?.next().is_none(),
            "target is not empty"
        );
        let (attempt, token_check) = token.run(|| -> Result<_> {
            let identity = facts::current_token(&name, "before-disposition")?;
            let token_facts = integrity::current_token_facts()?;
            let attempt = (|| -> Result<bool> {
                let handle = calls::open_delete(&target, &name)?;
                match (scenario, handle) {
                    (Scenario::Neither, None) => Ok(false),
                    (Scenario::Neither, Some(handle)) => {
                        calls::close(handle, &name, "unexpected-neither-grant")?;
                        anyhow::bail!("Neither unexpectedly obtained DELETE authority");
                    }
                    (
                        Scenario::Target | Scenario::NullParent | Scenario::NullTarget,
                        Some(handle),
                    ) => {
                        calls::mark_and_close(handle, &name)?;
                        Ok(true)
                    }
                    (Scenario::Target | Scenario::NullParent | Scenario::NullTarget, None) => {
                        anyhow::bail!("positive disposition fixture did not open");
                    }
                }
            })();
            let token_check = (|| -> Result<()> {
                ensure!(
                    identity == facts::current_token(&name, "after-disposition")?,
                    "semantic token identity/privileges changed"
                );
                ensure!(
                    token_facts == integrity::current_token_facts()?,
                    "token integrity/policy changed"
                );
                Ok(())
            })();
            Ok((attempt, token_check))
        })??;
        // Record the namespace even after a terminal operation error. Preserve
        // that operation's original error before a later observer error.
        let target_exists = target.try_exists();
        eprintln!(
            "HEPTA_DISPOSITION_NAMESPACE scenario={scenario:?} target_exists={target_exists:?}"
        );
        let deleted = attempt.with_context(|| format!("disposition operation: {scenario:?}"))?;
        token_check?;
        let exists = target_exists.context("observe final disposition namespace")?;
        ensure!(
            exists != deleted,
            "final target namespace does not match disposition"
        );
        ensure!(
            descriptors.0 == facts::descriptor_bytes(&parent)?,
            "parent full descriptor changed"
        );
        let parent_after = integrity::object_facts(&parent)?;
        // Child removal can legitimately change ordinary directory metadata.
        // The full parent security descriptor/label stays exact; the metadata
        // observer still rejects readonly/reparse objects before and after.
        let target_state = if exists {
            ensure!(
                descriptors.1 == facts::descriptor_bytes(&target)?
                    && objects.1 == integrity::object_facts(&target)?,
                "Neither target descriptor/metadata changed"
            );
            ensure!(
                std::fs::read_dir(&target)?.next().is_none(),
                "Neither target contents changed"
            );
            "unchanged"
        } else {
            "removed"
        };
        let children: Vec<_> = std::fs::read_dir(&parent)?
            .take(2)
            .map(|entry| entry.map(|entry| entry.file_name()))
            .collect::<std::io::Result<_>>()?;
        let expected_children = if exists {
            vec![std::ffi::OsString::from("target")]
        } else {
            vec![]
        };
        ensure!(
            children == expected_children,
            "unexpected final parent namespace"
        );
        eprintln!(
            "HEPTA_DISPOSITION_CONTRACT scenario={scenario:?} deleted={deleted} target_exists={exists} target_state={target_state} same_token=true parent_descriptor_equal=true parent_metadata_valid=true namespace_exact=true no_parent_handle=true parent_before={:?} parent_after={parent_after:?}",
            objects.0,
        );
        fixture
            .close()
            .with_context(|| format!("cleanup disposition fixture: {scenario:?}"))?;
        completed += 1;
    }
    ensure!(
        completed == 4,
        "expected four complete disposition contracts"
    );
    Ok(())
}
