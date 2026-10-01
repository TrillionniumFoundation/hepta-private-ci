//! Bounded read-only JSONL access for authority-bearing historical observers.

use std::io;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;

use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;

pub struct BoundedRolloutLineReader {
    inner: Reader,
    max_line_bytes: usize,
    guard: Arc<SelectedFile>,
}

enum Reader {
    Plain(tokio::io::BufReader<tokio::fs::File>),
    Compressed(Option<std::io::BufReader<Box<dyn io::Read + Send>>>),
}

struct SelectedFile {
    path: PathBuf,
    metadata: std::fs::Metadata,
    file: std::fs::File,
}

impl SelectedFile {
    fn verify(&self) -> io::Result<()> {
        let current = std::fs::symlink_metadata(&self.path).map_err(incomplete_file)?;
        let opened = self.file.metadata().map_err(incomplete_file)?;
        if !current.is_file()
            || !opened.is_file()
            || !same_file_snapshot(&self.metadata, &current)
            || !same_file_snapshot(&self.metadata, &opened)
        {
            return Err(incomplete_file(
                "selected rollout changed during observation",
            ));
        }
        Ok(())
    }
}

fn incomplete_file(error: impl Into<Box<dyn std::error::Error + Send + Sync>>) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, error)
}

fn same_file_snapshot(before: &std::fs::Metadata, after: &std::fs::Metadata) -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        (
            before.dev(),
            before.ino(),
            before.len(),
            before.mtime(),
            before.mtime_nsec(),
            before.ctime(),
            before.ctime_nsec(),
        ) == (
            after.dev(),
            after.ino(),
            after.len(),
            after.mtime(),
            after.mtime_nsec(),
            after.ctime(),
            after.ctime_nsec(),
        )
    }
    #[cfg(not(unix))]
    {
        before.len() == after.len()
            && before.modified().ok() == after.modified().ok()
            && before.created().ok() == after.created().ok()
    }
}

fn open_regular_rollout(path: &Path, expected: &std::fs::Metadata) -> io::Result<std::fs::File> {
    let mut options = std::fs::OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        // A regular-file-to-FIFO replacement must not strand a blocking worker.
        // Stable aliases in parent components remain valid; a leaf symlink does not.
        options.custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK);
    }
    let file = options.open(path).map_err(incomplete_file)?;
    let opened = file.metadata().map_err(incomplete_file)?;
    let current = std::fs::symlink_metadata(path).map_err(incomplete_file)?;
    if !expected.is_file()
        || !opened.is_file()
        || !current.is_file()
        || !same_file_snapshot(expected, &opened)
        || !same_file_snapshot(expected, &current)
    {
        return Err(incomplete_file("selected rollout changed while opening"));
    }
    Ok(file)
}

/// Open the selected rollout representation without materializing, repairing,
/// or appending. Both compressed and plain records have the same byte limit.
/// Unix opens reject leaf symlinks and special files without waiting for FIFO
/// writers. This does not promise cancellation of arbitrary filesystem I/O.
pub async fn open_bounded_rollout_line_reader(
    path: &Path,
    max_line_bytes: usize,
) -> io::Result<BoundedRolloutLineReader> {
    if max_line_bytes == 0 || max_line_bytes == usize::MAX {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "invalid rollout line byte limit",
        ));
    }
    let path = crate::existing_rollout_path(path).await.ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::NotFound,
            "selected rollout representation is absent",
        )
    })?;
    let metadata = tokio::fs::symlink_metadata(&path).await?;
    if !metadata.is_file() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "selected rollout is not a regular file",
        ));
    }
    let (inner, guard) = tokio::task::spawn_blocking(move || {
        let file = open_regular_rollout(&path, &metadata)?;
        let guard = Arc::new(SelectedFile {
            path,
            metadata,
            file: file.try_clone()?,
        });
        let inner = if guard
            .path
            .extension()
            .is_some_and(|extension| extension == "zst")
        {
            let mut decoder = zstd::stream::read::Decoder::new(file)?;
            // This must precede the first decoder read: a small frame header
            // can otherwise request a multi-gigabyte history window.
            decoder.window_log_max(25)?;
            Reader::Compressed(Some(std::io::BufReader::new(
                Box::new(decoder) as Box<dyn io::Read + Send>
            )))
        } else {
            Reader::Plain(tokio::io::BufReader::new(tokio::fs::File::from_std(file)))
        };
        guard.verify()?;
        Ok::<_, io::Error>((inner, guard))
    })
    .await
    .map_err(io::Error::other)??;
    Ok(BoundedRolloutLineReader {
        inner,
        max_line_bytes,
        guard,
    })
}

impl BoundedRolloutLineReader {
    /// Return only complete newline-terminated UTF-8 records. A caller must
    /// discard a scan on overflow, truncation, I/O failure, or cancellation.
    pub async fn next_line(&mut self) -> io::Result<Option<String>> {
        let cap = self.max_line_bytes;
        let mut bytes = Vec::new();
        match &mut self.inner {
            Reader::Plain(reader) => {
                reader
                    .take((cap + 1) as u64)
                    .read_until(b'\n', &mut bytes)
                    .await?;
            }
            Reader::Compressed(slot) => {
                let Some(mut reader) = slot.take() else {
                    return Err(io::Error::other("bounded rollout reader is busy"));
                };
                let (result, returned_reader) = tokio::task::spawn_blocking(move || {
                    let mut bytes = Vec::new();
                    let result = io::BufRead::read_until(
                        &mut io::Read::take(&mut reader, (cap + 1) as u64),
                        b'\n',
                        &mut bytes,
                    )
                    .map(|_| bytes)
                    .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error));
                    (result, reader)
                })
                .await
                .map_err(io::Error::other)?;
                *slot = Some(returned_reader);
                bytes = result?;
            }
        }
        if bytes.is_empty() {
            let guard = Arc::clone(&self.guard);
            tokio::task::spawn_blocking(move || guard.verify())
                .await
                .map_err(io::Error::other)??;
            return Ok(None);
        }
        if bytes.len() > cap || bytes.last() != Some(&b'\n') {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "rollout record exceeds its byte limit or is truncated",
            ));
        }
        bytes.pop();
        if bytes.last() == Some(&b'\r') {
            bytes.pop();
        }
        String::from_utf8(bytes)
            .map(Some)
            .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))
    }
}

#[cfg(test)]
#[path = "bounded_reader_tests.rs"]
mod tests;
