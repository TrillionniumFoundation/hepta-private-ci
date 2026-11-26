//! Eight opens on four new fixtures; no deletion or authority change.

#[path = "token_delete_native_open_calls.rs"]
mod calls;
#[path = "token_delete_native_open_facts.rs"]
mod facts;
#[path = "token_delete_integrity_observations.rs"]
mod integrity;

use super::authorization::AuthorizationSnapshot;
use super::support;
use super::support::Dacl;
use super::support::Kind;
use super::support::RestrictedToken;
use super::support::Restriction;
use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use windows_sys::Win32::Foundation::ERROR_ACCESS_DENIED;
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
fn absolute_nt_and_win32_open_observations() -> Result<()> {
    let token = RestrictedToken::new(Restriction::Full)?;
    let mut observed = 0;
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
            .with_context(|| format!("native-open parent: {scenario:?}"))?;
        support::create_target(&target, Kind::Directory)?;
        let target_policy = match scenario {
            Scenario::Target => Dacl::Capability(DELETE),
            Scenario::NullParent => Dacl::Identity(FILE_ALL_ACCESS & !DELETE),
            Scenario::NullTarget => Dacl::Null,
            Scenario::Neither => Dacl::Identity(FILE_ALL_ACCESS),
        };
        support::set_dacl(&target, target_policy)
            .with_context(|| format!("native-open target: {scenario:?}"))?;
        let name = format!("{scenario:?}");
        let descriptors = (
            facts::descriptor_bytes(&parent)?,
            facts::descriptor_bytes(&target)?,
        );
        let objects = (
            integrity::object_facts(&parent)?,
            integrity::object_facts(&target)?,
        );
        let authorization = AuthorizationSnapshot::capture(&parent, &target, &name, "before")?;
        let (win32, native, token_facts) = token.run(|| -> Result<_> {
            let identity = facts::current_token(&name, "before")?;
            let token_facts = integrity::current_token_facts()?;
            authorization.observe_current_token(&name, "before")?;
            let win32 = calls::win32(&target, &name)?;
            let native = calls::native(&target, &name)?;
            authorization.observe_current_token(&name, "after")?;
            ensure!(
                identity == facts::current_token(&name, "after")?,
                "semantic token identity/privileges changed"
            );
            ensure!(
                token_facts == integrity::current_token_facts()?,
                "token integrity/policy changed"
            );
            Ok((win32, native, token_facts))
        })??;
        let after = (
            facts::descriptor_bytes(&parent)?,
            facts::descriptor_bytes(&target)?,
        );
        ensure!(
            descriptors == after,
            "full observed descriptor bytes changed: {scenario:?}"
        );
        ensure!(
            objects
                == (
                    integrity::object_facts(&parent)?,
                    integrity::object_facts(&target)?
                ),
            "object attributes/labels changed"
        );
        ensure!(
            target.is_dir() && std::fs::read_dir(&target)?.next().is_none(),
            "open-only fixture namespace changed"
        );
        for observation in [&win32, &native] {
            match scenario {
                Scenario::NullTarget => ensure!(
                    observation.opened && observation.error.is_none(),
                    "NULL-target successful control failed"
                ),
                Scenario::Neither => ensure!(
                    !observation.opened && observation.error == Some(ERROR_ACCESS_DENIED),
                    "Neither access-denied control changed"
                ),
                Scenario::Target | Scenario::NullParent => {}
            }
        }
        eprintln!(
            "HEPTA_NATIVE_INVARIANT scenario={scenario:?} same_token=true descriptor_bytes_equal=true descriptor_lengths=({}, {}) metadata_equal=true namespace_unchanged=true no_parent_handle=true token={token_facts:?} objects={objects:?}",
            descriptors.0.len(),
            descriptors.1.len(),
        );
        fixture
            .close()
            .with_context(|| format!("cleanup native-open fixture: {scenario:?}"))?;
        observed += 2;
    }
    ensure!(observed == 8, "expected eight distinct open observations");
    Ok(())
}
