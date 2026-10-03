//! Read exact original header bytes without changing the held file cursor.
use crate::runtime_file_v2::MeasuredFileV2;
use serde::Deserialize;
use serde::Serialize;
use std::io;
use std::path::PathBuf;
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NeuronPreparedFileObservationV2 {
    pub path: PathBuf,
    pub device: u64,
    pub inode: u64,
    pub owner_uid: u32,
    pub owner_gid: u32,
    pub mode: u32,
    pub links: u64,
    pub length: u64,
    pub header: Vec<u8>,
}
impl NeuronPreparedFileObservationV2 {
    pub(crate) fn validate(&self) -> Result<(), io::Error> {
        if !self.path.is_absolute()
            || self.path.file_name().is_none()
            || self.links != 1
            || self.inode == 0
            || self.mode & 0o170000 != 0o100000
            || self.mode & 0o077 != 0
            || self.length != self.header.len() as u64
            || self.header.is_empty()
            || self.header.len() > 1024
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "original prepared file facts",
            ));
        }
        Ok(())
    }
}
impl MeasuredFileV2 {
    pub(crate) fn observe_prepared_header_v2(
        &self,
        expected: &[u8],
    ) -> io::Result<NeuronPreparedFileObservationV2> {
        self.verify_identity()?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::FileExt;
            use std::os::unix::fs::MetadataExt;
            let before = self.metadata()?;
            if before.len() != expected.len() as u64 {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    "prepared file is not one complete header",
                ));
            }
            let mut header = vec![0; expected.len()];
            self.read_exact_at(&mut header, 0)?;
            let after = self.metadata()?;
            self.verify_identity()?;
            if header != expected
                || before.dev() != after.dev()
                || before.ino() != after.ino()
                || before.len() != after.len()
                || before.mtime_nsec() != after.mtime_nsec()
                || before.ctime_nsec() != after.ctime_nsec()
                || before.mtime() != after.mtime()
                || before.ctime() != after.ctime()
            {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    "prepared file changed",
                ));
            }
            let result = NeuronPreparedFileObservationV2 {
                path: self.path_for_prepared_v2().to_owned(),
                device: after.dev(),
                inode: after.ino(),
                owner_uid: after.uid(),
                owner_gid: after.gid(),
                mode: after.mode(),
                links: after.nlink(),
                length: after.len(),
                header,
            };
            result.validate()?;
            Ok(result)
        }
        #[cfg(not(unix))]
        {
            let _ = expected;
            Err(io::Error::new(
                io::ErrorKind::Unsupported,
                "prepared descriptor facts require Unix",
            ))
        }
    }
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use std::fs::OpenOptions;
    use std::io::Seek;
    use std::io::SeekFrom;
    use std::io::Write;
    use std::os::unix::fs::OpenOptionsExt;
    #[test]
    fn actual_descriptor_read_preserves_cursor_and_denies_a_partial_tail() -> io::Result<()> {
        let root =
            std::env::temp_dir().join(format!("hepta-prepared-cursor-{}", std::process::id()));
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&root)?;
        let mut original = MeasuredFileV2::new(file, &root)?;
        let header = b"actual held descriptor header";
        original.write_all(header)?;
        original.sync_all()?;
        original.seek(SeekFrom::Start(5))?;
        let before = original.stream_position()?;
        let observed = original.observe_prepared_header_v2(header)?;
        assert_eq!(observed.header, header);
        assert_eq!(original.stream_position()?, before);
        assert_eq!(std::fs::read(&root)?, header);
        let mut external = OpenOptions::new().append(true).open(&root)?;
        external.write_all(b"torn")?;
        external.sync_all()?;
        assert!(original.observe_prepared_header_v2(header).is_err());
        assert_eq!(original.stream_position()?, before);
        drop(original);
        drop(external);
        std::fs::remove_file(root)?;
        Ok(())
    }
}
