//! Linear first-occurrence search for source-bound prompt serialization.
//!
//! Knuth–Morris–Pratt prevents repeated-prefix inputs from multiplying the
//! serialized-payload scan by the realization length. Each proof search starts
//! at the previous occurrence's end, preserving first-match and cursor order.

use codex_hepta_prompt_registry::MAX_REALIZATION_PAYLOAD_BYTES;

pub(super) fn find_subslice(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    if needle.is_empty()
        || needle.len() > haystack.len()
        || needle.len() > MAX_REALIZATION_PAYLOAD_BYTES
    {
        return None;
    }
    // Source validation already enforces the registry's 64-KiB ceiling. Keep
    // it explicit here too so the prefix table never grows beyond that bound.
    let mut prefix_lengths = vec![0_usize; needle.len()];
    let mut matched = 0_usize;
    for index in 1..needle.len() {
        while matched > 0 && needle[index] != needle[matched] {
            matched = prefix_lengths[matched - 1];
        }
        if needle[index] == needle[matched] {
            matched += 1;
        }
        prefix_lengths[index] = matched;
    }
    matched = 0;
    for (index, byte) in haystack.iter().enumerate() {
        while matched > 0 && *byte != needle[matched] {
            matched = prefix_lengths[matched - 1];
        }
        if *byte == needle[matched] {
            matched += 1;
        }
        if matched == needle.len() {
            return Some(index + 1 - needle.len());
        }
    }
    None
}

#[cfg(test)]
#[path = "prompt_serialization_search_tests.rs"]
mod tests;
