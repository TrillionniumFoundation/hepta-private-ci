use super::JobObject;
use pretty_assertions::assert_eq;
use std::io;
use std::os::windows::io::AsRawHandle;
use winapi::um::jobapi2::QueryInformationJobObject;
use winapi::um::winnt::JOB_OBJECT_LIMIT_BREAKAWAY_OK;
use winapi::um::winnt::JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
use winapi::um::winnt::JOBOBJECT_EXTENDED_LIMIT_INFORMATION;
use winapi::um::winnt::JobObjectExtendedLimitInformation;

fn flags(job: &JobObject) -> io::Result<u32> {
    let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = unsafe { std::mem::zeroed() };
    let queried = unsafe {
        QueryInformationJobObject(
            job.as_raw_handle().cast(),
            JobObjectExtendedLimitInformation,
            std::ptr::addr_of_mut!(limits).cast(),
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            std::ptr::null_mut(),
        )
    };
    if queried == 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(limits.BasicLimitInformation.LimitFlags)
}

#[test]
fn controlled_job_keeps_ownership_after_preserve_attempt() -> io::Result<()> {
    let job = JobObject::create_without_breakaway()?;
    assert_eq!(flags(&job)?, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE);
    assert_eq!(
        job.preserve_descendants().unwrap_err().kind(),
        io::ErrorKind::PermissionDenied
    );
    assert_eq!(flags(&job)?, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE);
    Ok(())
}

#[test]
fn interactive_job_preserves_its_existing_descendant_contract() -> io::Result<()> {
    let job = JobObject::create()?;
    assert_eq!(
        flags(&job)?,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_BREAKAWAY_OK
    );
    job.preserve_descendants()?;
    assert_eq!(flags(&job)?, JOB_OBJECT_LIMIT_BREAKAWAY_OK);
    Ok(())
}
