//! Windows bound private pipes for independent OpenSSH verification.
//! This is a native child/PID contract, not a Unix inherited-fd claim.

#[path = "windows_openssh_identity.rs"]
mod identity;
#[path = "windows_openssh_image.rs"]
mod image;
#[path = "windows_openssh_pipe.rs"]
mod pipe;

use crate::AcceptanceError;
use crate::durable::sha256;
use codex_utils_path::PrivateFile;
use codex_utils_path::PrivateFileIdentity;
use codex_utils_path::PrivateFileKind;
use codex_utils_path::PrivateSecurityIdentity;
use identity::TokenIdentity;
use image::SystemImage;
use pipe::PipeDelivery;
use pipe::PrivatePipe;
use pipe::native_error;
use std::fs::File;
use std::io;
use std::io::Write;
use std::os::windows::io::AsHandle;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Path;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;
use windows_sys::Win32::Foundation::*;
use windows_sys::Win32::System::Threading::*;

const VERIFY_DEADLINE: Duration = Duration::from_secs(5);

pub(crate) struct WindowsVerifierOwner {
    policy: PrivateFile,
    security: PrivateSecurityIdentity,
    token: TokenIdentity,
}

impl WindowsVerifierOwner {
    pub(crate) fn capture(path: &Path, pinned_sha256: &str) -> Result<Self, AcceptanceError> {
        let policy = PrivateFile::open_existing(path)?;
        if sha256(&policy.read_bounded(16 * 1024)?) != pinned_sha256 {
            return Err(invalid("native verifier owner policy digest changed"));
        }
        let borrowed = File::open(path)?;
        if &PrivateFileIdentity::inspect(&borrowed, PrivateFileKind::RegularFile)?
            != policy.identity()
        {
            return Err(invalid("native verifier owner policy object changed"));
        }
        let security = PrivateSecurityIdentity::inspect(&borrowed)?;
        let token = TokenIdentity::effective()?;
        policy.verify()?;
        Ok(Self {
            policy,
            security,
            token,
        })
    }

    fn verify_policy(&self) -> Result<(), AcceptanceError> {
        self.policy
            .verify()
            .map_err(|error| invalid(format!("native verifier owner policy changed: {error}")))
    }

    pub(crate) fn verify_openssh(
        &self,
        statement: &[u8],
        signature: &[u8],
        allowed: &[u8],
        principal: &str,
        namespace: &str,
    ) -> Result<(), AcceptanceError> {
        self.verify_policy()?;
        if statement.len() > crate::durable::MAX_SMALL_FILE_BYTES
            || signature.len() > 4096
            || allowed.len() > 16 * 1024
        {
            return Err(invalid(
                "native verifier inputs exceed their original bounds",
            ));
        }
        let result = self.run(statement, signature, allowed, principal, namespace);
        self.verify_policy()?;
        result
    }

    fn run(
        &self,
        statement: &[u8],
        signature: &[u8],
        allowed: &[u8],
        principal: &str,
        namespace: &str,
    ) -> Result<(), AcceptanceError> {
        let image = SystemImage::open()?;
        let allowed_pipe = PrivatePipe::create(self.security.descriptor_bytes())?;
        let signature_pipe = PrivatePipe::create(self.security.descriptor_bytes())?;
        let deadline = Instant::now() + VERIFY_DEADLINE;
        let mut owned = OwnedChild(
            Command::new(&image.path)
                .args(["-Y", "verify", "-f"])
                .arg(&allowed_pipe.name)
                .args(["-I", principal, "-n", namespace, "-s"])
                .arg(&signature_pipe.name)
                .env_clear()
                .env("LANG", "C")
                .env("LC_ALL", "C")
                .stdin(Stdio::piped())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()?,
        );
        let child = BoundChild::bind(&owned.0, &image, &self.token)?;
        let mut stdin = owned
            .0
            .stdin
            .take()
            .ok_or_else(|| invalid("native verifier stdin unavailable"))?;
        let io_result = std::thread::scope(|scope| -> io::Result<(PipeDelivery, PipeDelivery)> {
            let mut cleanup = RunCleanup {
                child: &child,
                allowed: &allowed_pipe,
                signature: &signature_pipe,
                exited: false,
            };
            let allowed_writer = scope.spawn(|| allowed_pipe.send(&child, allowed, deadline));
            let signature_writer = scope.spawn(|| signature_pipe.send(&child, signature, deadline));
            let body_writer = scope.spawn(move || stdin.write_all(statement));
            let remaining = deadline.saturating_duration_since(Instant::now());
            let millis = u32::try_from(remaining.as_millis())
                .unwrap_or(u32::MAX - 1)
                .max(1);
            let wait = unsafe { WaitForSingleObject(child.handle.as_raw_handle() as _, millis) };
            let wait_result = match wait {
                WAIT_OBJECT_0 => {
                    cleanup.exited = true;
                    Ok(())
                }
                WAIT_TIMEOUT => Err(io::Error::new(
                    io::ErrorKind::TimedOut,
                    "native OpenSSH verification deadline",
                )),
                _ => Err(native_error("WaitForSingleObject(native verifier child)")),
            };
            // Termination/disconnection must precede joining blocked workers,
            // including unwind paths. Normal workers flush then deliver EOF.
            let cleanup_result = cleanup.finish();
            let allowed_result = allowed_writer
                .join()
                .map_err(|_| io::Error::other("native allowed-signers worker panicked"))?;
            let signature_result = signature_writer
                .join()
                .map_err(|_| io::Error::other("native signature worker panicked"))?;
            let body_result = body_writer
                .join()
                .map_err(|_| io::Error::other("native statement worker panicked"))?;
            cleanup_result?;
            wait_result?;
            let allowed_delivery = allowed_result?;
            let signature_delivery = signature_result?;
            body_result?;
            Ok((allowed_delivery, signature_delivery))
        });
        let status = owned.0.wait()?;
        image.verify()?;
        let (allowed_delivery, signature_delivery) = io_result?;
        if signature_delivery != PipeDelivery::Consumed {
            return Err(invalid(
                "native verifier exited before consuming its bound signature",
            ));
        }
        if !status.success() {
            return Err(invalid("native OpenSSH SSHSIG verification failed"));
        }
        if allowed_delivery != PipeDelivery::Consumed {
            return Err(invalid(
                "successful native verifier did not consume its bound allowed signers",
            ));
        }
        Ok(())
    }
}

fn invalid(message: impl Into<String>) -> AcceptanceError {
    AcceptanceError::Invalid(message.into())
}

struct BoundChild {
    handle: OwnedHandle,
    pid: u32,
}

impl BoundChild {
    fn bind(
        child: &Child,
        image: &SystemImage,
        expected_token: &TokenIdentity,
    ) -> io::Result<Self> {
        let handle = child.as_handle().try_clone_to_owned()?;
        let mut path = vec![0u16; 32768];
        let mut count = path.len() as u32;
        if unsafe {
            QueryFullProcessImageNameW(
                handle.as_raw_handle() as _,
                0,
                path.as_mut_ptr(),
                &mut count,
            )
        } == 0
        {
            return Err(native_error(
                "QueryFullProcessImageNameW(actual verifier child)",
            ));
        }
        if count == 0 || count as usize >= path.len() {
            return Err(io::Error::other(
                "actual verifier child image path exceeds bound",
            ));
        }
        let actual = std::path::PathBuf::from(
            String::from_utf16(&path[..count as usize]).map_err(io::Error::other)?,
        );
        if !identity::same_file(&image.file, &image::open_held(&actual)?)?
            || TokenIdentity::process(child)? != *expected_token
        {
            return Err(io::Error::other(
                "actual verifier child image or owner token differs",
            ));
        }
        image.verify()?;
        #[cfg(test)]
        eprintln!(
            "HEPTA_WIN_SSHSIG_CHILD pid={} image_full_id={:?} token_user_owner_match=true",
            child.id(),
            codex_utils_path::WindowsFileId::inspect(&image.file)?
        );
        Ok(Self {
            handle,
            pid: child.id(),
        })
    }
}

struct OwnedChild(Child);

impl Drop for OwnedChild {
    fn drop(&mut self) {
        if !matches!(self.0.try_wait(), Ok(Some(_))) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
}

struct RunCleanup<'a> {
    child: &'a BoundChild,
    allowed: &'a PrivatePipe,
    signature: &'a PrivatePipe,
    exited: bool,
}

impl RunCleanup<'_> {
    fn finish(&mut self) -> io::Result<()> {
        let mut result = Ok(());
        if !self.exited {
            let handle = self.child.handle.as_raw_handle() as _;
            let terminated = unsafe { TerminateProcess(handle, 1) };
            let terminate_error = (terminated == 0)
                .then(|| native_error("TerminateProcess(native verifier cleanup)"));
            if let Some(error) = terminate_error
                && unsafe { WaitForSingleObject(handle, 0) } != WAIT_OBJECT_0
            {
                result = Err(error);
            } else if unsafe { WaitForSingleObject(handle, INFINITE) } != WAIT_OBJECT_0 {
                result = Err(native_error("WaitForSingleObject(native verifier cleanup)"));
            } else {
                self.exited = true;
            }
        }
        self.allowed.abort();
        self.signature.abort();
        result
    }
}

impl Drop for RunCleanup<'_> {
    fn drop(&mut self) {
        let _ = self.finish();
    }
}

#[cfg(test)]
#[path = "windows_openssh_tests.rs"]
mod tests;
