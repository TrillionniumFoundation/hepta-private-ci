//! Storage and real host callbacks for the HIA patch effect planner.
//!
//! HIA owns ordering, retries, delta exactness, committed-delta decisions and
//! removal-error byte comparison. Path parsing and filesystem calls retain the
//! original executor, sandbox reference and caller-supplied symlink policy.

use std::io;
use std::path::PathBuf;

use anyhow::Result;
use codex_exec_server::CreateDirectoryOptions;
use codex_exec_server::ExecutorFileSystem;
use codex_exec_server::FileSystemSandboxContext;
use codex_exec_server::GetMetadataOptions;
use codex_exec_server::ReadFileOptions;
use codex_exec_server::RemoveOptions;
use codex_exec_server::WriteFileOptions;
use codex_utils_path_uri::PathUri;

use crate::AffectedPaths;
use crate::AppliedPatchChange;
use crate::AppliedPatchDelta;
use crate::AppliedPatchFileChange;
use crate::ApplyPatchFileUpdateMode;
use crate::ApplyPatchOptions;
use crate::Hunk;
use crate::file_update::derive_new_contents_from_chunks;

unsafe extern "C" {
    fn codex_hia_patch_effects(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

#[derive(Debug)]
struct NativeTransportError(String);

impl std::fmt::Display for NativeTransportError {
    fn fmt(&self, output: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(output, "HIA patch_effects: {}", self.0)
    }
}

impl std::error::Error for NativeTransportError {}

fn rejected(message: &str) -> anyhow::Error {
    anyhow::Error::new(NativeTransportError(message.to_owned()))
}

fn required<T>(value: &Option<T>) -> Result<&T> {
    value
        .as_ref()
        .ok_or_else(|| rejected("selected host value is absent"))
}

fn number(value: u64) -> Result<usize> {
    usize::try_from(value).map_err(|_| rejected("native index does not fit usize"))
}

#[derive(Default)]
struct Storage {
    source: Option<PathUri>,
    destination: Option<PathUri>,
    parent: Option<PathUri>,
    affected: Option<PathBuf>,
    old: Option<String>,
    new: Option<String>,
    overwritten_destination: Option<String>,
    observed: Option<String>,
    last_error: Option<anyhow::Error>,
    remove_error: Option<anyhow::Error>,
}

#[derive(Default)]
struct Continuation {
    phase: u64,
    index: usize,
    destination_index: Option<usize>,
    old_present: bool,
    status: u64,
    metadata: u64,
    parent_present: bool,
}

impl Continuation {
    fn clear_callback(&mut self) {
        self.status = 0;
        self.metadata = 0;
        self.parent_present = false;
    }

    fn io_result<T>(&mut self, storage: &mut Storage, result: io::Result<T>) -> Option<T> {
        match result {
            Ok(value) => {
                self.status = 1;
                storage.last_error = None;
                Some(value)
            }
            Err(error) => {
                self.status = if error.kind() == io::ErrorKind::NotFound {
                    2
                } else {
                    3
                };
                storage.last_error = Some(error.into());
                None
            }
        }
    }

    fn host_result<T>(&mut self, storage: &mut Storage, result: Result<T>) -> Option<T> {
        match result {
            Ok(value) => {
                self.status = 1;
                storage.last_error = None;
                Some(value)
            }
            Err(error) => {
                self.status = 3;
                storage.last_error = Some(error);
                None
            }
        }
    }

    fn invoke(
        &self,
        hunks: &[Hunk],
        options: ApplyPatchOptions,
        delta: &AppliedPatchDelta,
        storage: &Storage,
    ) -> Result<[u64; 16]> {
        let (kind, moved) = match hunks.get(self.index) {
            Some(Hunk::AddFile { .. }) => (1, false),
            Some(Hunk::DeleteFile { .. }) => (2, false),
            Some(Hunk::UpdateFile { move_path, .. }) => (3, move_path.is_some()),
            None => (0, false),
        };
        let mode = match options.update_file_mode {
            ApplyPatchFileUpdateMode::NormalizeToLf => 0,
            ApplyPatchFileUpdateMode::PreserveLineEndings => 1,
        };
        let probe = matches!(self.phase, 13 | 31);
        let old = if probe {
            required(&storage.old)?.as_bytes()
        } else {
            &[]
        };
        let observed = if probe {
            storage.observed.as_deref().unwrap_or_default().as_bytes()
        } else {
            &[]
        };
        let observed_start = 176_usize
            .checked_add(old.len())
            .ok_or_else(|| rejected("request length overflow"))?;
        let needed = observed_start
            .checked_add(observed.len())
            .ok_or_else(|| rejected("request length overflow"))?;
        let header = [
            1,
            self.phase,
            hunks.len() as u64,
            self.index as u64,
            kind,
            u64::from(moved),
            u64::from(delta.exact),
            delta.changes.len() as u64,
            u64::from(self.old_present),
            self.destination_index.map_or(u64::MAX, |i| i as u64),
            self.status,
            self.metadata,
            u64::from(self.parent_present),
            old.len() as u64,
            if probe { 176 } else { 0 },
            observed.len() as u64,
            if probe { observed_start as u64 } else { 0 },
            u64::from(options.follow_symlinks),
            mode,
            0,
            0,
            0,
        ];
        let mut fixed = [0_u8; 176];
        for (bytes, word) in fixed.chunks_exact_mut(8).zip(header) {
            bytes.copy_from_slice(&word.to_le_bytes());
        }
        let mut payload = Vec::new();
        let source = if probe {
            payload
                .try_reserve_exact(needed)
                .map_err(|_| rejected("cannot allocate request"))?;
            payload.extend_from_slice(&fixed);
            payload.extend_from_slice(old);
            payload.extend_from_slice(observed);
            payload.as_slice()
        } else {
            fixed.as_slice()
        };
        let mut output = [0_u8; 128];
        let mut workspace = [];
        // SAFETY: buffers are disjoint and live for the synchronous call. Their
        // lengths match the borrowed ABI, and HIA retains no host pointers.
        let status = unsafe {
            codex_hia_patch_effects(
                source.as_ptr(),
                source.len() as u64,
                output.as_mut_ptr(),
                output.len() as u64,
                workspace.as_mut_ptr(),
                0,
            )
        };
        if status != 0 {
            return Err(rejected(&format!("native ABI rejected request ({status})")));
        }
        let mut words = [0; 16];
        for (value, bytes) in words.iter_mut().zip(output.chunks_exact(8)) {
            *value = u64::from_le_bytes(
                bytes
                    .try_into()
                    .map_err(|_| rejected("native word has invalid length"))?,
            );
        }
        if words[0] != 1
            || words[3] > 1
            || words[7] > 1
            || words[10] != kind
            || words[12] != u64::from(options.follow_symlinks)
            || words[13] != mode
            || words[14] != 0
            || words[15] != 0
            || number(words[5])? > hunks.len()
            || (words[1] != 18 && words[11] != 0)
        {
            return Err(rejected("native response framing differs"));
        }
        Ok(words)
    }
}

fn new_contents<'a>(hunk: &'a Hunk, storage: &'a Storage) -> Result<&'a String> {
    match hunk {
        Hunk::AddFile { contents, .. } => Ok(contents),
        Hunk::UpdateFile { .. } => required(&storage.new),
        Hunk::DeleteFile { .. } => Err(rejected("a delete has no write contents")),
    }
}

fn materialize_change(
    action: u64,
    previous_destination_index: Option<usize>,
    hunk: &Hunk,
    storage: &Storage,
    delta: &mut AppliedPatchDelta,
) -> Result<()> {
    let change = match action {
        0 => return Ok(()),
        1 => AppliedPatchChange {
            path: required(&storage.source)?.clone(),
            change: AppliedPatchFileChange::Add {
                content: new_contents(hunk, storage)?.clone(),
                overwritten_content: storage.old.clone(),
            },
        },
        2 => AppliedPatchChange {
            path: required(&storage.source)?.clone(),
            change: AppliedPatchFileChange::Delete {
                content: required(&storage.old)?.clone(),
            },
        },
        3 => AppliedPatchChange {
            path: required(&storage.source)?.clone(),
            change: AppliedPatchFileChange::Update {
                move_path: None,
                old_content: required(&storage.old)?.clone(),
                overwritten_move_content: None,
                new_content: new_contents(hunk, storage)?.clone(),
            },
        },
        4 => AppliedPatchChange {
            path: required(&storage.destination)?.clone(),
            change: AppliedPatchFileChange::Add {
                content: new_contents(hunk, storage)?.clone(),
                overwritten_content: storage.overwritten_destination.clone(),
            },
        },
        5 => AppliedPatchChange {
            path: required(&storage.source)?.clone(),
            change: AppliedPatchFileChange::Update {
                move_path: Some(required(&storage.destination)?.clone()),
                old_content: required(&storage.old)?.clone(),
                overwritten_move_content: storage.overwritten_destination.clone(),
                new_content: new_contents(hunk, storage)?.clone(),
            },
        },
        _ => return Err(rejected("unknown delta materialization")),
    };
    if action == 5 {
        let index = previous_destination_index
            .ok_or_else(|| rejected("destination delta index is absent"))?;
        *delta
            .changes
            .get_mut(index)
            .ok_or_else(|| rejected("destination delta index is outside the committed prefix"))? =
            change;
    } else {
        delta.changes.push(change);
    }
    Ok(())
}

fn selected_error(code: u64, storage: &mut Storage) -> Result<anyhow::Error> {
    if code == 1 {
        return Ok(anyhow::anyhow!("No files were modified."));
    }
    if code == 2 {
        return storage
            .last_error
            .take()
            .ok_or_else(|| rejected("host error is absent"));
    }
    let path = match code {
        3 | 5 | 7..=10 => required(&storage.source)?,
        4 | 6 => required(&storage.destination)?,
        _ => return Err(rejected("unknown native error selection")),
    }
    .inferred_native_path_string();
    let context = match code {
        3 | 4 => format!("Failed to write file {path}"),
        5 | 6 => format!("Failed to create parent directories for {path}"),
        7 | 8 => format!("Failed to delete file {path}"),
        9 | 10 => format!("Failed to remove original {path}"),
        _ => return Err(rejected("unknown native error context")),
    };
    let error = if matches!(code, 8 | 10) {
        io::Error::new(io::ErrorKind::InvalidInput, "path is a directory").into()
    } else if matches!(code, 7 | 9) {
        storage
            .remove_error
            .take()
            .or_else(|| storage.last_error.take())
            .ok_or_else(|| rejected("removal error is absent"))?
    } else {
        storage
            .last_error
            .take()
            .ok_or_else(|| rejected("write error is absent"))?
    };
    Ok(error.context(context))
}

pub(crate) async fn apply_hunks_to_files(
    hunks: &[Hunk],
    options: ApplyPatchOptions,
    cwd: &PathUri,
    fs: &dyn ExecutorFileSystem,
    sandbox: Option<&FileSystemSandboxContext>,
    delta: &mut AppliedPatchDelta,
) -> Result<AffectedPaths> {
    let result = execute(hunks, options, cwd, fs, sandbox, delta).await;
    // A transport failure may follow an already attempted host mutation.
    // Retain the known committed prefix without claiming complete coverage.
    if result
        .as_ref()
        .is_err_and(anyhow::Error::is::<NativeTransportError>)
    {
        delta.exact = false;
    }
    result
}

async fn execute(
    hunks: &[Hunk],
    options: ApplyPatchOptions,
    cwd: &PathUri,
    fs: &dyn ExecutorFileSystem,
    sandbox: Option<&FileSystemSandboxContext>,
    delta: &mut AppliedPatchDelta,
) -> Result<AffectedPaths> {
    let mut state = Continuation::default();
    let mut storage = Storage::default();
    let mut affected = AffectedPaths {
        added: Vec::new(),
        modified: Vec::new(),
        deleted: Vec::new(),
    };
    loop {
        let result = state.invoke(hunks, options, delta, &storage)?;
        delta.exact = result[3] == 1;
        if result[8] != 0 {
            let hunk = hunks
                .get(state.index)
                .ok_or_else(|| rejected("delta hunk is absent"))?;
            materialize_change(result[8], state.destination_index, hunk, &storage, delta)?;
        }
        if number(result[4])? != delta.changes.len() {
            return Err(rejected(
                "native delta length differs from committed storage",
            ));
        }
        if result[9] != 0 {
            let path = required(&storage.affected)?.clone();
            match result[9] {
                1 => affected.added.push(path),
                2 => affected.modified.push(path),
                3 => affected.deleted.push(path),
                _ => return Err(rejected("unknown affected-path materialization")),
            }
        }
        state.phase = result[2];
        state.index = number(result[5])?;
        state.destination_index = if result[6] == u64::MAX {
            None
        } else {
            Some(number(result[6])?)
        };
        state.old_present = result[7] == 1;
        state.clear_callback();
        let follow_symlinks = options.follow_symlinks;
        match result[1] {
            0 => return Ok(affected),
            17 => storage = Storage::default(),
            18 => return Err(selected_error(result[11], &mut storage)?),
            1 => {
                let hunk = hunks
                    .get(state.index)
                    .ok_or_else(|| rejected("source hunk is absent"))?;
                storage.affected = Some(hunk.path().to_path_buf());
                let resolved = hunk.resolve_path(cwd).map_err(anyhow::Error::from);
                storage.source = state.host_result(&mut storage, resolved);
            }
            5 => {
                let Some(Hunk::UpdateFile {
                    move_path: Some(path),
                    ..
                }) = hunks.get(state.index)
                else {
                    return Err(rejected("move destination is absent"));
                };
                let resolved = cwd
                    .join(&path.to_string_lossy())
                    .map_err(anyhow::Error::from);
                storage.destination = state.host_result(&mut storage, resolved);
            }
            2 | 6 | 14 => {
                let path = if result[1] == 6 {
                    required(&storage.destination)?
                } else {
                    required(&storage.source)?
                };
                let observed = fs
                    .get_metadata(path, GetMetadataOptions { follow_symlinks }, sandbox)
                    .await;
                if let Some(metadata) = state.io_result(&mut storage, observed) {
                    state.metadata = u64::from(metadata.is_file)
                        | (u64::from(metadata.is_symlink) << 1)
                        | (u64::from(metadata.is_directory) << 2);
                }
            }
            3 | 7 | 16 => {
                let path = if result[1] == 7 {
                    required(&storage.destination)?
                } else {
                    required(&storage.source)?
                };
                let observed = fs
                    .read_file_text(path, ReadFileOptions { follow_symlinks }, sandbox)
                    .await;
                let text = state.io_result(&mut storage, observed);
                match result[1] {
                    3 => storage.old = text,
                    7 => storage.overwritten_destination = text,
                    _ => storage.observed = text,
                }
            }
            4 => {
                let Some(Hunk::UpdateFile { chunks, .. }) = hunks.get(state.index) else {
                    return Err(rejected("update chunks are absent"));
                };
                let derived = derive_new_contents_from_chunks(
                    required(&storage.source)?,
                    chunks,
                    options.update_file_mode,
                    fs,
                    follow_symlinks,
                    sandbox,
                )
                .await
                .map_err(anyhow::Error::from);
                if let Some(derived) = state.host_result(&mut storage, derived) {
                    storage.old = Some(derived.original_contents);
                    storage.new = Some(derived.new_contents);
                }
            }
            8 | 9 => {
                let path = if result[1] == 9 {
                    required(&storage.destination)?
                } else {
                    required(&storage.source)?
                };
                let hunk = hunks
                    .get(state.index)
                    .ok_or_else(|| rejected("write hunk is absent"))?;
                let contents = new_contents(hunk, &storage)?.clone().into_bytes();
                let written = fs
                    .write_file(
                        path,
                        contents,
                        WriteFileOptions { follow_symlinks },
                        sandbox,
                    )
                    .await;
                state.io_result(&mut storage, written);
            }
            10 | 11 => {
                let path = if result[1] == 11 {
                    required(&storage.destination)?
                } else {
                    required(&storage.source)?
                };
                storage.parent = path.parent();
                state.parent_present = storage.parent.is_some();
                state.status = 1;
                storage.last_error = None;
            }
            12 | 13 => {
                let created = fs
                    .create_directory(
                        required(&storage.parent)?,
                        CreateDirectoryOptions {
                            recursive: true,
                            follow_symlinks,
                        },
                        sandbox,
                    )
                    .await;
                state.io_result(&mut storage, created);
            }
            15 => {
                let removed = fs
                    .remove(
                        required(&storage.source)?,
                        RemoveOptions {
                            recursive: false,
                            force: false,
                            follow_symlinks,
                        },
                        sandbox,
                    )
                    .await;
                state.io_result(&mut storage, removed);
                storage.remove_error = storage.last_error.take();
            }
            _ => return Err(rejected("unknown native filesystem effect")),
        }
    }
}
