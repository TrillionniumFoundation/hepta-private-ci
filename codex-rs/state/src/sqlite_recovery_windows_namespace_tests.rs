//! Real local namespace replacement while every original database FD is held.
//! Only this test's unused, per-login DOS mapping is created and removed.

use std::io;
use std::os::windows::ffi::OsStrExt;
use std::path::Path;
use std::path::PathBuf;
use windows_sys::Win32::Foundation::ERROR_FILE_NOT_FOUND;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Storage::FileSystem::*;

pub(super) struct DriveNamespace {
    device: Vec<u16>,
    letter: u8,
    target: Option<Vec<u16>>,
}

impl DriveNamespace {
    pub(super) fn create(target: &Path) -> io::Result<Self> {
        // SAFETY: these APIs read existing process-local/global device names.
        let used = unsafe { GetLogicalDrives() };
        if used == 0 {
            return Err(io::Error::last_os_error());
        }
        for letter in (b'F'..=b'Z').rev() {
            if used & (1 << (letter - b'A')) != 0 {
                continue;
            }
            let device = format!("{}:", char::from(letter))
                .encode_utf16()
                .chain([0])
                .collect::<Vec<_>>();
            let mut buffer = [0u16; 4096];
            // SAFETY: device is terminated; the output span is bounded.
            let size = unsafe {
                QueryDosDeviceW(device.as_ptr(), buffer.as_mut_ptr(), buffer.len() as u32)
            };
            if size != 0 {
                continue;
            }
            // Never replace another mapping after a failed query.
            if unsafe { GetLastError() } != ERROR_FILE_NOT_FOUND {
                return Err(io::Error::last_os_error());
            }
            let mut namespace = Self {
                device,
                letter,
                target: None,
            };
            namespace.install(target)?;
            let root = format!("{}:\\", char::from(letter))
                .encode_utf16()
                .chain([0])
                .collect::<Vec<_>>();
            // SAFETY: root is a terminated local device path. An unsupported
            // drive stays a real failing precondition, never a skipped test.
            if unsafe { GetDriveTypeW(root.as_ptr()) } != 3 {
                return Err(io::Error::other("local fixed namespace required"));
            }
            return Ok(namespace);
        }
        Err(io::Error::other("no unused local DOS drive namespace"))
    }

    pub(super) fn home(&self) -> PathBuf {
        PathBuf::from(format!("{}:\\private-home", char::from(self.letter)))
    }

    pub(super) fn replace(&mut self, target: &Path) -> io::Result<()> {
        self.close()?;
        self.install(target)
    }

    fn install(&mut self, target: &Path) -> io::Result<()> {
        let mut target: Vec<u16> = target.canonicalize()?.as_os_str().encode_wide().collect();
        if !target.starts_with(&[92, 92, 63, 92]) {
            return Err(io::Error::other("OS canonical namespace required"));
        }
        target[1] = 63; // \\?\ -> \??\, without following another alias.
        target.push(0);
        // SAFETY: both strings are terminated and live through the syscall.
        // No shell notification or global LocalSystem namespace is requested.
        if unsafe {
            DefineDosDeviceW(
                DDD_RAW_TARGET_PATH | DDD_NO_BROADCAST_SYSTEM,
                self.device.as_ptr(),
                target.as_ptr(),
            )
        } == 0
        {
            return Err(io::Error::last_os_error());
        }
        self.target = Some(target);
        Ok(())
    }

    pub(super) fn close(&mut self) -> io::Result<()> {
        if let Some(target) = &self.target {
            // SAFETY: remove only the exact target installed by this object;
            // never pop or remove an unrelated process's device definition.
            if unsafe {
                DefineDosDeviceW(
                    DDD_RAW_TARGET_PATH
                        | DDD_REMOVE_DEFINITION
                        | DDD_EXACT_MATCH_ON_REMOVE
                        | DDD_NO_BROADCAST_SYSTEM,
                    self.device.as_ptr(),
                    target.as_ptr(),
                )
            } == 0
            {
                return Err(io::Error::last_os_error());
            }
            self.target = None;
        }
        Ok(())
    }
}

impl Drop for DriveNamespace {
    fn drop(&mut self) {
        let _ = self.close();
    }
}
