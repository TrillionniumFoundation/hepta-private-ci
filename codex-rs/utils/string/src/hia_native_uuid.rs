//! ABI transport for the complete HIA UUID scanner.
//!
//! HIA owns candidate selection, ASCII hexadecimal and hyphen checks, and
//! non-overlapping advancement. This adapter copies only the returned spans.
//! The source is borrowed without a size cap. The raw ABI accepts arbitrary
//! bytes; safe Rust calls provide UTF-8, and returned slices are checked again.
//! Query writes a 64-byte header; emit appends 16-byte (start, end) rows.
//! All native errors leave the three buffers unchanged. Workspace is always
//! read-only. Allocation and each owned String remain host responsibilities.

const HEADER_BYTES: usize = 64;
const ROW_BYTES: usize = 16;

#[derive(Clone, Copy)]
#[repr(u64)]
enum Operation {
    Query = 0,
    Emit = 1,
}

#[derive(Debug, PartialEq, Eq)]
struct Plan {
    count: usize,
    required: usize,
}

unsafe extern "C" {
    fn codex_hia_uuid_find(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

fn invoke(source: &str, output: &mut [u8], operation: Operation) {
    let mut workspace = [0_u8; 32];
    workspace[..8].copy_from_slice(&1_u64.to_le_bytes());
    workspace[8..16].copy_from_slice(&(operation as u64).to_le_bytes());
    // SAFETY: all three non-overlapping buffers stay live for this synchronous
    // call, with their exact capacities. The HIA owner validates the full frame
    // and final output capacity before any write; it retains no pointers.
    let status = unsafe {
        codex_hia_uuid_find(
            source.as_ptr(),
            source.len() as u64,
            output.as_mut_ptr(),
            output.len() as u64,
            workspace.as_mut_ptr(),
            workspace.len() as u64,
        )
    };
    assert_eq!(status, 0, "HIA UUID scan failed");
}

fn decode_word(bytes: &[u8]) -> u64 {
    let mut encoded = [0_u8; 8];
    encoded.copy_from_slice(bytes);
    u64::from_le_bytes(encoded)
}

fn index(value: u64) -> usize {
    let Ok(value) = usize::try_from(value) else {
        panic!("HIA UUID offset does not fit usize");
    };
    value
}

fn read_plan(source: &str, output: &[u8], operation: Operation) -> Plan {
    let mut words = [0_u64; 8];
    for (word, encoded) in words.iter_mut().zip(output[..HEADER_BYTES].chunks_exact(8)) {
        *word = decode_word(encoded);
    }
    assert_eq!(words[0], 1, "HIA UUID revision is invalid");
    assert_eq!(words[1], operation as u64, "HIA UUID operation is invalid");
    assert_eq!(
        words[2],
        source.len() as u64,
        "HIA UUID source length differs"
    );
    assert_eq!(
        words[5], HEADER_BYTES as u64,
        "HIA UUID row offset is invalid"
    );
    assert_eq!(words[7], 0, "HIA UUID reserved word is invalid");
    let plan = Plan {
        count: index(words[3]),
        required: index(words[4]),
    };
    let required = plan
        .count
        .checked_mul(ROW_BYTES)
        .and_then(|bytes| bytes.checked_add(HEADER_BYTES));
    assert_eq!(
        required,
        Some(plan.required),
        "HIA UUID table size is invalid"
    );
    let written = match operation {
        Operation::Query => HEADER_BYTES,
        Operation::Emit => plan.required,
    };
    assert_eq!(words[6], written as u64, "HIA UUID write extent is invalid");
    assert!(written <= output.len(), "HIA UUID output exceeds capacity");
    plan
}

pub fn find_uuids(source: &str) -> Vec<String> {
    let mut header = [0_u8; HEADER_BYTES];
    invoke(source, &mut header, Operation::Query);
    let plan = read_plan(source, &header, Operation::Query);
    if plan.count == 0 {
        return Vec::new();
    }
    let mut table = vec![0_u8; plan.required];
    invoke(source, &mut table, Operation::Emit);
    assert_eq!(
        read_plan(source, &table, Operation::Emit),
        plan,
        "HIA UUID query and emit disagree"
    );
    let mut result = Vec::with_capacity(plan.count);
    let mut previous_end = 0;
    for row in table[HEADER_BYTES..].chunks_exact(ROW_BYTES) {
        let start = index(decode_word(&row[..8]));
        let end = index(decode_word(&row[8..]));
        assert!(start >= previous_end, "HIA UUID matches overlap or regress");
        assert_eq!(
            end.checked_sub(start),
            Some(36),
            "HIA UUID width is invalid"
        );
        let Some(value) = source.get(start..end) else {
            panic!("HIA UUID span is not a valid string range");
        };
        result.push(value.to_owned());
        previous_end = end;
    }
    result
}
