use super::create_workspace_token;
use crate::acl::ensure_allow_mask_aces;
use crate::acl::ensure_allow_write_aces;
use crate::private_object_capabilities::private_object_capabilities;
use crate::read_capability::read_cap_sid_for_root;
use crate::token::LocalSid;
use crate::token::get_current_token_for_restriction;
use crate::token::get_logon_sid_bytes;
use crate::token::get_user_sid_bytes;
use crate::token::world_sid;
use crate::token_information::TokenInformation;
use anyhow::Result;
use pretty_assertions::assert_eq;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Security::ImpersonateLoggedOnUser;
use windows_sys::Win32::Security::RevertToSelf;
use windows_sys::Win32::Security::TokenRestrictedSids;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;

struct Token(HANDLE);

impl Drop for Token {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.0);
        }
    }
}

struct Impersonation;

impl Drop for Impersonation {
    fn drop(&mut self) {
        if unsafe { RevertToSelf() } == 0 {
            std::process::abort();
        }
    }
}

#[test]
fn workspace_token_separates_object_write_caps_from_read_and_route_sids() -> Result<()> {
    let base = Token(unsafe { get_current_token_for_restriction()? });
    let write = LocalSid::from_string("S-1-5-21-111-222-333-444")?;
    let read = LocalSid::from_string("S-1-5-21-111-222-333-445")?;
    let route = LocalSid::from_string("S-1-5-21-111-222-333-446")?;
    let token = Token(unsafe {
        create_workspace_token(base.0, &[write.as_ptr()], &[read.as_ptr(), route.as_ptr()])?
    });
    let information = unsafe { TokenInformation::query(token.0, TokenRestrictedSids)? };
    let mut actual = unsafe { information.group_sids()? };
    let copy = |sid: &LocalSid| unsafe {
        let length = windows_sys::Win32::Security::GetLengthSid(sid.as_ptr());
        std::slice::from_raw_parts(sid.as_ptr().cast::<u8>(), length as usize).to_vec()
    };
    let mut expected = vec![copy(&write), copy(&read), copy(&route)];
    actual.sort();
    expected.sort();
    assert_eq!(actual, expected);
    assert_eq!(
        unsafe { private_object_capabilities(token.0)? },
        vec![copy(&write)]
    );
    Ok(())
}

#[test]
fn workspace_token_rejects_ambient_user_group_and_logon_restrictions() -> Result<()> {
    let base = Token(unsafe { get_current_token_for_restriction()? });
    let write = LocalSid::from_string("S-1-5-21-111-222-333-447")?;
    let identities = unsafe {
        [
            get_user_sid_bytes(base.0)?,
            get_logon_sid_bytes(base.0)?,
            world_sid()?,
        ]
    };
    for mut identity in identities {
        let result = unsafe {
            create_workspace_token(base.0, &[write.as_ptr()], &[identity.as_mut_ptr().cast()])
        };
        match result {
            Ok(handle) => {
                drop(Token(handle));
                anyhow::bail!("workspace token accepted an ambient restricting SID");
            }
            Err(error) => assert_eq!(
                error.to_string(),
                "workspace restricting SIDs must not contain ambient token identities"
            ),
        }
    }
    Ok(())
}

#[test]
fn current_read_root_allows_reading_without_write_or_delete() -> Result<()> {
    let temporary = tempfile::tempdir()?;
    let readable = temporary.path().join("readable");
    let writable = temporary.path().join("writable");
    std::fs::create_dir(&readable)?;
    std::fs::create_dir(&writable)?;
    let file = readable.join("existing.txt");
    std::fs::write(&file, "preserved")?;
    let read = LocalSid::from_string(&read_cap_sid_for_root(&readable)?)?;
    let write = LocalSid::from_string("S-1-5-21-111-222-333-448")?;
    unsafe {
        ensure_allow_mask_aces(
            &readable,
            &[read.as_ptr()],
            FILE_GENERIC_READ | FILE_GENERIC_EXECUTE,
        )?;
        ensure_allow_write_aces(&writable, &[write.as_ptr()])?;
    }
    let base = Token(unsafe { get_current_token_for_restriction()? });
    let token =
        Token(unsafe { create_workspace_token(base.0, &[write.as_ptr()], &[read.as_ptr()])? });
    anyhow::ensure!(
        unsafe { ImpersonateLoggedOnUser(token.0) } != 0,
        "impersonate workspace token failed"
    );
    let impersonation = Impersonation;
    let contents = std::fs::read_to_string(&file)?;
    let outside_write = std::fs::write(&file, "changed").map_err(|error| error.kind());
    let outside_delete = std::fs::remove_file(&file).map_err(|error| error.kind());
    let inside = writable.join("allowed.txt");
    std::fs::write(&inside, "allowed")?;
    std::fs::remove_file(&inside)?;
    drop(impersonation);
    assert_eq!(
        (
            contents,
            outside_write,
            outside_delete,
            std::fs::read_to_string(&file)?
        ),
        (
            "preserved".to_string(),
            Err(std::io::ErrorKind::PermissionDenied),
            Err(std::io::ErrorKind::PermissionDenied),
            "preserved".to_string()
        )
    );
    Ok(())
}
