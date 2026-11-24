//! Bounded namespace observations from a retained directory handle.
//!
//! Directory timestamps alone need not change when a child is created. These
//! entries are an endpoint witness, not an atomic snapshot or an ABA fence.

use std::fs::File;
use std::io;
use std::mem::offset_of;
use std::mem::size_of;
use std::os::windows::io::AsRawHandle;

use windows_sys::Win32::Foundation::ERROR_NO_MORE_FILES;
use windows_sys::Win32::Storage::FileSystem::FILE_ID_BOTH_DIR_INFO;
use windows_sys::Win32::Storage::FileSystem::FileIdBothDirectoryInfo;
use windows_sys::Win32::Storage::FileSystem::FileIdBothDirectoryRestartInfo;
use windows_sys::Win32::Storage::FileSystem::GetFileInformationByHandleEx;

const BUFFER_BYTES: usize = 65_536;
const MAX_ENTRIES: usize = 4_096;
const MAX_PAGES: usize = 128;
const MAX_NAME_BYTES: usize = 255 * 2;

#[repr(align(8))]
struct Page([u8; BUFFER_BYTES]);

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) struct Entry {
    name: Vec<u16>,
    file_id: i64,
    attributes: u32,
    length: i64,
    creation_time: i64,
    write_time: i64,
    change_time: i64,
}

/// The caller serializes enumeration on this handle: Windows retains its cursor.
pub(super) fn capture(directory: &File) -> io::Result<Vec<Entry>> {
    // FILE_ID_BOTH_DIR_INFO requires 8-byte alignment, including on 32-bit hosts.
    let mut storage = Box::new(Page([0; BUFFER_BYTES]));
    let mut entries = Vec::new();
    for page in 0..MAX_PAGES {
        storage.0.fill(0);
        // SAFETY: The directory handle is retained and the aligned allocation
        // is writable for exactly BUFFER_BYTES. Each capture restarts the cursor.
        let result = unsafe {
            GetFileInformationByHandleEx(
                directory.as_raw_handle() as _,
                if page == 0 {
                    FileIdBothDirectoryRestartInfo
                } else {
                    FileIdBothDirectoryInfo
                },
                storage.0.as_mut_ptr().cast(),
                BUFFER_BYTES as u32,
            )
        };
        if result == 0 {
            let error = io::Error::last_os_error();
            if error.raw_os_error() != Some(ERROR_NO_MORE_FILES as i32) {
                return Err(error);
            }
            entries.sort_unstable_by(|left: &Entry, right| left.name.cmp(&right.name));
            if entries.windows(2).any(|pair| pair[0].name == pair[1].name) {
                return Err(super::unsafe_object());
            }
            return Ok(entries);
        }
        append_page(&storage, &mut entries)?;
    }
    Err(limit_exceeded())
}

fn append_page(storage: &Page, entries: &mut Vec<Entry>) -> io::Result<()> {
    let bytes = storage.0.len();
    let name_offset = offset_of!(FILE_ID_BOTH_DIR_INFO, FileName);
    let mut offset = 0_usize;
    loop {
        if !offset.is_multiple_of(8)
            || offset
                .checked_add(size_of::<FILE_ID_BOTH_DIR_INFO>())
                .is_none_or(|end| end > bytes)
        {
            return Err(super::unsafe_object());
        }
        // SAFETY: The initialized backing Page is 8-byte aligned; the
        // checked record header is in bounds and NextEntryOffset preserves alignment.
        let record = unsafe {
            &*storage
                .0
                .as_ptr()
                .cast::<u8>()
                .add(offset)
                .cast::<FILE_ID_BOTH_DIR_INFO>()
        };
        let length = record.FileNameLength as usize;
        if length == 0 || !length.is_multiple_of(2) || length > MAX_NAME_BYTES {
            return Err(super::unsafe_object());
        }
        let end = offset
            .checked_add(name_offset)
            .and_then(|start| start.checked_add(length))
            .filter(|end| *end <= bytes)
            .ok_or_else(super::unsafe_object)?;
        // SAFETY: The UTF-16 span is initialized, even-sized, aligned and bounded
        // by `end`. Names are length-delimited and need not be NUL terminated.
        let name = unsafe {
            std::slice::from_raw_parts(
                storage
                    .0
                    .as_ptr()
                    .cast::<u8>()
                    .add(offset + name_offset)
                    .cast::<u16>(),
                length / 2,
            )
        };
        if name != [u16::from(b'.')] && name != [u16::from(b'.'), u16::from(b'.')] {
            if entries.len() == MAX_ENTRIES {
                return Err(limit_exceeded());
            }
            if record.EndOfFile < 0 || name.contains(&0) {
                return Err(super::unsafe_object());
            }
            entries.push(Entry {
                name: name.to_vec(),
                file_id: record.FileId,
                attributes: record.FileAttributes,
                length: record.EndOfFile,
                creation_time: record.CreationTime,
                write_time: record.LastWriteTime,
                change_time: record.ChangeTime,
            });
        }
        if record.NextEntryOffset == 0 {
            return Ok(());
        }
        let next = offset
            .checked_add(record.NextEntryOffset as usize)
            .filter(|next| *next >= end)
            .ok_or_else(super::unsafe_object)?;
        offset = next;
    }
}

fn limit_exceeded() -> io::Error {
    io::Error::new(
        io::ErrorKind::Unsupported,
        "private directory exceeds the bounded namespace inspection budget",
    )
}
