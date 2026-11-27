//! Storage and framing for HIA's ordered byte-range index.
//!
//! HIA owns comparisons, duplicate detection, AVL links and rotations, ordered
//! traversal, and usage marks. Rust owns the buffers and follows native IDs.
//! Keys remain borrowed for each call. Native nodes retain offsets, not pointers;
//! the caller must keep earlier key bytes unchanged and may append new bytes.

const HEADER: usize = 128;
const NODE: usize = 64;
const RESULT: usize = 32;
const ORDER_PAGE: usize = 1024;
#[cfg(test)]
const QUERY_WINDOW: usize = 4096;

const INSERT: u64 = 0;
const ORDERED: u64 = 1;
#[cfg(test)]
const FIND: u64 = 2;
#[cfg(test)]
const FIND_AND_MARK: u64 = 3;
#[cfg(test)]
const CONTINUE_QUERY: u64 = 4;
#[cfg(test)]
const FIRST_UNUSED: u64 = 5;

#[derive(Debug, PartialEq, Eq)]
pub(super) enum Insert {
    New { id: usize },
    Existing { id: usize },
}

pub(super) struct Index {
    workspace: Vec<u8>,
    output: Vec<u8>,
    count: usize,
}

struct Reply {
    bytes: usize,
    count: usize,
    event: u64,
    a: u64,
    b: u64,
    c: u64,
}

#[cfg(test)]
enum Query {
    Find,
    FindAndMark,
}

unsafe extern "C" {
    fn codex_hia_template_index(
        keys: *const u8,
        keys_len: u64,
        output: *mut u8,
        output_len: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

impl Index {
    pub(super) fn new() -> Self {
        Self {
            workspace: vec![0; HEADER],
            output: vec![0; RESULT],
            count: 0,
        }
    }

    pub(super) fn insert_range(&mut self, keys: &[u8], begin: usize, end: usize) -> Insert {
        let next_count = self
            .count
            .checked_add(1)
            .unwrap_or_else(|| panic!("HIA template index size overflow"));
        let capacity = next_count
            .checked_mul(NODE)
            .and_then(|bytes| bytes.checked_add(HEADER))
            .unwrap_or_else(|| panic!("HIA template node buffer size overflow"));
        grow(&mut self.workspace, capacity);
        self.command([INSERT, begin as u64, end as u64, 0]);
        let reply = self.invoke(keys);
        assert_eq!(reply.bytes, RESULT, "invalid HIA insert result size");
        assert_eq!((reply.b, reply.c), (0, 0), "invalid HIA insert result");
        let id = size(reply.a);
        match reply.event {
            0 => {
                assert_eq!(id, self.count, "invalid HIA new node ID");
                assert_eq!(reply.count, next_count, "invalid HIA inserted count");
                self.count = reply.count;
                Insert::New { id }
            }
            1 => {
                assert_eq!(reply.count, self.count, "invalid HIA duplicate count");
                assert!(id < self.count, "invalid HIA existing node ID");
                Insert::Existing { id }
            }
            _ => panic!("invalid HIA insertion event: {}", reply.event),
        }
    }

    pub(super) fn ordered_ids(&mut self) -> Vec<usize> {
        let page_capacity = self.count.min(ORDER_PAGE);
        grow(&mut self.output, RESULT + 8 * page_capacity);
        let mut ids = Vec::new();
        ids.try_reserve_exact(self.count)
            .unwrap_or_else(|error| panic!("allocate HIA ordered node IDs: {error}"));
        let mut link = u64::MAX;
        let mut seen = 0_usize;
        loop {
            self.command([ORDERED, link, seen as u64, 0]);
            let reply = self.stable_reply(&[]);
            assert_eq!(reply.event, 2, "invalid HIA ordered event");
            let page_count = size(reply.b);
            assert!(page_count <= page_capacity, "invalid HIA ordered page size");
            assert_eq!(
                reply.bytes,
                RESULT + 8 * page_count,
                "invalid HIA ordered bytes"
            );
            seen = seen
                .checked_add(page_count)
                .unwrap_or_else(|| panic!("HIA ordered index size overflow"));
            assert_eq!(size(reply.c), seen, "invalid HIA ordered progress");
            assert!(seen <= self.count, "invalid HIA ordered count");
            for position in 0..page_count {
                let id = size(word(&self.output, RESULT + 8 * position));
                assert!(id < self.count, "invalid HIA ordered node ID");
                ids.push(id);
            }
            link = reply.a;
            if link == 0 {
                assert_eq!(seen, self.count, "incomplete HIA ordered traversal");
                return ids;
            }
            assert!(
                page_count > 0 && seen < self.count && size(link) <= self.count,
                "invalid HIA ordered continuation"
            );
        }
    }

    #[cfg(test)]
    pub(super) fn find(&mut self, keys: &[u8], query: &str) -> Option<usize> {
        self.query(keys, query, Query::Find)
    }

    #[cfg(test)]
    pub(super) fn find_and_mark(&mut self, keys: &[u8], query: &str) -> Option<usize> {
        self.query(keys, query, Query::FindAndMark)
    }

    #[cfg(test)]
    pub(super) fn first_unused(&mut self) -> Option<usize> {
        self.command([FIRST_UNUSED, 0, 0, 0]);
        let reply = self.stable_reply(&[]);
        assert_eq!(reply.bytes, RESULT, "invalid HIA unused result size");
        assert_eq!((reply.b, reply.c), (0, 0), "invalid HIA unused result");
        match reply.event {
            6 => {
                let id = size(reply.a);
                assert!(id < self.count, "invalid HIA unused node ID");
                Some(id)
            }
            4 => {
                assert_eq!(reply.a, 0, "invalid HIA missing result");
                None
            }
            _ => panic!("invalid HIA unused event: {}", reply.event),
        }
    }

    #[cfg(test)]
    fn query(&mut self, keys: &[u8], query: &str, mode: Query) -> Option<usize> {
        let mut command = match mode {
            Query::Find => FIND,
            Query::FindAndMark => FIND_AND_MARK,
        };
        let mut offset = 0_usize;
        let mut previous_request = None;
        loop {
            let Some(remaining) = query.as_bytes().get(offset..) else {
                panic!("invalid HIA query offset");
            };
            let chunk = &remaining[..remaining.len().min(QUERY_WINDOW)];
            grow(&mut self.output, RESULT + chunk.len());
            self.output[RESULT..RESULT + chunk.len()].copy_from_slice(chunk);
            self.command([
                command,
                query.len() as u64,
                offset as u64,
                chunk.len() as u64,
            ]);
            let reply = self.stable_reply(keys);
            assert_eq!(reply.bytes, RESULT, "invalid HIA query result size");
            assert_eq!((reply.b, reply.c), (0, 0), "invalid HIA query result");
            match reply.event {
                3 => {
                    let id = size(reply.a);
                    assert!(id < self.count, "invalid HIA found node ID");
                    return Some(id);
                }
                4 => {
                    assert_eq!(reply.a, 0, "invalid HIA missing result");
                    return None;
                }
                5 => {
                    offset = size(reply.a);
                    assert!(
                        offset < query.len(),
                        "invalid HIA query continuation offset"
                    );
                    let cursor = word(&self.workspace, /*offset*/ 64);
                    assert!(
                        cursor > 0 && size(cursor) <= self.count,
                        "invalid HIA query cursor"
                    );
                    let request = (cursor, offset);
                    assert_ne!(
                        previous_request,
                        Some(request),
                        "HIA query made no progress"
                    );
                    previous_request = Some(request);
                    command = CONTINUE_QUERY;
                }
                _ => panic!("invalid HIA query event: {}", reply.event),
            }
        }
    }

    fn command(&mut self, words: [u64; 4]) {
        for (index, value) in words.into_iter().enumerate() {
            self.workspace[32 + 8 * index..40 + 8 * index].copy_from_slice(&value.to_le_bytes());
        }
    }

    fn stable_reply(&mut self, keys: &[u8]) -> Reply {
        let reply = self.invoke(keys);
        assert_eq!(reply.count, self.count, "unexpected HIA index count change");
        reply
    }

    fn invoke(&mut self, keys: &[u8]) -> Reply {
        // SAFETY: the three buffers are distinct and remain borrowed for this
        // synchronous call. Lengths describe their complete allocations. The
        // B3 static ABI retains no pointers and has no Python-wrapper extent cap.
        let status = unsafe {
            codex_hia_template_index(
                keys.as_ptr(),
                keys.len() as u64,
                self.output.as_mut_ptr(),
                self.output.len() as u64,
                self.workspace.as_mut_ptr(),
                self.workspace.len() as u64,
            )
        };
        let bytes = size(status);
        assert!(
            (RESULT..=self.output.len()).contains(&bytes),
            "invalid HIA index status: {status}"
        );
        let count = size(word(&self.workspace, /*offset*/ 0));
        assert!(
            count <= (self.workspace.len() - HEADER) / NODE,
            "invalid HIA node count"
        );
        let [event, a, b, c] = std::array::from_fn(|index| word(&self.output, 8 * index));
        Reply {
            bytes,
            count,
            event,
            a,
            b,
            c,
        }
    }
}

fn grow(buffer: &mut Vec<u8>, length: usize) {
    if buffer.len() < length {
        buffer
            .try_reserve(length - buffer.len())
            .unwrap_or_else(|error| panic!("allocate HIA index buffer: {error}"));
        buffer.resize(length, /*value*/ 0);
    }
}

fn word(bytes: &[u8], offset: usize) -> u64 {
    let Some(encoded) = bytes.get(offset..offset + 8) else {
        panic!("invalid HIA index word offset");
    };
    let Ok(encoded) = encoded.try_into() else {
        unreachable!("index words contain eight bytes");
    };
    u64::from_le_bytes(encoded)
}

fn size(value: u64) -> usize {
    usize::try_from(value).unwrap_or_else(|_| panic!("invalid HIA index word: {value}"))
}

#[cfg(test)]
#[path = "hia_native_index_tests.rs"]
mod tests;
