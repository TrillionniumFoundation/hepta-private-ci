//! A narrow Darwin exception for killpg's zombie-only EPERM result.
//!
//! The caller still owns the unreaped Child and has just observed WNOWAIT exit.
//! Every failed or incomplete query keeps the original killpg error. These
//! observations do not contain a descendant that left the original group.

use std::io;
use std::mem::size_of;
use std::mem::size_of_val;

pub(super) fn require_sole_retained_zombie(child_pid: u32) -> io::Result<()> {
    let pid = libc::pid_t::try_from(child_pid)
        .map_err(|_| io::Error::other("retained child PID does not fit pid_t"))?;
    require_sole_group_member(pid)?;
    // SAFETY: proc_bsdinfo is a C output structure containing only integer data.
    let mut info: libc::proc_bsdinfo = unsafe { std::mem::zeroed() };
    // A nonzero arg is required for PROC_PIDTBSDINFO to include zombies.
    // The full returned size is mandatory; ESRCH or a short query is not success.
    let returned = unsafe {
        libc::proc_pidinfo(
            pid,
            libc::PROC_PIDTBSDINFO,
            /*include_zombies*/ 1,
            (&mut info as *mut libc::proc_bsdinfo).cast(),
            size_of::<libc::proc_bsdinfo>() as libc::c_int,
        )
    };
    if returned != size_of::<libc::proc_bsdinfo>() as libc::c_int
        || info.pbi_pid != child_pid
        || info.pbi_ppid != std::process::id()
        || info.pbi_pgid != child_pid
        || info.pbi_status != libc::SZOMB as u32
    {
        return Err(io::Error::other(
            "Darwin did not confirm the retained direct child as a zombie in its original group",
        ));
    }
    require_sole_group_member(pid)
}

fn require_sole_group_member(pid: libc::pid_t) -> io::Result<()> {
    // A two-slot buffer distinguishes exactly one member from a full/truncated
    // result. libproc lists both live and zombie processes and returns PID count,
    // not byte count. Zero, query errors, another PID, or two-or-more all refuse.
    let mut members = [0 as libc::pid_t; 2];
    let count = unsafe {
        libc::proc_listpgrppids(
            pid,
            members.as_mut_ptr().cast(),
            size_of_val(&members) as libc::c_int,
        )
    };
    if count != 1 || members[0] != pid {
        return Err(io::Error::other(
            "Darwin did not confirm a complete group containing only the retained child",
        ));
    }
    Ok(())
}
