//! Append typed native-call observations while forwarding all six arguments.

#[cfg(native_observer)]
mod active {
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;
    use std::sync::Mutex;

    // [symbol, stage, source_len, output_capacity, workspace_len, status,
    //  request[4], response[10]]. Parse's last two response words are zero.
    static STAGE: AtomicU64 = AtomicU64::new(0);
    static CALLS: Mutex<Vec<[u64; 20]>> = Mutex::new(Vec::new());

    unsafe extern "C" {
        fn __real_codex_hia_template_parse(
            source: *const u8,
            source_len: u64,
            output: *mut u8,
            output_capacity: u64,
            workspace: *mut u8,
            workspace_len: u64,
        ) -> u64;
        fn __real_codex_hia_template_render(
            source: *const u8,
            source_len: u64,
            output: *mut u8,
            output_capacity: u64,
            workspace: *mut u8,
            workspace_len: u64,
        ) -> u64;
    }

    unsafe fn before(
        symbol: u64,
        source_len: u64,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> [u64; 20] {
        assert_eq!(workspace_len, 32);
        assert!(output_capacity >= if symbol == 1 { 64 } else { 80 });
        let mut row = [0_u64; 20];
        row[..5].copy_from_slice(&[
            symbol,
            STAGE.load(Ordering::Relaxed),
            source_len,
            output_capacity,
            workspace_len,
        ]);
        let request = unsafe { std::slice::from_raw_parts(workspace, 32) };
        for (word, bytes) in row[6..10].iter_mut().zip(request.chunks_exact(8)) {
            let mut data = [0_u8; 8];
            data.copy_from_slice(bytes);
            *word = u64::from_le_bytes(data);
        }
        row
    }

    unsafe fn after(mut row: [u64; 20], status: u64, output: *mut u8) {
        row[5] = status;
        if status == 0 {
            let size = if row[0] == 1 { 64 } else { 80 };
            let header = unsafe { std::slice::from_raw_parts(output, size) };
            for (word, bytes) in row[10..].iter_mut().zip(header.chunks_exact(8)) {
                let mut data = [0_u8; 8];
                data.copy_from_slice(bytes);
                *word = u64::from_le_bytes(data);
            }
        }
        CALLS
            .lock()
            .unwrap_or_else(|error| error.into_inner())
            .push(row);
    }

    #[unsafe(no_mangle)]
    unsafe extern "C" fn __wrap_codex_hia_template_parse(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64 {
        let row = unsafe { before(1, source_len, output_capacity, workspace, workspace_len) };
        let status = unsafe {
            __real_codex_hia_template_parse(
                source,
                source_len,
                output,
                output_capacity,
                workspace,
                workspace_len,
            )
        };
        unsafe { after(row, status, output) };
        status
    }

    #[unsafe(no_mangle)]
    unsafe extern "C" fn __wrap_codex_hia_template_render(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64 {
        let row = unsafe { before(2, source_len, output_capacity, workspace, workspace_len) };
        let status = unsafe {
            __real_codex_hia_template_render(
                source,
                source_len,
                output,
                output_capacity,
                workspace,
                workspace_len,
            )
        };
        unsafe { after(row, status, output) };
        status
    }

    pub fn stage(value: u64) {
        STAGE.store(value, Ordering::Relaxed);
    }

    pub fn take() -> Vec<[u64; 20]> {
        std::mem::take(&mut *CALLS.lock().unwrap_or_else(|error| error.into_inner()))
    }
}

#[cfg(native_observer)]
pub use active::stage;
#[cfg(native_observer)]
pub use active::take;

#[cfg(not(native_observer))]
pub fn stage(_value: u64) {}

#[cfg(not(native_observer))]
pub fn take() -> Vec<[u64; 20]> {
    Vec::new()
}
