//! Recover only this owner's demonstrably dead socket after process loss.
use crate::{AgentdError,AgentdState};
use crate::hmi_text::invalid;
use std::os::unix::fs::{FileTypeExt,MetadataExt,PermissionsExt};
use std::path::PathBuf;
use std::sync::{Arc,atomic::{AtomicBool,Ordering}};
use std::time::Duration;

pub(crate) struct SocketGuard {path:PathBuf,device:u64,inode:u64,active:Arc<AtomicBool>}
impl Drop for SocketGuard {
    fn drop(&mut self) {
        self.active.store(false,Ordering::SeqCst);
        if std::fs::symlink_metadata(&self.path).is_ok_and(|m|m.file_type().is_socket() && m.dev()==self.device && m.ino()==self.inode) {
            let _=std::fs::remove_file(&self.path);
        }
    }
}

pub(crate) async fn bind(state:&AgentdState,active:Arc<AtomicBool>)->Result<(codex_uds::UnixListener,SocketGuard),AgentdError> {
    let root=&state.identity().run_root;
    let directory=std::fs::symlink_metadata(root)?;
    if !directory.is_dir() || root.canonicalize()?!=*root
        || directory.mode() & 0o077!=0 || directory.uid()!=std::fs::metadata(&state.identity().home_root)?.uid()
    {return Err(invalid("HMI socket requires the existing canonical private owner run directory"));}
    let path=root.join("hmi-text.sock");
    state.refresh_generation()?;
    match tokio::fs::symlink_metadata(&path).await {
        Err(error) if error.kind()==std::io::ErrorKind::NotFound=>{},
        Err(error)=>return Err(error.into()),
        Ok(before)=>{
            if !before.file_type().is_socket() || before.uid()!=directory.uid() || before.mode() & 0o077!=0 || before.nlink()!=1 {
                return Err(invalid("existing HMI path is not this owner's private socket"));
            }
            match tokio::time::timeout(Duration::from_secs(1),codex_uds::UnixStream::connect(&path)).await {
                Ok(Err(error)) if error.kind()==std::io::ErrorKind::ConnectionRefused=>{},
                Ok(Ok(_))=>return Err(invalid("existing HMI socket is live")),
                Ok(Err(error))=>return Err(invalid(format!("cannot prove existing HMI socket dead: {error}"))),
                Err(_)=>return Err(invalid("existing HMI socket probe timed out")),
            }
            let after=tokio::fs::symlink_metadata(&path).await?;
            if !after.file_type().is_socket() || after.dev()!=before.dev() || after.ino()!=before.ino()
                || after.uid()!=before.uid() || after.mode()!=before.mode() || after.nlink()!=1
            {return Err(invalid("HMI socket changed during stale-owner probe"));}
            state.refresh_generation()?;
            tokio::fs::remove_file(&path).await?;
        }
    }
    let listener=codex_uds::UnixListener::bind(&path).await.map_err(|e|invalid(format!("bind HMI owner socket: {e}")))?;
    let metadata=std::fs::symlink_metadata(&path)?;
    let guard=SocketGuard {path:path.clone(),device:metadata.dev(),inode:metadata.ino(),active};
    // Only the socket just created by this owner is set private. Existing
    // directory, policy, device and deployment permissions are never changed.
    std::fs::set_permissions(path,std::fs::Permissions::from_mode(0o600))?;
    Ok((listener,guard))
}
