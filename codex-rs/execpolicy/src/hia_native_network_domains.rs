//! Checked transport for HIA's ordered network-domain reduction.
//!
//! HIA selects non-Prompt records, compares exact host bytes and returns the
//! last surviving rule indices in each decision's original order. Rust never
//! normalizes hosts or caches results. Prompt hosts and all justifications stay
//! outside the wire; only final hosts are cloned into the public result.

use crate::Decision;
use crate::rule::NetworkRule;
use std::io::Write;

unsafe extern "C" {
    fn codex_hia_network_domains(
        source: *const u8,
        source_length: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_length: u64,
    ) -> u64;
}

pub(crate) fn compile(rules: &[NetworkRule]) -> (Vec<String>, Vec<String>) {
    let mut stack_indices = [0_usize; 32];
    let mut heap_indices = Vec::new();
    let mut selected = 0_usize;
    let mut capacity = 24_usize;
    let mut remaining = rules;
    let mut base = 0_usize;
    loop {
        let (batch, rest) = remaining.split_at(remaining.len().min(64));
        let mut source = [0_u8; 80];
        source[8..16].copy_from_slice(&(batch.len() as u64).to_le_bytes());
        for (position, rule) in batch.iter().enumerate() {
            source[16 + position] = decision_tag(rule.decision);
        }
        let mut output = [0xff_u8; 72];
        invoke(&source[..16 + batch.len()], &mut output, &mut []);
        let count = read_word(&output, 0);
        assert!(
            count <= batch.len(),
            "HIA network selection count is invalid"
        );
        let mut previous = None;
        for &position in &output[8..8 + count] {
            let position = usize::from(position);
            assert!(
                position < batch.len() && previous.is_none_or(|old| position > old),
                "HIA network selection index is invalid"
            );
            let rule = &batch[position];
            assert_ne!(
                rule.decision,
                Decision::Prompt,
                "HIA network selection returned a Prompt record"
            );
            let index = base + position;
            if selected < stack_indices.len() {
                stack_indices[selected] = index;
            } else {
                if selected == stack_indices.len() {
                    heap_indices.try_reserve_exact(64).unwrap_or_else(|error| {
                        panic!("HIA network index allocation failed: {error}")
                    });
                    heap_indices.extend_from_slice(&stack_indices);
                }
                heap_indices.push(index);
            }
            selected += 1;
            capacity = capacity
                .checked_add(24)
                .and_then(|size| size.checked_add(rule.host.len()))
                .unwrap_or_else(|| panic!("HIA network frame length overflow"));
            previous = Some(position);
        }
        if rest.is_empty() {
            break;
        }
        base += batch.len();
        remaining = rest;
    }
    if selected == 0 {
        return (Vec::new(), Vec::new());
    }
    let indices = if selected <= stack_indices.len() {
        &stack_indices[..selected]
    } else {
        &heap_indices
    };
    if capacity <= 512 {
        let mut source = [0_u8; 512];
        let mut remaining = &mut source[..capacity];
        encode(&mut remaining, rules, indices);
        assert!(remaining.is_empty(), "HIA network frame size mismatch");
        reduce(&source[..capacity], rules, indices)
    } else {
        let mut source = Vec::new();
        source
            .try_reserve_exact(capacity)
            .unwrap_or_else(|error| panic!("HIA network frame allocation failed: {error}"));
        encode(&mut source, rules, indices);
        assert_eq!(source.len(), capacity, "HIA network frame size mismatch");
        reduce(&source, rules, indices)
    }
}

fn decision_tag(decision: Decision) -> u8 {
    match decision {
        Decision::Allow => 0,
        Decision::Prompt => 1,
        Decision::Forbidden => 2,
    }
}

fn append_word(output: &mut impl Write, value: u64) {
    output
        .write_all(&value.to_le_bytes())
        .unwrap_or_else(|error| panic!("HIA network frame encoding failed: {error}"));
}

fn encode(output: &mut impl Write, rules: &[NetworkRule], indices: &[usize]) {
    append_word(output, /*value*/ 1);
    append_word(output, rules.len() as u64);
    append_word(output, indices.len() as u64);
    for &index in indices {
        let rule = &rules[index];
        append_word(output, index as u64);
        append_word(output, u64::from(decision_tag(rule.decision)));
        append_word(output, rule.host.len() as u64);
        output
            .write_all(rule.host.as_bytes())
            .unwrap_or_else(|error| panic!("HIA network host encoding failed: {error}"));
    }
}

fn reduce(source: &[u8], rules: &[NetworkRule], indices: &[usize]) -> (Vec<String>, Vec<String>) {
    let output_size = indices
        .len()
        .checked_mul(8)
        .and_then(|bytes| bytes.checked_add(16))
        .unwrap_or_else(|| panic!("HIA network output length overflow"));
    let mut stack_output = [0xff_u8; 512];
    let mut heap_output = Vec::new();
    let output = if output_size <= stack_output.len() {
        &mut stack_output[..output_size]
    } else {
        heap_output
            .try_reserve_exact(output_size)
            .unwrap_or_else(|error| panic!("HIA network output allocation failed: {error}"));
        heap_output.resize(output_size, 0xff);
        &mut heap_output
    };
    let mut stack_workspace = [0xff_u8; 512];
    let mut heap_workspace = Vec::new();
    let workspace = if indices.len() <= stack_workspace.len() {
        &mut stack_workspace[..indices.len()]
    } else {
        heap_workspace
            .try_reserve_exact(indices.len())
            .unwrap_or_else(|error| panic!("HIA network workspace allocation failed: {error}"));
        heap_workspace.resize(indices.len(), 0xff);
        &mut heap_workspace
    };
    invoke(source, output, workspace);
    let allowed = read_word(output, 0);
    let denied = read_word(output, 8);
    let total = allowed
        .checked_add(denied)
        .unwrap_or_else(|| panic!("HIA network result count overflow"));
    assert!(
        total > 0 && total <= indices.len(),
        "HIA network result count is invalid"
    );
    let mut results = [Vec::new(), Vec::new()];
    let mut at = 16;
    for ((count, decision), result) in [(allowed, Decision::Allow), (denied, Decision::Forbidden)]
        .into_iter()
        .zip(&mut results)
    {
        result
            .try_reserve_exact(count)
            .unwrap_or_else(|error| panic!("HIA network result allocation failed: {error}"));
        let mut previous = None;
        for _ in 0..count {
            let index = read_word(output, at);
            assert!(
                indices.binary_search(&index).is_ok() && previous.is_none_or(|old| index > old),
                "HIA network result index is invalid"
            );
            let rule = rules
                .get(index)
                .unwrap_or_else(|| panic!("HIA network result index is out of range"));
            assert_eq!(
                rule.decision, decision,
                "HIA network result decision is invalid"
            );
            result.push(rule.host.clone());
            previous = Some(index);
            at += 8;
        }
    }
    let [allowed, denied] = results;
    (allowed, denied)
}

fn read_word(bytes: &[u8], at: usize) -> usize {
    let word: [u8; 8] = bytes
        .get(at..at + 8)
        .and_then(|slice| slice.try_into().ok())
        .unwrap_or_else(|| panic!("HIA network result word is out of range"));
    usize::try_from(u64::from_le_bytes(word))
        .unwrap_or_else(|_| panic!("HIA network result word exceeds usize"))
}

fn invoke(source: &[u8], output: &mut [u8], workspace: &mut [u8]) {
    // SAFETY: the three disjoint buffers stay live for this synchronous call.
    // Their exact extents are supplied; HIA retains no pointers. It validates
    // the complete operation before writing output or its private workspace.
    let status = unsafe {
        codex_hia_network_domains(
            source.as_ptr(),
            source.len() as u64,
            output.as_mut_ptr(),
            output.len() as u64,
            workspace.as_mut_ptr(),
            workspace.len() as u64,
        )
    };
    assert_eq!(
        status, 0,
        "HIA network domains rejected the native operation"
    );
}
