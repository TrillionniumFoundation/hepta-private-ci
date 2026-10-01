//! Bounded read-only JSONL access for authority-bearing historical observers.

use std::io;
use std::path::Path;

use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;

pub struct BoundedRolloutLineReader {
    inner: Reader,
    max_line_bytes: usize,
}

enum Reader {
    Plain(tokio::io::BufReader<tokio::fs::File>),
    Compressed(Option<std::io::BufReader<Box<dyn io::Read + Send>>>),
}

/// Open the selected rollout representation without materializing, repairing,
/// or appending. Both compressed and plain records have the same byte limit.
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
    if !tokio::fs::metadata(&path).await?.is_file() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "selected rollout is not a regular file",
        ));
    }
    let inner = if path.extension().is_some_and(|extension| extension == "zst") {
        let reader = tokio::task::spawn_blocking(move || {
            let file = std::fs::File::open(path)?;
            let mut decoder = zstd::stream::read::Decoder::new(file)?;
            // This must precede the first decoder read: a small frame header
            // can otherwise request a multi-gigabyte history window.
            decoder.window_log_max(25)?;
            Ok::<_, io::Error>(std::io::BufReader::new(
                Box::new(decoder) as Box<dyn io::Read + Send>
            ))
        })
        .await
        .map_err(io::Error::other)??;
        Reader::Compressed(Some(reader))
    } else {
        Reader::Plain(tokio::io::BufReader::new(
            tokio::fs::File::open(path).await?,
        ))
    };
    Ok(BoundedRolloutLineReader {
        inner,
        max_line_bytes,
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
