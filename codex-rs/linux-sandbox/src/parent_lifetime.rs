//! Keep the seccomp-filtered namespace init tied to its outer bubblewrap process.
//!
//! Bubblewrap's pre-exec parent-death signal can be cleared by an exec credential
//! transition. Re-arm it in the trusted inner stage and then check a stable
//! reference to the original parent, including when that parent is invisible in
//! the new PID namespace. No host pidfd may reach a proxy worker or user command.

use std::fs::File;
use std::io;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;

const PARENT_LIFETIME_FD_ARG: &str = "--parent-lifetime-fd";

pub(crate) fn preserve_for_inner_stage(
    argv: &mut Vec<String>,
    preserved_files: &mut Vec<File>,
) -> io::Result<()> {
    let command_index = argv
        .iter()
        .position(|argument| argument == "--")
        .map(|separator| separator + 1)
        .filter(|index| *index < argv.len())
        .ok_or_else(|| io::Error::other("bubblewrap is missing its inner command"))?;
    let inner_options = &argv[command_index + 1..];
    let inner_options = &inner_options[..inner_options
        .iter()
        .position(|argument| argument == "--")
        .unwrap_or(inner_options.len())];
    if !inner_options
        .iter()
        .any(|argument| argument == "--apply-seccomp-then-exec")
    {
        // The /bin/true proc-mount preflight does not enter our inner stage.
        return Ok(());
    }
    if inner_options.iter().any(|argument| {
        argument == PARENT_LIFETIME_FD_ARG || argument.starts_with("--parent-lifetime-fd=")
    }) {
        return Err(io::Error::other(
            "duplicate inner parent lifetime descriptor",
        ));
    }

    // This runs after any cleanup-supervisor fork, immediately before exec of
    // bubblewrap. Its single-threaded monitor is the inner stage's direct
    // parent: our generated flags use a fresh PID namespace, not --pidns.
    // Opening self here avoids PID reuse and binding to a more distant owner.
    // SAFETY: pidfd_open takes a current PID and zero flags, with no pointers.
    let descriptor = unsafe { libc::syscall(libc::SYS_pidfd_open, libc::getpid(), 0) };
    if descriptor < 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: pidfd_open returned a new descriptor, owned only by this File.
    let mut file = unsafe { File::from_raw_fd(descriptor as libc::c_int) };
    if file.as_raw_fd() <= libc::STDERR_FILENO {
        // A caller may have closed a standard stream. Keep the private channel
        // out of 0..=2 so bubblewrap's stdio handling cannot replace it.
        // SAFETY: file owns a live descriptor and F_DUPFD_CLOEXEC takes an int.
        let descriptor = unsafe {
            libc::fcntl(
                file.as_raw_fd(),
                libc::F_DUPFD_CLOEXEC,
                libc::STDERR_FILENO + 1,
            )
        };
        if descriptor < 0 {
            return Err(io::Error::last_os_error());
        }
        // SAFETY: fcntl returned a fresh descriptor distinct from file's fd.
        file = unsafe { File::from_raw_fd(descriptor) };
    }
    argv.splice(
        command_index + 1..command_index + 1,
        [
            PARENT_LIFETIME_FD_ARG.to_string(),
            file.as_raw_fd().to_string(),
        ],
    );
    // Both system and bundled launchers already make this list inheritable.
    preserved_files.push(file);
    Ok(())
}

pub(crate) fn bind_inner_to_parent(descriptor: libc::c_int) -> io::Result<()> {
    if descriptor <= libc::STDERR_FILENO {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "parent lifetime descriptor must not use standard streams",
        ));
    }
    // SAFETY: F_GETFD only validates the descriptor supplied by the launcher.
    let flags = unsafe { libc::fcntl(descriptor, libc::F_GETFD) };
    if flags < 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: this private argument transfers the launcher's live pidfd across
    // exec exactly once. No Rust object in this fresh process owns it yet.
    // The launcher establishes its type and identity; fcntl/poll alone cannot
    // authenticate an arbitrary descriptor supplied by a different caller.
    let file = unsafe { File::from_raw_fd(descriptor) };
    // SAFETY: file owns this descriptor; restore CLOEXEC as defense in depth.
    if unsafe { libc::fcntl(file.as_raw_fd(), libc::F_SETFD, flags | libc::FD_CLOEXEC) } < 0 {
        return Err(io::Error::last_os_error());
    }

    // Set first, then check. If the original parent died before this call, the
    // pidfd detects it even after reparenting; if it dies during or after the
    // check, SIGKILL terminates PID 1 and the kernel tears down its descendants.
    // The outer bwrap is single-threaded, so its pidfd and PDEATHSIG refer to
    // the same lifetime. getppid() may legitimately be zero in this namespace.
    // SAFETY: prctl receives a valid signal and no pointer arguments.
    if unsafe { libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGKILL, 0, 0, 0) } < 0 {
        return Err(io::Error::last_os_error());
    }
    let mut descriptor = libc::pollfd {
        fd: file.as_raw_fd(),
        events: libc::POLLIN,
        revents: 0,
    };
    loop {
        // SAFETY: poll receives one initialized pollfd and a zero timeout.
        let result = unsafe { libc::poll(&mut descriptor, 1, 0) };
        if result < 0 {
            let error = io::Error::last_os_error();
            if error.kind() == io::ErrorKind::Interrupted {
                continue;
            }
            return Err(error);
        }
        if result != 0 || descriptor.revents != 0 {
            return Err(io::Error::other(
                "outer bubblewrap parent has exited or is invalid",
            ));
        }
        // Close before initializing proxy workers or forking the user command.
        drop(file);
        return Ok(());
    }
}
