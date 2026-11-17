//! Bounded transport for the native environment-display state machines.

pub(super) const CHUNK_BYTES: usize = 4096;
const WORD_BYTES: usize = 8;
const MAX_SOURCE_BYTES: usize = 8400;
const MAX_RESULT_BYTES: usize = 4162;

pub(super) type NativeResult<T> = Result<T, &'static str>;

#[derive(Clone, Copy)]
#[repr(u64)]
pub(super) enum Operation {
    SortInit = 0,
    SortResume = 1,
    MaskFragment = 2,
    JoinInit = 3,
    JoinFragment = 4,
}

unsafe extern "C" {
    fn codex_hia_format_env_display(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

pub(super) fn call(
    operation: Operation,
    state: &[u64],
    extra: &[u64],
    payloads: &[&[u8]],
) -> NativeResult<Vec<u8>> {
    let words = state
        .len()
        .checked_add(extra.len())
        .and_then(|length| length.checked_add(/*rhs*/ 2))
        .ok_or("request word count overflow")?;
    let mut size = words
        .checked_mul(WORD_BYTES)
        .ok_or("request header length overflow")?;
    for payload in payloads {
        size = size
            .checked_add(payload.len())
            .ok_or("request payload length overflow")?;
    }
    if size > MAX_SOURCE_BYTES {
        return Err("request exceeds the bounded transport frame");
    }
    let mut source = Vec::with_capacity(size);
    for word in [1, operation as u64]
        .into_iter()
        .chain(state.iter().copied())
        .chain(extra.iter().copied())
    {
        source.extend_from_slice(&word.to_le_bytes());
    }
    for payload in payloads {
        source.extend_from_slice(payload);
    }
    let mut output = [0_u8; MAX_RESULT_BYTES];
    let mut workspace = [];
    // SAFETY: these separate live buffers cover the advertised ranges during
    // this synchronous call. The checked native entry retains no pointers;
    // its state is returned as bytes and the workspace has no contents.
    let status = unsafe {
        codex_hia_format_env_display(
            source.as_ptr(),
            source.len() as u64,
            output.as_mut_ptr(),
            output.len() as u64,
            workspace.as_mut_ptr(),
            workspace.len() as u64,
        )
    };
    if status >> 32 != 0 {
        return Err("native wrapper rejected the request");
    }
    match status as u32 {
        u32::MAX => return Err("native frame or state is invalid"),
        value if value == u32::MAX - 1 => return Err("native output capacity is insufficient"),
        value if value == u32::MAX - 2 => return Err("native result length overflow"),
        _ => {}
    }
    let written = count(status)?;
    if written > output.len() {
        return Err("native result exceeds its output buffer");
    }
    Ok(output[..written].to_vec())
}

pub(super) fn decode<const N: usize>(bytes: &[u8]) -> NativeResult<([u64; N], &[u8])> {
    let header = N.checked_mul(WORD_BYTES).ok_or("result header overflow")?;
    if bytes.len() < header {
        return Err("native result header is incomplete");
    }
    let mut words = [0_u64; N];
    for (word, chunk) in words
        .iter_mut()
        .zip(bytes[..header].chunks_exact(WORD_BYTES))
    {
        let mut encoded = [0_u8; WORD_BYTES];
        encoded.copy_from_slice(chunk);
        *word = u64::from_le_bytes(encoded);
    }
    Ok((words, &bytes[header..]))
}

pub(super) fn count(value: u64) -> NativeResult<usize> {
    usize::try_from(value).map_err(|_| "native count does not fit usize")
}
