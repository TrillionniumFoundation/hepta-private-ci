//! The original Root grants one existing data input FD, never a B journal or
//! heldout writer. Only the same completed native Trainer supplies its bytes.

use std::fs::File;
use std::io;
use std::os::fd::AsRawFd;
use std::os::unix::fs::FileExt;
use std::os::unix::fs::MetadataExt;

use super::*;
use crate::cell_q24_training_receipt_owner::OriginalQ24TrainingOperationEvidenceV1;

pub(super) fn require_original_data_file(file: &File, bootstrap: &Bootstrap) -> io::Result<()> {
    let metadata = file.metadata()?;
    // SAFETY: F_GETFL observes the flags of this owned existing descriptor.
    let flags = unsafe { libc::fcntl(file.as_raw_fd(), libc::F_GETFL) };
    if flags < 0 {
        return Err(io::Error::last_os_error());
    }
    if flags & libc::O_ACCMODE != libc::O_RDWR
        || flags & (libc::O_PATH | libc::O_APPEND) != 0
        || !metadata.is_file()
        || metadata.uid() != 0
        || metadata.mode() & 0o7777 != 0o600
        || metadata.nlink() != 1
        || metadata.dev() != bootstrap.candidate_data_device
        || metadata.ino() != bootstrap.candidate_data_inode
        || metadata.len() > 32_780
    {
        return Err(io::Error::other(
            "original Root candidate data custody differs",
        ));
    }
    Ok(())
}

impl OriginalRootIndependentBEvaluationClientV1 {
    pub(super) fn write_original_candidate_data(
        &self,
        original: &OriginalQ24TrainingOperationEvidenceV1<'_>,
        scope: &FrozenLearningScopeV2,
    ) -> Result<Digest32, Error> {
        let result = (|| {
            self.require_initial(original.snapshot(), scope)?;
            let candidate = original.original_candidate_material()?;
            let bytes = &candidate.heads;
            if bytes.is_empty() || bytes.len() > 32_780 {
                return Err(Error::WrongScope);
            }
            let file = self
                .candidate_data
                .try_lock()
                .map_err(|_| Error::CommitUncertain)?;
            require_original_data_file(&file, &self.bootstrap).map_err(unavailable)?;
            file.try_lock().map_err(unavailable)?;
            let written = (|| {
                let length = file.metadata().map_err(unavailable)?.len();
                if length == 0 {
                    file.write_all_at(bytes, /*offset*/ 0)
                        .map_err(unavailable)?;
                    file.sync_all().map_err(unavailable)?;
                } else if length != bytes.len() as u64 {
                    return Err(Error::CommitUncertain);
                }
                // An existing image is only read, never truncated or rewritten.
                for _ in 0..2 {
                    require_original_data_file(&file, &self.bootstrap).map_err(unavailable)?;
                    if file.metadata().map_err(unavailable)?.len() != bytes.len() as u64 {
                        return Err(Error::CommitUncertain);
                    }
                    let mut actual = vec![0; bytes.len()];
                    file.read_exact_at(&mut actual, /*offset*/ 0)
                        .map_err(unavailable)?;
                    if actual != *bytes {
                        return Err(Error::CommitUncertain);
                    }
                }
                original.require_current_training_source()?;
                self.require_initial(original.snapshot(), scope)?;
                Ok(Digest32::of_bytes(bytes))
            })();
            let unlocked = file.unlock();
            let digest = written?;
            unlocked.map_err(unavailable)?;
            Ok(digest)
        })();
        if result.is_err() {
            self.refused.store(true, Ordering::Release);
        }
        result
    }
}
