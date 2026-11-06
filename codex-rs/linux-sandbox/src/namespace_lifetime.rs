//! A private liveness channel from the outer helper to its PID-namespace init.
//!
//! Bubblewrap creates a new session, so killing the outer process group cannot
//! directly reach the inner supervisor. Only the outer supervisor keeps one
//! socket peer. Duplicating the observing endpoint cannot keep that peer alive,
//! so EOF does not depend on when bubblewrap closes its inherited duplicates.

use std::fs::File;
use std::io;
use std::io::Read;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::fd::RawFd;
use std::os::unix::fs::FileTypeExt;

const INNER_ARGUMENT: &str = "--parent-lifetime-fd";

pub(crate) fn channel() -> io::Result<(File, File)> {
    let mut fds = [-1; 2];
    // SAFETY: socketpair initializes both entries on success. CLOEXEC prevents
    // unrelated execs from inheriting either peer; the launcher explicitly
    // preserves only the observing endpoint for the trusted inner helper.
    if unsafe {
        libc::socketpair(
            libc::AF_UNIX,
            libc::SOCK_STREAM | libc::SOCK_CLOEXEC,
            0,
            fds.as_mut_ptr(),
        )
    } < 0
    {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: socketpair returned two distinct, newly owned descriptors.
    Ok(unsafe { (File::from_raw_fd(fds[0]), File::from_raw_fd(fds[1])) })
}

pub(crate) fn attach_reader_argument(argv: &mut Vec<String>, reader: &File) -> io::Result<()> {
    let inner = argv
        .iter()
        .position(|argument| argument == "--")
        .and_then(|separator| separator.checked_add(1))
        .filter(|inner| *inner < argv.len())
        .ok_or_else(|| io::Error::other("missing trusted inner sandbox command"))?;
    let inner_options = &argv[inner + 1..];
    let trusted_inner = inner_options
        .iter()
        .take_while(|argument| argument.as_str() != "--")
        .any(|argument| argument == "--apply-seccomp-then-exec");
    let already_bound = inner_options
        .iter()
        .take_while(|argument| argument.as_str() != "--")
        .any(|argument| argument == INNER_ARGUMENT);
    if !trusted_inner || already_bound || reader.as_raw_fd() <= libc::STDERR_FILENO {
        return Err(io::Error::other("invalid inner sandbox lifetime binding"));
    }
    argv.splice(
        inner + 1..inner + 1,
        [INNER_ARGUMENT.to_string(), reader.as_raw_fd().to_string()],
    );
    Ok(())
}

pub(crate) struct InnerParentLifetime {
    reader: File,
}

impl InnerParentLifetime {
    /// Take the reader inherited by the trusted inner helper after exec.
    ///
    /// # Safety
    ///
    /// The caller transfers ownership of this inherited descriptor; no Rust
    /// owner may already own it. The inner entry point calls this once, before
    /// opening any descriptors on behalf of the sandboxed command.
    pub(crate) unsafe fn inherit(fd: RawFd) -> io::Result<Self> {
        // SAFETY: getpid has no pointer arguments and does not change state.
        if unsafe { libc::getpid() } != 1 {
            return Err(io::Error::other("inner sandbox must be PID namespace init"));
        }
        // SAFETY: the caller transfers the inherited descriptor exactly once.
        let reader = unsafe { take_reader(fd) }?;
        require_live_owner(&reader)?;
        Ok(Self { reader })
    }

    /// Start only after the command fork, so the new thread is never forked.
    ///
    /// The command child drops its copy of this reader before exec. No inner
    /// process receives the owner peer. Normal command completion still follows
    /// the existing waitpid path; the detached watcher ends with PID 1.
    pub(crate) fn start(self) -> io::Result<()> {
        drop(
            std::thread::Builder::new()
                .name("sandbox-parent".to_string())
                .spawn(move || {
                    let mut reader = self.reader;
                    wait_for_owner_loss(&mut reader);
                    // SAFETY: inherit established that this process is the
                    // init of the sandbox PID namespace. _exit terminates this
                    // process; the kernel terminates its namespace members.
                    // No external PID or process group is selected or signaled.
                    unsafe { libc::_exit(1) }
                })?,
        );
        Ok(())
    }
}

unsafe fn take_reader(fd: RawFd) -> io::Result<File> {
    if fd <= libc::STDERR_FILENO {
        return Err(io::Error::other(
            "lifetime reader must not use standard I/O",
        ));
    }
    // SAFETY: fcntl only inspects the supplied descriptor.
    let descriptor_flags = unsafe { libc::fcntl(fd, libc::F_GETFD) };
    if descriptor_flags < 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: the live descriptor was checked above and the caller transfers
    // its sole Rust ownership to this function.
    let reader = unsafe { File::from_raw_fd(fd) };
    // SAFETY: reader owns a live descriptor for both fcntl calls.
    let access_flags = unsafe { libc::fcntl(reader.as_raw_fd(), libc::F_GETFL) };
    if access_flags < 0 {
        return Err(io::Error::last_os_error());
    }
    if access_flags & libc::O_ACCMODE != libc::O_RDWR
        || access_flags & libc::O_NONBLOCK != 0
        || !reader.metadata()?.file_type().is_socket()
        || socket_option(fd, libc::SO_DOMAIN)? != libc::AF_UNIX
        || socket_option(fd, libc::SO_TYPE)? != libc::SOCK_STREAM
    {
        return Err(io::Error::other(
            "lifetime reader must be a blocking Unix stream socket",
        ));
    }
    let mut address = std::mem::MaybeUninit::<libc::sockaddr_storage>::zeroed();
    let mut address_len = std::mem::size_of::<libc::sockaddr_storage>() as libc::socklen_t;
    // SAFETY: the initialized buffer and length are valid for getpeername.
    // Requiring a peer rejects a listener or an unconnected stream socket.
    if unsafe { libc::getpeername(fd, address.as_mut_ptr().cast(), &mut address_len) } < 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: reader owns this connected Unix stream. All observing-endpoint
    // duplicates become read-only by protocol; none is the outer owner peer.
    if unsafe { libc::shutdown(fd, libc::SHUT_WR) } < 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: preserving existing flags and adding CLOEXEC makes the private
    // reader unavailable to any subsequent command exec.
    if unsafe {
        libc::fcntl(
            reader.as_raw_fd(),
            libc::F_SETFD,
            descriptor_flags | libc::FD_CLOEXEC,
        )
    } < 0
    {
        return Err(io::Error::last_os_error());
    }
    Ok(reader)
}

fn socket_option(fd: RawFd, option: libc::c_int) -> io::Result<libc::c_int> {
    let mut value: libc::c_int = 0;
    let mut length = std::mem::size_of_val(&value) as libc::socklen_t;
    // SAFETY: the output pointer and length describe one initialized integer.
    if unsafe {
        libc::getsockopt(
            fd,
            libc::SOL_SOCKET,
            option,
            (&mut value as *mut libc::c_int).cast(),
            &mut length,
        )
    } < 0
    {
        return Err(io::Error::last_os_error());
    }
    if length as usize != std::mem::size_of_val(&value) {
        return Err(io::Error::other("invalid lifetime socket option size"));
    }
    Ok(value)
}

fn require_live_owner(reader: &File) -> io::Result<()> {
    let mut descriptor = libc::pollfd {
        fd: reader.as_raw_fd(),
        events: libc::POLLIN,
        revents: 0,
    };
    loop {
        // SAFETY: descriptor is initialized and valid for this one-entry poll.
        let result = unsafe { libc::poll(&mut descriptor, 1, 0) };
        if result == 0 {
            return Ok(());
        }
        if result > 0 {
            // The owner peer never sends data. Readability, EOF, or an invalid
            // descriptor therefore cannot authorize starting a command.
            return Err(io::Error::other("outer sandbox owner is unavailable"));
        }
        let error = io::Error::last_os_error();
        if error.kind() != io::ErrorKind::Interrupted {
            return Err(error);
        }
    }
}

fn wait_for_owner_loss(reader: &mut File) {
    let mut byte = [0_u8; 1];
    loop {
        match reader.read(&mut byte) {
            Err(error) if error.kind() == io::ErrorKind::Interrupted => {}
            // Only an idle, open peer is valid. EOF, unexpected data, and
            // read errors all close this owner's sandbox conservatively.
            Ok(_) | Err(_) => return,
        }
    }
}

#[cfg(test)]
#[path = "namespace_lifetime_tests.rs"]
mod tests;
