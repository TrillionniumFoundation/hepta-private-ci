use std::ffi::OsString;
use std::io;
use std::os::windows::ffi::OsStrExt;
use std::os::windows::io::AsRawHandle;
use std::path::Path;
use std::sync::Arc;
use std::time::Duration;

use sha2::Digest;
use sha2::Sha256;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::windows::named_pipe::ClientOptions;
use tokio::net::windows::named_pipe::NamedPipeServer;
use tokio::net::windows::named_pipe::ServerOptions;
use tokio::time::sleep;
use tokio::time::timeout;
use windows_sys::Win32::Foundation::ERROR_PIPE_BUSY;
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::SECURITY_IDENTIFICATION;

use super::OwnerLocalStream;

#[path = "owner_local_security.rs"]
mod security;
use security::Descriptor;
use security::Sid;

const PREFACE: &[u8; 16] = b"hepta-owner-v1\0\0";
const ACK: &[u8; 16] = b"hepta-owner-ok\0\0";
const HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(2);

pub(super) struct Listener {
    name: OsString,
    next: NamedPipeServer,
    descriptor: Descriptor,
    owner: Arc<Sid>,
}

pub(super) struct Incoming {
    pipe: NamedPipeServer,
    owner: Arc<Sid>,
}

enum Claim {
    First,
    Continuation,
}

impl Listener {
    pub(super) async fn bind(path: &Path) -> io::Result<Self> {
        let owner = Arc::new(Sid::current()?);
        let name = pipe_name(path, &owner)?;
        let sid = owner.sddl()?;
        let descriptor = Descriptor::from_sddl(&format!("O:{sid}D:P(A;;0x001f01ff;;;{sid})"))?;
        let next = create_server(&name, &descriptor, &owner, Claim::First)?;
        Ok(Self {
            name,
            next,
            descriptor,
            owner,
        })
    }

    pub(super) async fn accept(&mut self) -> io::Result<Incoming> {
        self.next.connect().await?;
        // Create the replacement while the current instance still owns the
        // namespace. Never close the last server handle between accepts.
        let replacement = create_server(
            &self.name,
            &self.descriptor,
            &self.owner,
            Claim::Continuation,
        )?;
        let pipe = std::mem::replace(&mut self.next, replacement);
        Ok(Incoming {
            pipe,
            owner: Arc::clone(&self.owner),
        })
    }
}

fn create_server(
    name: &OsString,
    descriptor: &Descriptor,
    owner: &Sid,
    claim: Claim,
) -> io::Result<NamedPipeServer> {
    let mut attributes = SECURITY_ATTRIBUTES {
        nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
        lpSecurityDescriptor: descriptor.as_ptr(),
        bInheritHandle: 0,
    };
    let mut options = ServerOptions::new();
    options
        .first_pipe_instance(matches!(claim, Claim::First))
        .reject_remote_clients(/*reject*/ true)
        // 32 application slots, a connected accept, and its replacement.
        .max_instances(/*instances*/ 34);
    // The descriptor and attributes are live and aligned; Windows copies the
    // descriptor atomically as part of CreateNamedPipeW.
    let pipe = unsafe {
        options.create_with_security_attributes_raw(name, std::ptr::addr_of_mut!(attributes).cast())
    }?;
    security::verify_handle(pipe.as_raw_handle(), owner)?;
    Ok(pipe)
}

/// The name is a deterministic, lossless binding to the supplied endpoint and
/// current user. Only the local pipe namespace is used, including for UNC paths.
fn pipe_name(path: &Path, owner: &Sid) -> io::Result<OsString> {
    if !path.is_absolute() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "owner-local endpoint must be absolute",
        ));
    }
    let mut digest = Sha256::new();
    digest.update(b"hepta-owner-local-v1\0");
    let sid = owner.sddl()?;
    digest.update((sid.len() as u64).to_le_bytes());
    digest.update(sid.as_bytes());
    for unit in path.as_os_str().encode_wide() {
        digest.update(unit.to_le_bytes());
    }
    Ok(OsString::from(format!(
        r"\\.\pipe\hepta-owner-local-v1-{:x}",
        digest.finalize()
    )))
}

pub(super) async fn authenticate(incoming: Incoming) -> io::Result<OwnerLocalStream> {
    timeout(HANDSHAKE_TIMEOUT, async move {
        let Incoming { mut pipe, owner } = incoming;
        let mut preface = [0u8; PREFACE.len()];
        pipe.read_exact(&mut preface).await?;
        if &preface != PREFACE {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "invalid owner-local transport preface",
            ));
        }
        // Impersonation is synchronous and ends before write_all can yield.
        security::authenticate_client(pipe.as_raw_handle(), &owner)?;
        pipe.write_all(ACK).await?;
        Ok(OwnerLocalStream {
            inner: Box::new(pipe),
        })
    })
    .await
    .map_err(|_| {
        io::Error::new(
            io::ErrorKind::TimedOut,
            "owner-local transport handshake expired",
        )
    })?
}

pub(super) async fn connect(path: &Path) -> io::Result<OwnerLocalStream> {
    timeout(HANDSHAKE_TIMEOUT, async {
        let owner = Sid::current()?;
        let name = pipe_name(path, &owner)?;
        let mut pipe = loop {
            match ClientOptions::new()
                .security_qos_flags(SECURITY_IDENTIFICATION)
                .open(&name)
            {
                Ok(pipe) => break pipe,
                Err(error) if error.raw_os_error() == Some(ERROR_PIPE_BUSY as i32) => {
                    sleep(Duration::from_millis(10)).await
                }
                Err(error) => return Err(error),
            }
        };
        security::verify_handle(pipe.as_raw_handle(), &owner)?;
        pipe.write_all(PREFACE).await?;
        let mut ack = [0u8; ACK.len()];
        pipe.read_exact(&mut ack).await?;
        if &ack != ACK {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "invalid owner-local transport acknowledgement",
            ));
        }
        Ok(OwnerLocalStream {
            inner: Box::new(pipe),
        })
    })
    .await
    .map_err(|_| {
        io::Error::new(
            io::ErrorKind::TimedOut,
            "owner-local transport handshake expired",
        )
    })?
}
