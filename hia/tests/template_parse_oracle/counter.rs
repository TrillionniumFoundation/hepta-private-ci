//! Observe actual calls while forwarding all six arguments unchanged.

#[cfg(native_observer)]
mod active {
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;
    use std::sync::Mutex;

    static STAGE: AtomicU64 = AtomicU64::new(0);
    static CALLS: Mutex<Vec<[u64; 17]>> = Mutex::new(Vec::new());

    unsafe extern "C" {
        fn __real_codex_hia_template_parse(
            source: *const u8,
            source_len: u64,
            output: *mut u8,
            output_capacity: u64,
            workspace: *mut u8,
            workspace_len: u64,
        ) -> u64;
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
        assert_eq!(workspace_len, 32);
        assert!(output_capacity >= 64);
        let mut row = [0_u64; 17];
        row[0] = STAGE.load(Ordering::Relaxed);
        row[1] = source_len;
        row[2] = output_capacity;
        row[3] = workspace_len;
        let request = unsafe { std::slice::from_raw_parts(workspace, 32) };
        for (word, bytes) in row[5..9].iter_mut().zip(request.chunks_exact(8)) {
            let mut data = [0_u8; 8];
            data.copy_from_slice(bytes);
            *word = u64::from_le_bytes(data);
        }
        // No argument is replaced, advanced, resized, or synthesized.
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
        row[4] = status;
        let header = unsafe { std::slice::from_raw_parts(output, 64) };
        for (word, bytes) in row[9..].iter_mut().zip(header.chunks_exact(8)) {
            let mut data = [0_u8; 8];
            data.copy_from_slice(bytes);
            *word = u64::from_le_bytes(data);
        }
        CALLS
            .lock()
            .unwrap_or_else(|error| error.into_inner())
            .push(row);
        status
    }

    pub fn stage(value: u64) {
        STAGE.store(value, Ordering::Relaxed);
    }

    pub fn take() -> Vec<[u64; 17]> {
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
pub fn take() -> Vec<[u64; 17]> {
    Vec::new()
}
