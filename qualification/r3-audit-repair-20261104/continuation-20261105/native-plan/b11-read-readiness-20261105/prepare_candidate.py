import difflib
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent.parent
WIN = Path("codex-rs/windows-sandbox-rs/src/bin/setup_main/win.rs")
MUTEX = WIN.parent / "win/read_acl_mutex.rs"
TEST = WIN.parent / "win/read_acl_mutex_tests.rs"


def identity(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }


def replace_once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new, 1)


win = (WORKSPACE / "architecture-audit/b11-delete-boundary-20261105/source" / WIN).read_bytes()
assert identity(win)["blob"] == "1d9340c6db26d6d10c1b3edecb1c9fecc908ef1d"
mutex = (ROOT / "source" / MUTEX).read_bytes()
assert identity(mutex)["blob"] == "a96b6a502474a8bab3baa7842f36dfa814c9cc37"
(ROOT / "source" / WIN).parent.mkdir(parents=True, exist_ok=True)
(ROOT / "source" / WIN).write_bytes(win)

s = win.decode()
for line in (
    "use std::os::windows::process::CommandExt;\n",
    "use std::process::Command;\n",
    "use std::process::Stdio;\n",
    "use read_acl_mutex::read_acl_mutex_exists;\n",
):
    s = replace_once(s, line, "")
start = s.index("fn spawn_read_acl_helper(")
end = s.index("struct ReadAclSubjects", start)
s = s[:start] + s[end:]
old = '''    let _read_acl_guard = match acquire_read_acl_mutex()? {
        Some(guard) => guard,
        None => {
            log_line(log, "read ACL helper already running; skipping")?;
            return Ok(());
        }
    };
    log_line(log, "read-acl-only mode: applying read ACLs")?;
'''
new = '''    let _read_acl_guard = acquire_read_acl_mutex()?;
    log_line(log, "applying read ACLs for the current setup request")?;
'''
s = replace_once(s, old, new)
s = replace_once(s, '''        if payload.refresh_only {
            anyhow::bail!("read ACL run had errors");
        }
''', '''        anyhow::bail!("read ACL run had errors");
''')
s = replace_once(s, '''    // Deny-read ACEs must be present before the sandboxed command starts. Apply
    // them synchronously here instead of delegating them to the background
    // helper used for read grants.
''', '''    // Deny-read ACEs must be present before the sandboxed command starts.
    // Keep them synchronous before the read-grant stage below.
''')
start = s.index('    if payload.read_roots.is_empty() {', s.index('fn run_setup_full('))
end = s.index('    if refresh_only {\n        setup_runtime_bin::', start)
s = s[:start] + '''    if payload.read_roots.is_empty() {
        log_line(log, "no read roots to grant; skipping read ACL stage")?;
    } else {
        // Returning from full setup must include this request's read ACL work.
        // An existing mutex is not a receipt for this request's roots.
        run_read_acl_only(payload, log)?;
    }

''' + s[end:]
s = replace_once(s, "write roots (read roots delegated); errors={:?}",
                 "write roots after read ACL stage; errors={:?}")

mutex_new = '''use anyhow::Context;
use anyhow::Result;
use codex_windows_sandbox::to_wide;
use std::ffi::OsStr;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::ERROR_ALREADY_EXISTS;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::System::Threading::CreateMutexW;
use windows_sys::Win32::System::Threading::ReleaseMutex;

const READ_ACL_MUTEX_NAME: &str = "Local\\\\CodexSandboxReadAcl";

pub(super) struct ReadAclMutexGuard {
    handle: HANDLE,
}

impl Drop for ReadAclMutexGuard {
    fn drop(&mut self) {
        unsafe {
            let _ = ReleaseMutex(self.handle);
            CloseHandle(self.handle);
        }
    }
}

pub(super) fn acquire_read_acl_mutex() -> Result<ReadAclMutexGuard> {
    acquire_named_read_acl_mutex(OsStr::new(READ_ACL_MUTEX_NAME))
}

fn acquire_named_read_acl_mutex(name: &OsStr) -> Result<ReadAclMutexGuard> {
    let name = to_wide(name);
    // SAFETY: name is NUL-terminated and valid for this call. The new handle
    // cannot be inherited, and only a newly created mutex is initially owned.
    let handle = unsafe { CreateMutexW(std::ptr::null(), /*binitialowner*/ 1, name.as_ptr()) };
    let error = unsafe { GetLastError() };
    if handle == 0 {
        return Err(std::io::Error::from_raw_os_error(error as i32))
            .context("CreateMutexW failed for read ACL preparation");
    }
    if error == ERROR_ALREADY_EXISTS {
        // Opening an existing object does not acquire it or prove that any
        // earlier request completed. Close this non-owning handle and fail.
        unsafe {
            CloseHandle(handle);
        }
        return Err(std::io::Error::from_raw_os_error(error as i32)).context(
            "read ACL preparation mutex already exists; current request is not ready",
        );
    }
    Ok(ReadAclMutexGuard { handle })
}

#[cfg(test)]
#[path = "read_acl_mutex_tests.rs"]
mod tests;
'''

tests = '''use super::acquire_named_read_acl_mutex;
use anyhow::Context;
use anyhow::Result;
use codex_windows_sandbox::to_wide;
use pretty_assertions::assert_eq;
use std::ffi::OsStr;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::os::windows::io::RawHandle;
use windows_sys::Win32::Foundation::ERROR_ALREADY_EXISTS;
use windows_sys::Win32::System::Threading::MUTEX_ALL_ACCESS;
use windows_sys::Win32::System::Threading::OpenMutexW;

#[test]
fn existing_read_acl_mutex_is_not_a_completion_receipt() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let unique = temp.path().file_name().expect("owned temporary directory");
    let name = format!("Local\\\\CodexSandboxReadAclTest-{}", unique.to_string_lossy());
    let name = OsStr::new(&name);
    let first = acquire_named_read_acl_mutex(name)?;

    let competing = acquire_named_read_acl_mutex(name)
        .err()
        .expect("an existing mutex must not report readiness");
    assert_eq!(
        competing
            .downcast_ref::<std::io::Error>()
            .and_then(std::io::Error::raw_os_error),
        Some(ERROR_ALREADY_EXISTS as i32)
    );
    assert_eq!(
        competing.to_string(),
        "read ACL preparation mutex already exists; current request is not ready"
    );

    let wide_name = to_wide(name);
    // SAFETY: the live owner's name is NUL-terminated and valid for the call.
    let retained =
        unsafe { OpenMutexW(MUTEX_ALL_ACCESS, /*binherithandle*/ 0, wide_name.as_ptr()) };
    if retained == 0 {
        return Err(std::io::Error::last_os_error()).context("retain owned test mutex");
    }
    // SAFETY: OpenMutexW returned a new valid handle owned solely by this value.
    let retained = unsafe { OwnedHandle::from_raw_handle(retained as RawHandle) };
    drop(first);

    let released_but_retained = acquire_named_read_acl_mutex(name)
        .err()
        .expect("an unowned existing object still is not a completion receipt");
    assert_eq!(
        released_but_retained
            .downcast_ref::<std::io::Error>()
            .and_then(std::io::Error::raw_os_error),
        Some(ERROR_ALREADY_EXISTS as i32)
    );
    assert_eq!(
        released_but_retained.to_string(),
        "read ACL preparation mutex already exists; current request is not ready"
    );

    drop(retained);
    let _after_last_handle_closes = acquire_named_read_acl_mutex(name)?;
    Ok(())
}
'''

sources = [(WIN, win, s.encode()), (MUTEX, mutex, mutex_new.encode()), (TEST, None, tests.encode())]
patch = []
rows = []
for logical, before, after in sources:
    target = ROOT / "candidate" / logical
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(after)
    patch.append(f"diff --git a/{logical} b/{logical}\n")
    if before is None:
        patch.append("new file mode 100644\n")
    patch.append(f"index {identity(before or b'')['blob'] if before is not None else '0'*40}..{identity(after)['blob']}" + (" 100644\n" if before is not None else "\n"))
    patch.extend(difflib.unified_diff(
        (before or b'').decode().splitlines(keepends=True),
        after.decode().splitlines(keepends=True),
        fromfile=f"a/{logical}" if before is not None else "/dev/null",
        tofile=f"b/{logical}",
    ))
    rows.append({"path": str(logical), "preimage": identity(before) if before is not None else None,
                 "postimage": identity(after), "local_preimage": str(ROOT / 'source' / logical) if before is not None else None,
                 "local_postimage": str(target)})
(ROOT / "read-readiness.patch").write_bytes(''.join(patch).encode())
(ROOT / "source-map.json").write_text(json.dumps({"base_head":"eed4d6bb61b789b19f60facc79f9e031765fa4c9", "base_tree":"ca1c4671ef6b2773280d01b5d76c6166252f5856", "files":rows}, indent=2) + '\n')
print(json.dumps({"patch":identity((ROOT / 'read-readiness.patch').read_bytes()),"files":rows},indent=2))
