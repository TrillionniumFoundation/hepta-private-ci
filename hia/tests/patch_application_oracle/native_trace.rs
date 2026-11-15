//! Forward the real linked symbol unchanged; retain its actual transition frames.
#[cfg(native_application)]
use std::sync::Mutex;

#[cfg(native_application)]
static CALLS: Mutex<Vec<(Vec<u8>, Vec<u8>, u64)>> = Mutex::new(Vec::new());

#[cfg(native_application)]
unsafe extern "C" {
    fn __real_codex_hia_patch_application(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_len: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

#[cfg(native_application)]
#[unsafe(no_mangle)]
unsafe extern "C" fn __wrap_codex_hia_patch_application(
    source: *const u8,
    source_len: u64,
    output: *mut u8,
    output_len: u64,
    workspace: *mut u8,
    workspace_len: u64,
) -> u64 {
    let request = if source_len == 64 {
        unsafe { std::slice::from_raw_parts(source, 64) }.to_vec()
    } else {
        Vec::new()
    };
    let status = unsafe {
        __real_codex_hia_patch_application(
            source,
            source_len,
            output,
            output_len,
            workspace,
            workspace_len,
        )
    };
    let response = if output_len >= 64 {
        unsafe { std::slice::from_raw_parts(output, 64) }.to_vec()
    } else {
        Vec::new()
    };
    CALLS
        .lock()
        .unwrap_or_else(|error| error.into_inner())
        .push((request, response, status));
    status
}

pub fn emit() {
    #[cfg(native_application)]
    {
        let calls = CALLS.lock().unwrap_or_else(|error| error.into_inner());
        println!("native_calls={}", calls.len());
        for (index, (request, response, status)) in calls.iter().enumerate() {
            println!("native_{index}_request_hex={}", crate::hex(request));
            println!("native_{index}_response_hex={}", crate::hex(response));
            println!("native_{index}_status={status}");
        }
    }
    #[cfg(not(native_application))]
    println!("native_calls=0");
}
