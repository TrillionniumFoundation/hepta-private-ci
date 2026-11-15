//! Owned storage and byte framing for the HIA SourceFile implementation.
//!
//! The native entry owns parsing, preferred endings, replacement selection,
//! logical-line identity and rendering order. Its query writes a 40-byte plan
//! header; materialization repeats validation before writing that header and
//! 32-byte span records. Returned errors write nothing. Both calls borrow live,
//! disjoint buffers and retain no pointers. All request fields are little-endian
//! u64 values, and every successful status is zero.
//!
//! The request header is [operation, pools, lines, replacements, inserted,
//! preferred, parse_text_id, zero], followed by pool lengths, old line records,
//! replacement triples and inserted text IDs. Pool IDs 0/1/2 are LF/CRLF/CR.
//! Parsing borrows the original string as pool 3. Other operations borrow the
//! concatenated pool bytes. The HIA owner validates UTF-8 and all span boundaries.
//!
//! Stored spans always refer to one owned text backing. After replacement,
//! copying the native-selected spans compacts that backing and releases deleted
//! text. Embedded CR/LF in inserted text remains inside its native logical row.

use std::borrow::Cow;

use crate::text_file::Replacement;

const HEADER_SIZE: usize = 40;
const RECORD_SIZE: usize = 32;
const LITERALS: &str = "\n\r\n\r";

#[derive(Clone, Copy)]
#[repr(u64)]
enum Operation {
    Parse = 0,
    Apply = 2,
    Texts = 4,
    Contents = 6,
}

struct Line {
    start: usize,
    length: usize,
    ending: u64,
}

pub(super) struct SourceFile {
    backing: String,
    lines: Vec<Line>,
    preferred_ending: u64,
}

struct Plan {
    bytes: Vec<u8>,
    count: usize,
    logical_count: usize,
    total_bytes: usize,
    preferred: u64,
}

unsafe extern "C" {
    fn codex_hia_source_file(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_len: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

fn word(bytes: &[u8]) -> u64 {
    let mut encoded = [0_u8; 8];
    encoded.copy_from_slice(bytes);
    u64::from_le_bytes(encoded)
}

fn size(value: u64) -> usize {
    usize::try_from(value).unwrap_or_else(|_| panic!("HIA span size does not fit usize"))
}

fn push_word(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_le_bytes());
}

fn request(
    operation: Operation,
    pools: &[&str],
    lines: &[Line],
    replacements: &[Replacement],
    preferred: u64,
) -> Vec<u8> {
    let inserted = replacements
        .iter()
        .try_fold(0_usize, |count, (_, _, segment)| {
            count.checked_add(segment.len())
        })
        .unwrap_or_else(|| panic!("HIA inserted frame length overflow"));
    let parse_text_id = match operation {
        Operation::Parse => 3,
        Operation::Apply | Operation::Texts | Operation::Contents => 0,
    };
    let mut bytes = Vec::new();
    for value in [
        operation as u64,
        pools.len() as u64,
        lines.len() as u64,
        replacements.len() as u64,
        inserted as u64,
        preferred,
        parse_text_id,
        0,
    ] {
        push_word(&mut bytes, value);
    }
    for text in pools {
        push_word(&mut bytes, text.len() as u64);
    }
    for line in lines {
        for value in [3, line.start as u64, line.length as u64, line.ending] {
            push_word(&mut bytes, value);
        }
    }
    for (start, old_length, segment) in replacements {
        for value in [*start as u64, *old_length as u64, segment.len() as u64] {
            push_word(&mut bytes, value);
        }
    }
    for id in 4..pools.len() {
        push_word(&mut bytes, id as u64);
    }
    bytes
}

fn invoke(source: &str, output: &mut [u8], request: &mut [u8]) {
    // SAFETY: these three disjoint allocations remain live and immutably
    // borrowed where required. HIA validates the declared lengths and all
    // contents before writing any result and retains no pointer after return.
    let status = unsafe {
        codex_hia_source_file(
            source.as_ptr(),
            source.len() as u64,
            output.as_mut_ptr(),
            output.len() as u64,
            request.as_mut_ptr(),
            request.len() as u64,
        )
    };
    assert_eq!(status, 0, "HIA SourceFile request failed");
}

fn plan(source: &str, operation: Operation, mut request: Vec<u8>) -> Plan {
    let mut header = [0_u8; HEADER_SIZE];
    invoke(source, &mut header, &mut request);
    let needed = size(word(&header[..8]));
    let count = size(word(&header[8..16]));
    let expected = count
        .checked_mul(RECORD_SIZE)
        .and_then(|records| records.checked_add(HEADER_SIZE))
        .unwrap_or_else(|| panic!("HIA plan length overflow"));
    assert_eq!(needed, expected, "HIA plan framing is invalid");
    let mut bytes = vec![0_u8; needed];
    request[..8].copy_from_slice(&(operation as u64 + 1).to_le_bytes());
    invoke(source, &mut bytes, &mut request);
    assert_eq!(
        &bytes[..HEADER_SIZE],
        &header,
        "HIA plan changed after query"
    );
    let preferred = word(&header[32..40]);
    assert!(
        (1..=3).contains(&preferred),
        "HIA preferred ending is invalid"
    );
    Plan {
        bytes,
        count,
        logical_count: size(word(&header[16..24])),
        total_bytes: size(word(&header[24..32])),
        preferred,
    }
}

impl Plan {
    fn records(&self) -> impl Iterator<Item = [u64; 4]> + '_ {
        self.bytes[HEADER_SIZE..]
            .chunks_exact(RECORD_SIZE)
            .map(|record| {
                let mut fields = [0_u64; 4];
                for (field, encoded) in fields.iter_mut().zip(record.chunks_exact(8)) {
                    *field = word(encoded);
                }
                fields
            })
    }
}

fn span<'a>(pools: &[&'a str], row: [u64; 4]) -> &'a str {
    let text = pools
        .get(size(row[0]))
        .unwrap_or_else(|| panic!("HIA text ID is outside the pool"));
    let start = size(row[1]);
    let end = start
        .checked_add(size(row[2]))
        .unwrap_or_else(|| panic!("HIA span range overflow"));
    text.get(start..end)
        .unwrap_or_else(|| panic!("HIA text span is outside UTF-8 boundaries"))
}

impl SourceFile {
    pub(super) fn parse(contents: &str) -> Self {
        let pools = ["\n", "\r\n", "\r", contents];
        let query = request(Operation::Parse, &pools, &[], &[], /*preferred*/ 0);
        let plan = plan(contents, Operation::Parse, query);
        assert_eq!(
            plan.count, plan.logical_count,
            "HIA parsed line count differs"
        );
        let mut lines = Vec::with_capacity(plan.count);
        for row in plan.records() {
            assert_eq!(row[0], 3, "HIA parse selected another pool");
            assert!(row[3] <= 3, "HIA line ending is invalid");
            let text = span(&pools, row);
            lines.push(Line {
                start: size(row[1]),
                length: text.len(),
                ending: row[3],
            });
        }
        assert_eq!(
            plan.total_bytes,
            contents.len(),
            "HIA parse byte total differs"
        );
        let mut backing = String::from(LITERALS);
        backing.push_str(contents);
        Self {
            backing,
            lines,
            preferred_ending: plan.preferred,
        }
    }

    pub(super) fn line_texts(&self) -> Vec<String> {
        let pools = ["\n", "\r\n", "\r", &self.backing[LITERALS.len()..]];
        let query = request(
            Operation::Texts,
            &pools,
            &self.lines,
            &[],
            self.preferred_ending,
        );
        let plan = plan(&self.backing, Operation::Texts, query);
        assert_eq!(plan.count, plan.logical_count, "HIA text count differs");
        let mut texts = Vec::with_capacity(plan.count);
        for row in plan.records() {
            assert_eq!(row[3], 0, "HIA text projection tag is invalid");
            texts.push(span(&pools, row).to_owned());
        }
        texts
    }

    pub(super) fn apply_replacements(&mut self, replacements: &[Replacement]) {
        let mut pools = vec!["\n", "\r\n", "\r", &self.backing[LITERALS.len()..]];
        for (_, _, segment) in replacements {
            pools.extend(segment.iter().map(String::as_str));
        }
        let mut payload = Cow::Borrowed(self.backing.as_str());
        for text in &pools[4..] {
            payload.to_mut().push_str(text);
        }
        let query = request(
            Operation::Apply,
            &pools,
            &self.lines,
            replacements,
            self.preferred_ending,
        );
        let plan = plan(&payload, Operation::Apply, query);
        assert_eq!(
            plan.count, plan.logical_count,
            "HIA replacement line count differs"
        );
        assert_eq!(
            plan.preferred, self.preferred_ending,
            "HIA preferred style changed"
        );
        let mut backing = String::from(LITERALS);
        let mut lines = Vec::with_capacity(plan.count);
        for row in plan.records() {
            assert!(row[0] >= 3, "HIA replacement selected a literal pool");
            assert!(
                (1..=3).contains(&row[3]),
                "HIA replacement ending is invalid"
            );
            let text = span(&pools, row);
            lines.push(Line {
                start: backing.len() - LITERALS.len(),
                length: text.len(),
                ending: row[3],
            });
            backing.push_str(text);
        }
        self.backing = backing;
        self.lines = lines;
    }

    pub(super) fn into_contents(self) -> String {
        let pools = ["\n", "\r\n", "\r", &self.backing[LITERALS.len()..]];
        let query = request(
            Operation::Contents,
            &pools,
            &self.lines,
            &[],
            self.preferred_ending,
        );
        let plan = plan(&self.backing, Operation::Contents, query);
        assert_eq!(
            plan.logical_count,
            self.lines.len(),
            "HIA rendering line count differs"
        );
        let mut contents = String::with_capacity(plan.total_bytes);
        for row in plan.records() {
            assert_eq!(row[3], 0, "HIA rendering tag is invalid");
            contents.push_str(span(&pools, row));
        }
        assert_eq!(
            contents.len(),
            plan.total_bytes,
            "HIA rendering byte total differs"
        );
        contents
    }
}
