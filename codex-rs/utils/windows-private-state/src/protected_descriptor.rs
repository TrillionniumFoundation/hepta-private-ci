//! An internal descriptor built only from the actual captured user.

use crate::security::CurrentUser;
use crate::security::ValidationError;
use std::ffi::c_void;
use std::mem::size_of;

pub(crate) struct ProtectedDescriptor {
    storage: Vec<usize>,
}
impl ProtectedDescriptor {
    pub(crate) fn for_user(user: &CurrentUser) -> Result<Self, ValidationError> {
        let sid = user.sid_bytes();
        if !(8..=68).contains(&sid.len()) || !sid.len().is_multiple_of(4) {
            return Err(ValidationError::MalformedDescriptor);
        }
        let acl = 20 + sid.len();
        let ace_size = 8 + sid.len();
        let size = acl + 8 + ace_size;
        let mut storage = vec![0_usize; size.div_ceil(size_of::<usize>())];
        // SAFETY: initialized aligned storage owns at least size bytes; this
        // mutable byte view ends before storage is moved into the descriptor.
        let bytes =
            unsafe { std::slice::from_raw_parts_mut(storage.as_mut_ptr().cast::<u8>(), size) };
        bytes[0] = 1;
        bytes[2..4].copy_from_slice(&0x9004_u16.to_le_bytes()); // self-relative protected DACL
        bytes[4..8].copy_from_slice(&20_u32.to_le_bytes());
        bytes[16..20].copy_from_slice(&(acl as u32).to_le_bytes());
        bytes[20..acl].copy_from_slice(sid);
        bytes[acl] = 2;
        bytes[acl + 2..acl + 4].copy_from_slice(&((8 + ace_size) as u16).to_le_bytes());
        bytes[acl + 4..acl + 6].copy_from_slice(&1_u16.to_le_bytes());
        bytes[acl + 10..acl + 12].copy_from_slice(&(ace_size as u16).to_le_bytes());
        bytes[acl + 12..acl + 16].copy_from_slice(&0x001f_01ff_u32.to_le_bytes());
        bytes[acl + 16..size].copy_from_slice(sid);
        Ok(Self { storage })
    }

    pub(crate) fn as_ptr(&self) -> *const c_void {
        self.storage.as_ptr().cast()
    }
}
