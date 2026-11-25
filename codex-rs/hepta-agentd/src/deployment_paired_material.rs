//! Fixed held training inputs. Installation only inspects descriptor metadata.
//! The first byte is read by the paired owner after its durable entry CAS.
use super::*;
use std::fs::File;
use std::os::fd::AsRawFd;
use std::os::unix::fs::FileExt;
use std::os::unix::fs::MetadataExt;

pub(crate) const MAX_TRAINING_MATERIAL_BYTES: u64 = 32 * 1024;

/// Frozen content references supplied by the trusted original composition.
/// This metadata is not a grant and cannot open or select a material path.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PairedTrainingMaterialManifestV1 {
    pub failure_sha256: Digest32,
    pub failure_bytes: u64,
    pub correction_sha256: Digest32,
    pub correction_bytes: u64,
}

impl PairedTrainingMaterialManifestV1 {
    pub fn commitment(&self) -> io::Result<Digest32> {
        if self.failure_sha256.is_zero()
            || self.correction_sha256.is_zero()
            || self.failure_bytes == 0
            || self.correction_bytes == 0
            || self
                .failure_bytes
                .checked_add(self.correction_bytes)
                .is_none_or(|bytes| bytes > MAX_TRAINING_MATERIAL_BYTES)
        {
            return Err(denied("invalid bounded paired training commitment"));
        }
        Ok(Digest32::of_bytes(&serde_json::to_vec(&(
            "hepta.paired-training-materials.v1",
            self.failure_sha256.to_string(),
            self.failure_bytes,
            self.correction_sha256.to_string(),
            self.correction_bytes,
        ))?))
    }

    pub(super) fn matches(&self, registration: &HostAuthorityPairedRegistration) -> io::Result<()> {
        if registration.request.materials != self.commitment()?
            || registration.preparation.frozen_materials != self.commitment()?
            || registration.request.original.usage
                != (crate::PairedLearningDataUse::TrainOnFailureAndCorrection {
                    failure: self.failure_sha256,
                    correction: self.correction_sha256,
                })
        {
            return Err(denied(
                "fixed training inputs differ from the original exact purpose",
            ));
        }
        Ok(())
    }
}

#[derive(PartialEq, Eq)]
struct MaterialStamp {
    device: u64,
    inode: u64,
    length: u64,
    uid: u32,
    mode: u32,
    links: u64,
    modified: (i64, i64),
    changed: (i64, i64),
}

impl MaterialStamp {
    fn read(file: &File) -> io::Result<Self> {
        let value = file.metadata()?;
        if !value.is_file() {
            return Err(denied(
                "paired material must be an existing regular descriptor",
            ));
        }
        Ok(Self {
            device: value.dev(),
            inode: value.ino(),
            length: value.len(),
            uid: value.uid(),
            mode: value.mode(),
            links: value.nlink(),
            modified: (value.mtime(), value.mtime_nsec()),
            changed: (value.ctime(), value.ctime_nsec()),
        })
    }
}

struct HeldMaterial {
    file: File,
    stamp: MaterialStamp,
    digest: Digest32,
}

impl HeldMaterial {
    fn capture(file: File, bytes: u64, digest: Digest32, owner_uid: u32) -> io::Result<Self> {
        // SAFETY: F_GETFL only observes the status flags of this held fd.
        let flags = unsafe { libc::fcntl(file.as_raw_fd(), libc::F_GETFL) };
        if flags < 0 {
            return Err(io::Error::last_os_error());
        }
        let stamp = MaterialStamp::read(&file)?;
        if flags & libc::O_ACCMODE != libc::O_RDONLY
            || flags & libc::O_PATH != 0
            || stamp.uid != owner_uid
            || stamp.mode & 0o077 != 0
            || stamp.links != 1
            || stamp.length != bytes
        {
            return Err(denied(
                "paired material descriptor differs from its private owner or size",
            ));
        }
        Ok(Self {
            file,
            stamp,
            digest,
        })
    }

    fn read_after_entry(
        &self,
        end: Instant,
        fence: &mut impl FnMut() -> io::Result<()>,
    ) -> io::Result<Vec<u8>> {
        if MaterialStamp::read(&self.file)? != self.stamp {
            return Err(denied("paired material changed before original entry"));
        }
        let bound = usize::try_from(self.stamp.length).map_err(io::Error::other)?;
        let mut bytes = vec![0; bound + 1];
        let mut length = 0;
        while length < bytes.len() {
            if Instant::now() >= end {
                return Err(denied(
                    "paired material read exceeded the original deadline",
                ));
            }
            let chunk_end = bytes.len().min(length + 4096);
            // The original locked owner rechecks all four leases, the held
            // human descriptors and the original peer at every actual pread.
            // Returning a future or checking only the whole batch is not entry.
            fence()?;
            let read = match self
                .file
                .read_at(&mut bytes[length..chunk_end], length as u64)
            {
                Ok(read) => read,
                Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
                Err(error) => return Err(error),
            };
            if read == 0 {
                break;
            }
            length += read;
        }
        bytes.truncate(length);
        if length != bound
            || MaterialStamp::read(&self.file)? != self.stamp
            || Digest32::of_bytes(&bytes) != self.digest
            || Instant::now() >= end
        {
            return Err(denied(
                "paired original content commitment or deadline changed",
            ));
        }
        Ok(bytes)
    }
}

pub(super) struct FixedTrainingMaterials {
    pub(super) manifest: PairedTrainingMaterialManifestV1,
    failure: HeldMaterial,
    correction: HeldMaterial,
}

pub(super) struct TrainingMaterialBytes {
    pub(super) failure: Vec<u8>,
    pub(super) correction: Vec<u8>,
}

impl FixedTrainingMaterials {
    pub(super) fn capture(
        registration: &HostAuthorityPairedRegistration,
        manifest: PairedTrainingMaterialManifestV1,
        failure: File,
        correction: File,
        owner_uid: u32,
    ) -> io::Result<Self> {
        manifest.matches(registration)?;
        let failure = HeldMaterial::capture(
            failure,
            manifest.failure_bytes,
            manifest.failure_sha256,
            owner_uid,
        )?;
        let correction = HeldMaterial::capture(
            correction,
            manifest.correction_bytes,
            manifest.correction_sha256,
            owner_uid,
        )?;
        if (failure.stamp.device, failure.stamp.inode)
            == (correction.stamp.device, correction.stamp.inode)
        {
            return Err(denied(
                "paired failure and correction require distinct original descriptors",
            ));
        }
        Ok(Self {
            manifest,
            failure,
            correction,
        })
    }

    pub(super) fn read_after_entry(
        &self,
        end: Instant,
        fence: &mut impl FnMut() -> io::Result<()>,
    ) -> io::Result<TrainingMaterialBytes> {
        let failure = self.failure.read_after_entry(end, fence)?;
        let correction = self.correction.read_after_entry(end, fence)?;
        Ok(TrainingMaterialBytes {
            failure,
            correction,
        })
    }
}
