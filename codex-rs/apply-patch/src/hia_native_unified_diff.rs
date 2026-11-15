//! Storage and ABI adapter for the HIA unified-diff owner.
//!
//! This isolated draft accepts an explicit, already-admitted arithmetic policy.
//! Production wiring must obtain it from the bound defining-crate and owner
//! compiler receipts; this module neither infers flags nor calls similar.

const WORD_BYTES: usize = 8;
const HEADER_BYTES: usize = 16 * WORD_BYTES;
const DESCRIPTOR_BYTES: usize = 8 * WORD_BYTES;
const FRAGMENT_BYTES: usize = 4 * WORD_BYTES;
const ABI_REVISION: usize = 2;
const INSPECT_TRUSTED: u64 = 2;
const PLAN_TRUSTED: u64 = 3;

unsafe extern "C" {
    fn codex_hia_unified_diff(
        source: *const u8,
        source_len: usize,
        output: *mut u8,
        output_len: usize,
        workspace: *mut u8,
        workspace_len: usize,
    ) -> u32;
}

fn invalid_native(message: &str) -> ! {
    panic!("HIA unified-diff ABI violation: {message}")
}

fn checked_add(left: usize, right: usize) -> usize {
    match left.checked_add(right) {
        Some(value) => value,
        None => invalid_native("byte extent overflow"),
    }
}

fn checked_mul(left: usize, right: usize) -> usize {
    match left.checked_mul(right) {
        Some(value) => value,
        None => invalid_native("table extent overflow"),
    }
}

fn word(bytes: &[u8], offset: usize) -> usize {
    let end = checked_add(offset, WORD_BYTES);
    let Some(slice) = bytes.get(offset..end) else {
        invalid_native("truncated metadata word")
    };
    let Ok(array) = <[u8; WORD_BYTES]>::try_from(slice) else {
        invalid_native("invalid metadata word width")
    };
    let Ok(value) = usize::try_from(u64::from_le_bytes(array)) else {
        invalid_native("metadata does not fit host usize")
    };
    value
}

fn header(bytes: &[u8]) -> [usize; 16] {
    std::array::from_fn(|index| word(bytes, index * WORD_BYTES))
}

fn descriptor(
    operation: u64,
    old_bytes: usize,
    new_bytes: usize,
    context: usize,
    arithmetic_policy: u64,
) -> [u8; DESCRIPTOR_BYTES] {
    let values = [
        operation,
        old_bytes as u64,
        new_bytes as u64,
        context as u64,
        arithmetic_policy,
        0,
        0,
        0,
    ];
    let mut result = [0; DESCRIPTOR_BYTES];
    for (dest, value) in result.chunks_exact_mut(WORD_BYTES).zip(values) {
        dest.copy_from_slice(&value.to_le_bytes());
    }
    result
}

fn invoke(source: &str, output: &mut [u8], workspace: &mut [u8]) {
    // All three allocations are disjoint and remain live for this call. Both
    // source halves were copied from valid &str, satisfying the trusted entry.
    let status = unsafe {
        codex_hia_unified_diff(
            source.as_ptr(),
            source.len(),
            output.as_mut_ptr(),
            output.len(),
            workspace.as_mut_ptr(),
            workspace.len(),
        )
    };
    assert_eq!(status, 0, "HIA unified-diff rejected its adapter frame");
}

fn semantic_panic(code: usize, operand_a: usize, operand_b: usize) -> ! {
    match code {
        1 => panic!("attempt to multiply with overflow"),
        2 | 4 => panic!("attempt to add with overflow"),
        3 => panic!("index out of bounds: the len is {operand_a} but the index is {operand_b}"),
        5 => panic!("attempt to subtract with overflow"),
        6 => panic!("capacity overflow"),
        _ => invalid_native("unknown semantic error"),
    }
}

/// Copies native-selected source and literal fragments into the returned String.
///
/// The arithmetic policy is supplied by compiler-provenance admission. It is not
/// inferred from this caller's debug assertions or from Cargo's profile alone.
pub(crate) fn unified_diff(old: &str, new: &str, context: usize, arithmetic_policy: u64) -> String {
    let mut source = String::with_capacity(checked_add(old.len(), new.len()));
    source.push_str(old);
    source.push_str(new);

    let mut request = descriptor(
        INSPECT_TRUSTED,
        old.len(),
        new.len(),
        context,
        arithmetic_policy,
    );
    let mut query_bytes = [0; HEADER_BYTES];
    invoke(&source, &mut query_bytes, &mut request);
    let query = header(&query_bytes);
    let Ok(policy) = usize::try_from(arithmetic_policy) else {
        invalid_native("arithmetic policy does not fit host usize")
    };
    if query[0] != ABI_REVISION
        || query[1] < HEADER_BYTES
        || query[2] < DESCRIPTOR_BYTES
        || query[3..9] != [0; 6]
        || query[9] > old.len()
        || query[10] > new.len()
        || query[11..14] != [0; 3]
        || query[14] != policy
        || query[15] != 0
    {
        invalid_native("invalid inspect header");
    }

    let mut output = vec![0; query[1]];
    let mut workspace = vec![0; query[2]];
    workspace[..DESCRIPTOR_BYTES].copy_from_slice(&descriptor(
        PLAN_TRUSTED,
        old.len(),
        new.len(),
        context,
        arithmetic_policy,
    ));
    invoke(&source, &mut output, &mut workspace);
    let plan = header(&output);
    if plan[0..3] != query[0..3]
        || plan[9..11] != query[9..11]
        || plan[14..16] != query[14..16]
        || plan[3] < HEADER_BYTES
        || plan[3] > output.len()
    {
        invalid_native("plan identity or extent differs from inspect");
    }
    if plan[11] != 0 {
        if plan[3] != HEADER_BYTES || plan[4..9] != [0; 5] {
            invalid_native("semantic error contains a partial result");
        }
        semantic_panic(plan[11], plan[12], plan[13]);
    }
    if plan[12..14] != [0; 2]
        || plan[6] != HEADER_BYTES
        || plan[7] != checked_add(HEADER_BYTES, checked_mul(plan[5], FRAGMENT_BYTES))
        || plan[3] != checked_add(plan[7], plan[8])
    {
        invalid_native("invalid fragment table or literal pool");
    }
    let Some(literal_bytes) = output.get(plan[7]..plan[3]) else {
        invalid_native("literal pool exceeds output")
    };
    let Ok(literals) = std::str::from_utf8(literal_bytes) else {
        invalid_native("literal pool is not UTF-8")
    };
    let mut result = String::with_capacity(plan[4]);
    for index in 0..plan[5] {
        let row = checked_add(HEADER_BYTES, checked_mul(index, FRAGMENT_BYTES));
        let kind = word(&output, row);
        let offset = word(&output, checked_add(row, WORD_BYTES));
        let length = word(&output, checked_add(row, 2 * WORD_BYTES));
        if word(&output, checked_add(row, 3 * WORD_BYTES)) != 0 {
            invalid_native("nonzero fragment reserved word");
        }
        let pool = match kind {
            0 => source.as_str(),
            1 => literals,
            _ => invalid_native("unknown fragment kind"),
        };
        let Some(fragment) = pool.get(offset..checked_add(offset, length)) else {
            invalid_native("fragment is outside its UTF-8 pool")
        };
        if checked_add(result.len(), fragment.len()) > plan[4] {
            invalid_native("fragment bytes exceed the claimed result size");
        }
        result.push_str(fragment);
    }
    if result.len() != plan[4] {
        invalid_native("fragment bytes do not fill the claimed result size");
    }
    result
}
