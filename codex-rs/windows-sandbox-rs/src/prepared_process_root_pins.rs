//! Process-owner pins for the exact roots of an already verified ACL context.
use super::PreparedFilesystemAclContext;
use super::QUERY;
use super::descriptor;
use super::identity;
use crate::read_acl_query;
use anyhow::Result;
use anyhow::ensure;
use std::fs::File;
use std::os::windows::io::BorrowedHandle;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_DATA;

/// Private, non-inheritable owners; no caller can substitute paths or handles.
/// They do not establish descendant, loader or production-launch authority.
pub(crate) struct PreparedProcessRootPins {
    _roots: Vec<File>,
}

impl PreparedFilesystemAclContext {
    pub(crate) fn pin_process_roots(
        &mut self,
        base: BorrowedHandle<'_>,
    ) -> Result<PreparedProcessRootPins> {
        self.validate_for_token(base)?;
        self.refused = true;
        let roots = self
            .roots
            .iter()
            .map(|root| {
                // READ_DATA is LIST_DIRECTORY for directories. Unlike QUERY alone,
                // it participates in sharing checks with this open's no-DELETE-share.
                // The existing open also refuses reparses and never inherits handles.
                let file = read_acl_query::open_with_access(&root.path, QUERY | FILE_READ_DATA)?;
                ensure!(
                    identity(&file)? == root.identity && descriptor(&file)?.1 == root.descriptor,
                    "prepared process root identity or descriptor changed"
                );
                Ok(file)
            })
            .collect::<Result<Vec<_>>>()?;
        // Any failed open or comparison leaves refusal sticky and drops every
        // acquired pin. Revalidate the complete context and source token while
        // all successful pins are held before returning their private owner.
        self.refused = false;
        self.validate_for_token(base)?;
        Ok(PreparedProcessRootPins { _roots: roots })
    }
}
