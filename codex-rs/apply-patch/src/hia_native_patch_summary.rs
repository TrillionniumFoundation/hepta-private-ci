//! Execute the exact original writer calls in the order selected by HIA.

use std::io;
use std::path::PathBuf;

use crate::AffectedPaths;

unsafe extern "C" {
    fn codex_hia_patch_summary(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

fn rejected(message: &'static str) -> io::Error {
    io::Error::other(message)
}

fn count(value: usize) -> io::Result<u64> {
    u64::try_from(value).map_err(|_| rejected("HIA patch_summary: count does not fit u64"))
}

fn path_at(paths: &[PathBuf], index: u64) -> io::Result<&PathBuf> {
    let index = usize::try_from(index)
        .map_err(|_| rejected("HIA patch_summary: index does not fit usize"))?;
    paths
        .get(index)
        .ok_or_else(|| rejected("HIA patch_summary: selected path is absent"))
}

fn step(state: [u64; 3], counts: [u64; 3]) -> io::Result<[u64; 8]> {
    let frame = [
        1, state[0], state[1], state[2], counts[0], counts[1], counts[2], 0,
    ];
    let mut source = [0u8; 64];
    for (index, value) in frame.into_iter().enumerate() {
        source[index * 8..index * 8 + 8].copy_from_slice(&value.to_le_bytes());
    }
    let mut output = [0u8; 64];
    // SAFETY: fixed stack buffers are live, disjoint and satisfy the locked
    // borrowed-buffer ABI. The entry retains no pointers and needs no workspace.
    let status = unsafe {
        codex_hia_patch_summary(
            source.as_ptr(),
            source.len() as u64,
            output.as_mut_ptr(),
            output.len() as u64,
            std::ptr::null_mut(),
            0,
        )
    };
    if status != 0 {
        return Err(io::Error::other(format!(
            "HIA patch_summary: native ABI rejected request ({status})"
        )));
    }
    let mut response = [0u64; 8];
    for (index, value) in response.iter_mut().enumerate() {
        let mut word = [0u8; 8];
        word.copy_from_slice(&output[index * 8..index * 8 + 8]);
        *value = u64::from_le_bytes(word);
    }
    if response[0] != 1
        || response[3] != 1
        || response[4] > 3
        || response[6] != 0
        || response[7] != 0
    {
        return Err(rejected("HIA patch_summary: invalid result frame"));
    }
    Ok(response)
}

/// Print the native-selected summary using the original formatting calls.
pub fn print_summary(affected: &AffectedPaths, out: &mut impl io::Write) -> io::Result<()> {
    let counts = [
        count(affected.added.len())?,
        count(affected.modified.len())?,
        count(affected.deleted.len())?,
    ];
    let mut state = [0u64; 3];
    loop {
        let response = step(state, counts)?;
        match response[1] {
            0 if response[2] == 0 && response[4] == 3 && response[5] == 0 => return Ok(()),
            1 if response[2] == 0 && response[4] == 0 && response[5] == 0 => {
                writeln!(out, "Success. Updated the following files:")?;
            }
            2 => {
                let path = path_at(&affected.added, response[2])?;
                writeln!(out, "A {}", path.display())?;
            }
            3 => {
                let path = path_at(&affected.modified, response[2])?;
                writeln!(out, "M {}", path.display())?;
            }
            4 => {
                let path = path_at(&affected.deleted, response[2])?;
                writeln!(out, "D {}", path.display())?;
            }
            _ => return Err(rejected("HIA patch_summary: invalid writer command")),
        }
        state = [response[3], response[4], response[5]];
    }
}
