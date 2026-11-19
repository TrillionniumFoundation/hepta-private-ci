use std::io;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::ptr;
use std::time::Duration;

use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::windows::named_pipe::ClientOptions;
use tokio::net::windows::named_pipe::NamedPipeClient;
use tokio::net::windows::named_pipe::ServerOptions;
use tokio::time::timeout;
use windows_sys::Win32::Foundation::ERROR_NO_TOKEN;
use windows_sys::Win32::Security::CreateWellKnownSid;
use windows_sys::Win32::Security::ImpersonateAnonymousToken;
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::WinAnonymousSid;
use windows_sys::Win32::Storage::FileSystem::SECURITY_ANONYMOUS;
use windows_sys::Win32::Storage::FileSystem::SECURITY_IDENTIFICATION;
use windows_sys::Win32::Storage::FileSystem::SECURITY_IMPERSONATION;
use windows_sys::Win32::System::Threading::GetCurrentThread;
use windows_sys::Win32::System::Threading::OpenThreadToken;

use super::super::Incoming;
use super::super::Listener;
use super::super::PREFACE;
use super::super::pipe_name;
use super::Descriptor;
use super::RevertGuard;
use super::Sid;
use super::authenticate_client;
use crate::OwnerLocalStream;

async fn raw_pair(qos: u32) -> io::Result<(tempfile::TempDir, Incoming, NamedPipeClient)> {
    let directory = tempfile::TempDir::new()?;
    let endpoint = directory.path().join("control");
    let mut listener = Listener::bind(&endpoint).await?;
    let name = pipe_name(&endpoint, &Sid::current()?)?;
    let client = ClientOptions::new().security_qos_flags(qos).open(name)?;
    let incoming = listener.accept().await?;
    Ok((directory, incoming, client))
}

fn no_thread_token() -> io::Result<()> {
    let mut token = ptr::null_mut();
    if unsafe { OpenThreadToken(GetCurrentThread(), TOKEN_QUERY, 1, &mut token) } != 0 {
        let _token = unsafe { OwnedHandle::from_raw_handle(token) };
        return Err(io::Error::other(
            "impersonation leaked onto the executor thread",
        ));
    }
    assert_eq!(
        io::Error::last_os_error().raw_os_error(),
        Some(ERROR_NO_TOKEN as i32)
    );
    Ok(())
}

#[tokio::test]
async fn owner_local_rejects_an_actual_handle_with_a_foreign_principal_grant() -> io::Result<()> {
    let directory = tempfile::TempDir::new()?;
    let endpoint = directory.path().join("control");
    let owner = Sid::current()?;
    let name = pipe_name(&endpoint, &owner)?;
    let sid = owner.sddl()?;
    for sddl in [
        format!("O:{sid}D:P(A;;0x001f01ff;;;{sid})(A;;GR;;;WD)"),
        format!("O:{sid}D:(A;;0x001f01ff;;;{sid})"),
        format!("O:{sid}D:NO_ACCESS_CONTROL"),
    ] {
        let descriptor = Descriptor::from_sddl(&sddl)?;
        let mut attributes = SECURITY_ATTRIBUTES {
            nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: descriptor.as_ptr(),
            bInheritHandle: 0,
        };
        let _weak_server = unsafe {
            ServerOptions::new()
                .first_pipe_instance(/*first*/ true)
                .create_with_security_attributes_raw(&name, ptr::addr_of_mut!(attributes).cast())
        }?;
        assert!(
            matches!(OwnerLocalStream::connect(&endpoint).await, Err(error) if error.kind() == io::ErrorKind::PermissionDenied)
        );
    }
    Ok(())
}

#[tokio::test]
async fn owner_local_dacl_denies_an_actual_anonymous_client_open() -> io::Result<()> {
    let directory = tempfile::TempDir::new()?;
    let endpoint = directory.path().join("control");
    let _listener = Listener::bind(&endpoint).await?;
    let name = pipe_name(&endpoint, &Sid::current()?)?;
    no_thread_token()?;
    if unsafe { ImpersonateAnonymousToken(GetCurrentThread()) } == 0 {
        return Err(io::Error::last_os_error());
    }
    {
        let _restore = RevertGuard;
        // No await while the thread carries the anonymous token.
        assert!(
            ClientOptions::new()
                .security_qos_flags(SECURITY_IDENTIFICATION)
                .open(name)
                .is_err()
        );
    }
    no_thread_token()
}

#[tokio::test]
async fn owner_local_rejects_wrong_preface_before_application_io() -> io::Result<()> {
    let (_directory, incoming, mut client) = raw_pair(SECURITY_IDENTIFICATION).await?;
    client.write_all(b"{\"method\":\"cancelTurn\"}\n").await?;
    assert!(
        matches!(super::super::authenticate(incoming).await, Err(error) if error.kind() == io::ErrorKind::InvalidData)
    );
    no_thread_token()
}

#[tokio::test]
async fn owner_local_rejects_anonymous_and_impersonation_level_clients_without_token_leak()
-> io::Result<()> {
    for qos in [SECURITY_ANONYMOUS, SECURITY_IMPERSONATION] {
        let (_directory, incoming, mut client) = raw_pair(qos).await?;
        client.write_all(PREFACE).await?;
        assert!(super::super::authenticate(incoming).await.is_err());
        no_thread_token()?;
    }
    Ok(())
}

#[tokio::test]
async fn owner_local_compares_the_real_client_token_and_reverts_after_rejection() -> io::Result<()>
{
    let (_directory, mut incoming, mut client) = raw_pair(SECURITY_IDENTIFICATION).await?;
    client.write_all(PREFACE).await?;
    let mut preface = [0; PREFACE.len()];
    incoming.pipe.read_exact(&mut preface).await?;
    assert_eq!(&preface, PREFACE);
    let mut bytes = [0u32; 17];
    let mut length = std::mem::size_of_val(&bytes) as u32;
    if unsafe {
        CreateWellKnownSid(
            WinAnonymousSid,
            ptr::null_mut(),
            bytes.as_mut_ptr().cast(),
            &mut length,
        )
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    let foreign = unsafe { Sid::copy(bytes.as_mut_ptr().cast()) }?;
    assert_ne!(Sid::current()?.0, foreign.0);
    assert!(super::verify_handle(incoming.pipe.as_raw_handle(), &foreign).is_err());
    assert!(authenticate_client(incoming.pipe.as_raw_handle(), &foreign).is_err());
    no_thread_token()?;
    // The same real client succeeds against its actual owner after rejection.
    authenticate_client(incoming.pipe.as_raw_handle(), &incoming.owner)?;
    no_thread_token()
}

#[tokio::test]
async fn owner_local_client_rejects_invalid_transport_acknowledgement() -> io::Result<()> {
    let directory = tempfile::TempDir::new()?;
    let endpoint = directory.path().join("control");
    let mut listener = Listener::bind(&endpoint).await?;
    let (server_result, client_result) = tokio::join!(
        async {
            let mut incoming = listener.accept().await?;
            let mut preface = [0; PREFACE.len()];
            incoming.pipe.read_exact(&mut preface).await?;
            assert_eq!(&preface, PREFACE);
            incoming.pipe.write_all(b"invalid-ack-v1\0\0").await?;
            Ok::<_, io::Error>(())
        },
        OwnerLocalStream::connect(endpoint),
    );
    server_result?;
    assert!(matches!(client_result, Err(error) if error.kind() == io::ErrorKind::InvalidData));
    Ok(())
}

#[tokio::test]
async fn owner_local_pending_handshake_remains_cancellable() -> io::Result<()> {
    let (_directory, incoming, _client) = raw_pair(SECURITY_IDENTIFICATION).await?;
    assert!(
        timeout(
            Duration::from_millis(20),
            super::super::authenticate(incoming)
        )
        .await
        .is_err()
    );
    no_thread_token()
}
