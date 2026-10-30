//! Child-local observations for the failing PowerShell Ctrl-C integration test.
//!
//! These probes do not change the parent process's control-handler state and do
//! not replace the PowerShell assertion. "Preserve" means no reset after Python
//! starts; CPython or its runtime may already have changed inherited state.

use super::collect_output_until_exit;
use super::combine_spawned_output;
use super::wait_for_output_contains;
use super::windows_python_fixture::find_native_python;
use crate::TerminalSize;
use crate::spawn_pty_process;
use std::collections::HashMap;
use std::path::Path;

const READY: &str = "__CODEX_CTRL_READY__";
const RESULT: &str = "__CODEX_CTRL_RESULT__";
const CHILD: &str = r#"
import ctypes, json, msvcrt, os, sys
from ctypes import wintypes
assert sys.platform == 'win32' and os.name == 'nt'
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel.GetConsoleMode.restype = wintypes.BOOL
kernel.SetConsoleCtrlHandler.argtypes = [ctypes.c_void_p, wintypes.BOOL]
kernel.SetConsoleCtrlHandler.restype = wintypes.BOOL
kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
kernel.CreateEventW.restype = wintypes.HANDLE
kernel.SetEvent.argtypes = [wintypes.HANDLE]
kernel.SetEvent.restype = wintypes.BOOL
kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel.WaitForSingleObject.restype = wintypes.DWORD
HANDLER = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
route = sys.argv[1]
assert route in ('preserve', 'reset')
event = None
handler = None
received = []
callback_errors = []
exit_code = 1
try:
    mode = wintypes.DWORD()
    mode_ok = bool(kernel.GetConsoleMode(msvcrt.get_osfhandle(sys.stdin.fileno()), ctypes.byref(mode)))
    mode_error = None if mode_ok else ctypes.get_last_error()
    reset_ok = None
    reset_error = None
    if route == 'reset':
        reset_ok = bool(kernel.SetConsoleCtrlHandler(None, False))
        reset_error = None if reset_ok else ctypes.get_last_error()
    event = kernel.CreateEventW(None, True, False, None)
    if not event:
        raise ctypes.WinError(ctypes.get_last_error())
    @HANDLER
    def handler(code):
        if code != 0:
            return False
        received.append(int(code))
        if not kernel.SetEvent(event):
            callback_errors.append(ctypes.get_last_error())
        return True
    if not kernel.SetConsoleCtrlHandler(ctypes.cast(handler, ctypes.c_void_p), True):
        raise ctypes.WinError(ctypes.get_last_error())
    print('__CODEX_CTRL_READY__' + json.dumps({
        'route': route, 'executable': sys.executable, 'version': sys.version,
        'initial_mode_ok': mode_ok, 'initial_mode': mode.value if mode_ok else None,
        'initial_mode_error': mode_error, 'reset_succeeded': reset_ok,
        'reset_error': reset_error,
    }), flush=True)
    wait_result = int(kernel.WaitForSingleObject(event, 1500))
    wait_error = ctypes.get_last_error() if wait_result == 0xffffffff else None
    wait_status = {0: 'signaled', 258: 'timeout', 0xffffffff: 'failed'}.get(wait_result, 'unexpected')
    print('__CODEX_CTRL_RESULT__' + json.dumps({
        'route': route, 'observation_ms': 1500, 'wait_result': wait_result,
        'wait_status': wait_status, 'wait_error': wait_error,
        'received_control_events': received, 'callback_errors': callback_errors,
    }), flush=True)
    exit_code = 0 if wait_result in (0, 258) else 1
except BaseException as error:
    print('__CODEX_CTRL_ERROR__' + repr(error), flush=True)
finally:
    # Keep the callback and its event alive until this private child exits.
    # Removing a handler does not join callbacks already in progress. Closing
    # the event here could race such a callback, so process exit owns cleanup.
    # Bypass interpreter teardown while a Windows handler thread may enter it.
    os._exit(exit_code)
"#;

pub(super) async fn collect_ctrl_c_diagnostics(env: &HashMap<String, String>) -> String {
    let python = match find_native_python() {
        Ok(python) => python,
        Err(error) => return format!("Ctrl-C child diagnostics unavailable: {error}"),
    };
    let mut observations = Vec::new();
    for route in ["preserve", "reset"] {
        let observation = match observe_ctrl_c(&python, route, env).await {
            Ok(transcript) => format!("route={route}; transcript={transcript:?}"),
            Err(error) => format!("route={route}; diagnostic error={error}"),
        };
        observations.push(observation);
    }
    format!(
        "Child-local Ctrl-C observations (not a PowerShell verdict): {}",
        observations.join("; ")
    )
}

async fn observe_ctrl_c(
    python: &str,
    route: &str,
    env: &HashMap<String, String>,
) -> anyhow::Result<String> {
    let args = ["-I", "-S", "-u", "-c", CHILD, route].map(str::to_owned);
    let spawned = spawn_pty_process(
        python,
        &args,
        Path::new("."),
        env,
        /*arg0*/ &None,
        TerminalSize::default(),
        &[],
    )
    .await?;
    let (session, mut output_rx, exit_rx) = combine_spawned_output(spawned);
    let mut transcript =
        wait_for_output_contains(&mut output_rx, READY, /*timeout_ms*/ 5_000).await?;
    session.writer_sender().send(vec![0x03]).await?;
    let result = wait_for_output_contains(&mut output_rx, RESULT, /*timeout_ms*/ 5_000)
        .await
        .map_err(|error| {
            anyhow::anyhow!(
                "{error}; readiness transcript: {:?}",
                String::from_utf8_lossy(&transcript)
            )
        })?;
    transcript.extend_from_slice(&result);
    let (tail, exit_code) =
        collect_output_until_exit(output_rx, exit_rx, /*timeout_ms*/ 5_000).await;
    transcript.extend_from_slice(&tail);
    let transcript = String::from_utf8_lossy(&transcript).into_owned();
    anyhow::ensure!(
        exit_code == 0,
        "Ctrl-C diagnostic child exit_code={exit_code}; transcript={transcript:?}"
    );
    Ok(transcript)
}
