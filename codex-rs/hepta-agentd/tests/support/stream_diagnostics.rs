pub(crate) const MAX_STREAM_BYTES: usize = 4_096;

/// Preserve the first failure and the final output without exceeding the
/// decoded-byte budget, even when lossy UTF-8 decoding expands invalid bytes.
pub(crate) fn summarize_stream(bytes: impl DoubleEndedIterator<Item = u8> + Clone) -> String {
    let prefix: Vec<_> = bytes.clone().take(MAX_STREAM_BYTES + 1).collect();
    let decoded_prefix = String::from_utf8_lossy(&prefix);
    if prefix.len() <= MAX_STREAM_BYTES && decoded_prefix.len() <= MAX_STREAM_BYTES {
        return decoded_prefix.into_owned();
    }

    const OMITTED: &str = "\n...[middle omitted]...\n";
    let head_budget = (MAX_STREAM_BYTES - OMITTED.len()) / 2;
    let tail_budget = MAX_STREAM_BYTES - OMITTED.len() - head_budget;
    let mut head_end = head_budget;
    while !decoded_prefix.is_char_boundary(head_end) {
        head_end -= 1;
    }

    let mut suffix: Vec<_> = bytes.rev().take(MAX_STREAM_BYTES + 1).collect();
    suffix.reverse();
    let decoded_suffix = String::from_utf8_lossy(&suffix);
    let mut tail_start = decoded_suffix.len().saturating_sub(tail_budget);
    while !decoded_suffix.is_char_boundary(tail_start) {
        tail_start += 1;
    }
    format!(
        "{}{OMITTED}{}",
        &decoded_prefix[..head_end],
        &decoded_suffix[tail_start..]
    )
}
