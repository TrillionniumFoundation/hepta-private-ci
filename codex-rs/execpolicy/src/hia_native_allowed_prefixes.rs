//! Checked transport for HIA's allowed-prefix rendering, ordering and deduplication.
//!
//! Visit each dynamic rule once in the owner's iteration order. HIA admits an
//! Allow decision before Rust reads that prefix's pattern. HIA then renders the
//! raw tokens and sorts the rendered vectors; Rust only constructs owned output.

use crate::Decision;
use crate::PatternToken;
use crate::PrefixRule;
use crate::RuleRef;
use multimap::MultiMap;

unsafe extern "C" {
    fn codex_hia_allowed_prefixes(
        source: *const u8,
        source_length: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_length: u64,
    ) -> u64;
}

struct Frame {
    stack: [u8; 512],
    heap: Vec<u8>,
    length: usize,
}

impl Frame {
    fn append(&mut self, bytes: &[u8]) {
        let end = self
            .length
            .checked_add(bytes.len())
            .unwrap_or_else(|| panic!("HIA allowed-prefix frame length overflow"));
        if end <= self.stack.len() {
            self.stack[self.length..end].copy_from_slice(bytes);
        } else {
            if self.heap.is_empty() {
                self.heap.try_reserve_exact(end).unwrap_or_else(|error| {
                    panic!("HIA allowed-prefix frame allocation failed: {error}")
                });
                self.heap.extend_from_slice(&self.stack[..self.length]);
            } else {
                self.heap
                    .try_reserve(end - self.heap.len())
                    .unwrap_or_else(|error| {
                        panic!("HIA allowed-prefix frame allocation failed: {error}")
                    });
            }
            self.heap.extend_from_slice(bytes);
        }
        self.length = end;
    }

    fn word(&mut self, value: usize) {
        self.append(&(value as u64).to_le_bytes());
    }

    fn bytes(&mut self) -> &mut [u8] {
        if self.heap.is_empty() {
            &mut self.stack[..self.length]
        } else {
            &mut self.heap
        }
    }
}

pub(crate) fn collect(rules_by_program: &MultiMap<String, RuleRef>) -> Vec<Vec<String>> {
    let mut frame = Frame {
        stack: [0; 512],
        heap: Vec::new(),
        length: 16,
    };
    let mut count = 0_usize;
    for (_, rules) in rules_by_program.iter_all() {
        for rule in rules {
            let Some(prefix) = rule.as_any().downcast_ref::<PrefixRule>() else {
                continue;
            };
            let mut admission = [0_u8; 16];
            admission[8] = match prefix.decision {
                Decision::Allow => 0,
                Decision::Prompt => 1,
                Decision::Forbidden => 2,
            };
            let mut result = [0xff_u8; 8];
            invoke(&admission, &mut result, &mut []);
            let admitted = word(&result, 0);
            assert!(admitted <= 1, "HIA allowed-prefix admission is invalid");
            if admitted == 0 {
                continue;
            }
            count = count
                .checked_add(1)
                .unwrap_or_else(|| panic!("HIA allowed-prefix rule count overflow"));
            let tokens = prefix
                .pattern
                .rest
                .len()
                .checked_add(1)
                .unwrap_or_else(|| panic!("HIA allowed-prefix token count overflow"));
            frame.word(tokens);
            frame.word(/*value*/ 0);
            frame.word(/*value*/ 1);
            frame.word(prefix.pattern.first.len());
            frame.append(prefix.pattern.first.as_bytes());
            for token in prefix.pattern.rest.iter() {
                match token {
                    PatternToken::Single(value) => {
                        frame.word(/*value*/ 0);
                        frame.word(/*value*/ 1);
                        frame.word(value.len());
                        frame.append(value.as_bytes());
                    }
                    PatternToken::Alts(values) => {
                        frame.word(/*value*/ 1);
                        frame.word(values.len());
                        for value in values {
                            frame.word(value.len());
                            frame.append(value.as_bytes());
                        }
                    }
                }
            }
        }
    }
    let source = frame.bytes();
    source[..8].copy_from_slice(&1_u64.to_le_bytes());
    source[8..16].copy_from_slice(&(count as u64).to_le_bytes());
    let mut plan = [0xff_u8; 24];
    invoke(source, &mut plan, &mut []);
    let rendered = word(&plan, 0);
    let workspace_size = word(&plan, 8);
    let output_size = word(&plan, 16);
    let metadata = count
        .checked_mul(24)
        .and_then(|size| size.checked_add(8))
        .unwrap_or_else(|| panic!("HIA allowed-prefix workspace size overflow"));
    let expected_output = count
        .checked_mul(8)
        .and_then(|size| size.checked_add(8))
        .unwrap_or_else(|| panic!("HIA allowed-prefix output size overflow"));
    assert!(
        rendered <= source.len() - 16 && rendered >= count * 16,
        "HIA allowed-prefix rendered size is invalid"
    );
    assert_eq!(
        metadata.checked_add(rendered),
        Some(workspace_size),
        "HIA allowed-prefix workspace plan is invalid"
    );
    assert_eq!(
        output_size, expected_output,
        "HIA allowed-prefix output plan is invalid"
    );
    let mut stack_output = [0xff_u8; 512];
    let mut heap_output = Vec::new();
    let output = if output_size <= stack_output.len() {
        &mut stack_output[..output_size]
    } else {
        heap_output
            .try_reserve_exact(output_size)
            .unwrap_or_else(|error| panic!("HIA allowed-prefix output allocation failed: {error}"));
        heap_output.resize(output_size, 0xff);
        &mut heap_output
    };
    let mut stack_workspace = [0xff_u8; 512];
    let mut heap_workspace = Vec::new();
    let workspace = if workspace_size <= stack_workspace.len() {
        &mut stack_workspace[..workspace_size]
    } else {
        heap_workspace
            .try_reserve_exact(workspace_size)
            .unwrap_or_else(|error| {
                panic!("HIA allowed-prefix workspace allocation failed: {error}")
            });
        heap_workspace.resize(workspace_size, 0xff);
        &mut heap_workspace
    };
    source[..8].copy_from_slice(&2_u64.to_le_bytes());
    invoke(source, output, workspace);
    decode(output, workspace, count, metadata)
}

fn decode(output: &[u8], workspace: &mut [u8], count: usize, metadata: usize) -> Vec<Vec<String>> {
    let unique = word(output, 0);
    assert!(
        unique <= count && (unique == 0) == (count == 0),
        "HIA allowed-prefix result count is invalid"
    );
    assert_eq!(
        word(workspace, 0),
        metadata,
        "HIA allowed-prefix first offset is invalid"
    );
    let mut previous = metadata;
    for index in 1..=count {
        let end = word(workspace, index * 8);
        assert!(
            end >= previous && end - previous >= 16 && end <= workspace.len(),
            "HIA allowed-prefix vector offset is invalid"
        );
        previous = end;
    }
    assert_eq!(
        previous,
        workspace.len(),
        "HIA allowed-prefix final offset is invalid"
    );
    // Reuse the now-private sort scratch as a visited-index bitmap. This checks
    // the returned wire indices, without another allocation or Rust deduplication.
    let visited = (count + 1) * 8;
    workspace[visited..visited + count].fill(0);
    let mut result = Vec::new();
    result
        .try_reserve_exact(unique)
        .unwrap_or_else(|error| panic!("HIA allowed-prefix result allocation failed: {error}"));
    for position in 0..unique {
        let index = word(output, 8 + position * 8);
        assert!(
            index < count,
            "HIA allowed-prefix result index is out of range"
        );
        assert_eq!(
            workspace[visited + index],
            0,
            "HIA allowed-prefix result index is duplicated"
        );
        workspace[visited + index] = 1;
        let start = word(workspace, index * 8);
        let end = word(workspace, (index + 1) * 8);
        let bytes = &workspace[start..end];
        let tokens = word(bytes, 0);
        assert!(
            tokens > 0 && tokens <= (bytes.len() - 8) / 8,
            "HIA allowed-prefix token count is invalid"
        );
        let mut prefix = Vec::new();
        prefix
            .try_reserve_exact(tokens)
            .unwrap_or_else(|error| panic!("HIA allowed-prefix token allocation failed: {error}"));
        let mut at = 8_usize;
        for _ in 0..tokens {
            let length = word(bytes, at);
            at += 8;
            let end = at
                .checked_add(length)
                .filter(|&end| end <= bytes.len())
                .unwrap_or_else(|| panic!("HIA allowed-prefix token length is invalid"));
            let token = String::from_utf8(bytes[at..end].to_vec())
                .unwrap_or_else(|error| panic!("HIA allowed-prefix output is not UTF-8: {error}"));
            prefix.push(token);
            at = end;
        }
        assert_eq!(
            at,
            bytes.len(),
            "HIA allowed-prefix vector has trailing bytes"
        );
        result.push(prefix);
    }
    result
}

fn word(bytes: &[u8], at: usize) -> usize {
    let value: [u8; 8] = at
        .checked_add(8)
        .and_then(|end| bytes.get(at..end))
        .and_then(|slice| slice.try_into().ok())
        .unwrap_or_else(|| panic!("HIA allowed-prefix result word is out of range"));
    usize::try_from(u64::from_le_bytes(value))
        .unwrap_or_else(|_| panic!("HIA allowed-prefix result word exceeds usize"))
}

fn invoke(source: &[u8], output: &mut [u8], workspace: &mut [u8]) {
    // SAFETY: the three disjoint buffers remain live for the synchronous call.
    // Exact lengths are passed; HIA retains no pointers and validates the whole
    // selected operation and capacities before writing either mutable buffer.
    let status = unsafe {
        codex_hia_allowed_prefixes(
            source.as_ptr(),
            source.len() as u64,
            output.as_mut_ptr(),
            output.len() as u64,
            workspace.as_mut_ptr(),
            workspace.len() as u64,
        )
    };
    assert_eq!(status, 0, "HIA allowed-prefix operation failed");
}
