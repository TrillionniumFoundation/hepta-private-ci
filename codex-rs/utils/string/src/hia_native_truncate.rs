//! Borrowed-input ABI adapter for the HIA truncation and token-budget owner.
//!
//! `source` is the complete UTF-8 input, without copying or a framing size cap.
//! Workspace contains two little-endian u64 words: operation and budget. The
//! operations are characters/byte budget (0), tokens/token budget (1), tokens to
//! bytes (2), and bytes to tokens (3). Scalar operations require empty source.
//! Trusted characters (4) and tokens (5) require valid UTF-8; only these operations
//! are used for Rust `&str`. They skip redundant validation: token plans inspect
//! at most four bytes at either boundary, and character plans count only the
//! removed byte range. The strict operations 0 and 1 validate the entire input.
//! The 40-byte result contains prefix end, suffix start, removed marker units,
//! original approximate token count, and marker kind (unchanged=0/chars=1/tokens=2).
//! Scalar operations place their value in the first word and zero the rest.
//!
//! Status is 40 on success, 0xffff_fffe for insufficient output or workspace,
//! 0xffff_ffff for an invalid operation or nonempty scalar input, and
//! 0xffff_fffd for malformed UTF-8. Capacity checks precede operation checks,
//! which precede UTF-8 validation. Errors never write output or workspace;
//! workspace is read-only on success as well. The native call retains no data.

const OUTPUT_SIZE: usize = 40;
const REQUEST_SIZE: usize = 16;

#[derive(Clone, Copy)]
#[repr(u64)]
enum Operation {
    Characters = 4,
    Tokens = 5,
    BytesForTokens = 2,
    TokensForBytes = 3,
}

unsafe extern "C" {
    fn codex_hia_truncate(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

fn invoke(source: &str, operation: Operation, budget: usize) -> [u64; 5] {
    let mut request = [0_u8; REQUEST_SIZE];
    request[..8].copy_from_slice(&(operation as u64).to_le_bytes());
    request[8..].copy_from_slice(&(budget as u64).to_le_bytes());
    let mut output = [0_u8; OUTPUT_SIZE];
    // SAFETY: the borrowed UTF-8 input and separate stack buffers remain live
    // for this synchronous call. Their exact lengths are provided. The HIA
    // owner checks capacities before writes. The trusted operations rely on
    // Rust's valid UTF-8 invariant; the strict ABI remains separately testable.
    let status = unsafe {
        codex_hia_truncate(
            source.as_ptr(),
            source.len() as u64,
            output.as_mut_ptr(),
            OUTPUT_SIZE as u64,
            request.as_mut_ptr(),
            REQUEST_SIZE as u64,
        )
    };
    assert_eq!(status, OUTPUT_SIZE as u64, "HIA truncation call failed");
    let mut words = [0_u64; 5];
    for (word, bytes) in words.iter_mut().zip(output.chunks_exact(8)) {
        let mut encoded = [0_u8; 8];
        encoded.copy_from_slice(bytes);
        *word = u64::from_le_bytes(encoded);
    }
    words
}

fn truncate(source: &str, operation: Operation, budget: usize) -> (String, Option<u64>) {
    let [prefix, suffix, removed_units, original_tokens, kind] = invoke(source, operation, budget);
    if kind == 0 {
        assert_eq!(
            [prefix, suffix, removed_units],
            [source.len() as u64, source.len() as u64, 0],
            "HIA unchanged truncation plan is invalid"
        );
        return (source.to_string(), None);
    }
    let expected_kind = match operation {
        Operation::Characters => 1,
        Operation::Tokens => 2,
        Operation::BytesForTokens | Operation::TokensForBytes => {
            panic!("HIA scalar operation cannot render a truncation marker")
        }
    };
    assert_eq!(kind, expected_kind, "HIA marker kind is invalid");
    let Ok(prefix) = usize::try_from(prefix) else {
        panic!("HIA prefix offset does not fit usize");
    };
    let Ok(suffix) = usize::try_from(suffix) else {
        panic!("HIA suffix offset does not fit usize");
    };
    assert!(prefix <= suffix, "HIA truncation plan overlaps");
    let Some(before) = source.get(..prefix) else {
        panic!("HIA prefix is not a boundary");
    };
    let Some(after) = source.get(suffix..) else {
        panic!("HIA suffix is not a boundary");
    };
    let marker = match operation {
        Operation::Characters => format!("…{removed_units} chars truncated…"),
        Operation::Tokens => format!("…{removed_units} tokens truncated…"),
        Operation::BytesForTokens | Operation::TokensForBytes => {
            panic!("HIA scalar operation cannot render a truncation marker")
        }
    };
    let mut result = String::with_capacity(before.len() + marker.len() + after.len() + 1);
    result.push_str(before);
    result.push_str(&marker);
    result.push_str(after);
    (result, Some(original_tokens))
}

pub(super) fn truncate_middle_chars(source: &str, max_bytes: usize) -> String {
    truncate(source, Operation::Characters, max_bytes).0
}

pub(super) fn truncate_middle_with_token_budget(
    source: &str,
    max_tokens: usize,
) -> (String, Option<u64>) {
    let (result, original_tokens) = truncate(source, Operation::Tokens, max_tokens);
    // Only a marker plan needs the original public API's equality check. An
    // unchanged HIA plan already guarantees None without comparing the copy.
    // Marker plans retain the case where input already spells the rendered text.
    let count = original_tokens.filter(|_| result != source);
    (result, count)
}

pub(super) fn approx_bytes_for_tokens(tokens: usize) -> usize {
    let [bytes, _, _, _, _] = invoke("", Operation::BytesForTokens, tokens);
    match usize::try_from(bytes) {
        Ok(bytes) => bytes,
        Err(_) => panic!("HIA byte count does not fit usize"),
    }
}

pub(super) fn approx_tokens_from_byte_count(bytes: usize) -> u64 {
    let [tokens, _, _, _, _] = invoke("", Operation::TokensForBytes, bytes);
    tokens
}
