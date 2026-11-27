//! Allocation accounting is separate from the latency differential executable.
use std::alloc::GlobalAlloc;
use std::alloc::Layout;
use std::alloc::System;
use std::cell::Cell;
use std::hint::black_box;
use std::ops::RangeInclusive;
use std::sync::Arc;

#[path = "../../codex-rs/execpolicy/src/hia_native_prefix.rs"]
mod hia_native_prefix;
mod rule {
    include!(env!("CODEX_HIA_EXECPOLICY_SOURCE"));
}
use rule::PatternToken;
use rule::PrefixPattern;

thread_local! {
    static CALLS: Cell<Option<(usize, usize)>> = const { Cell::new(None) };
}
struct Counted;
#[global_allocator]
static ALLOCATOR: Counted = Counted;

fn record(allocations: usize, reallocations: usize) {
    let _ = CALLS.try_with(|calls| {
        if let Some((a, r)) = calls.get() {
            calls.set(Some((
                a.wrapping_add(allocations),
                r.wrapping_add(reallocations),
            )));
        }
    });
}

// SAFETY: every operation preserves its caller's contract by forwarding to System.
unsafe impl GlobalAlloc for Counted {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        record(1, 0);
        unsafe { System.alloc(layout) }
    }
    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        record(1, 0);
        unsafe { System.alloc_zeroed(layout) }
    }
    unsafe fn realloc(&self, pointer: *mut u8, layout: Layout, size: usize) -> *mut u8 {
        record(0, 1);
        unsafe { System.realloc(pointer, layout, size) }
    }
    unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
        unsafe { System.dealloc(pointer, layout) }
    }
}

fn measured<T>(call: impl FnOnce() -> T) -> (T, (usize, usize)) {
    CALLS.set(Some((0, 0)));
    let value = black_box(call());
    (
        value,
        CALLS
            .replace(None)
            .unwrap_or_else(|| panic!("allocation measurement state was not initialized")),
    )
}

fn check(
    name: &str,
    pattern: &PrefixPattern,
    cmd: &[String],
    expected: Option<Vec<String>>,
    expected_calls: RangeInclusive<usize>,
) -> usize {
    let (actual, (alloc, realloc)) = measured(|| black_box(pattern).matches_prefix(black_box(cmd)));
    assert!(actual == expected, "complete public result differs: {name}");
    assert!(
        expected_calls.contains(&(alloc + realloc)),
        "{name}: alloc={alloc}, realloc={realloc}"
    );
    println!("allocation_case name={name} alloc={alloc} realloc={realloc}");
    1
}

fn main() {
    let (probe, (alloc, realloc)) = measured(|| {
        let mut bytes = black_box(Vec::<u8>::with_capacity(black_box(1)));
        bytes.push(7);
        black_box(&mut bytes).reserve_exact(black_box(4096));
        black_box(bytes)
    });
    assert!(
        alloc > 0 && realloc > 0,
        "allocation counter positive control failed"
    );
    println!("allocation_probe alloc={alloc} realloc={realloc}");
    drop(probe);

    // Rule/cmd construction, expected output, mutation and assertions are outside measurement.
    let mut pattern = PrefixPattern {
        first: "p".into(),
        rest: vec![PatternToken::Single("x".repeat(2_097_153))].into(),
    };
    let mut completed = 0;
    for (name, cmd) in [
        ("large_empty", vec![]),
        ("large_short", vec!["p".to_string()]),
    ] {
        completed += check(name, &pattern, &cmd, None, 0..=0);
    }
    let mut cmd = vec!["p".into(), "x".repeat(2_097_153)];
    completed += check(
        "exact_large",
        &pattern,
        &cmd,
        Some(cmd.clone()),
        1..=usize::MAX,
    );

    // Mutate the same public owner and unique Arc storage; no prepared/cache representation.
    Arc::make_mut(&mut pattern.first).make_ascii_uppercase();
    completed += check("first_changed_old", &pattern, &cmd, None, 1..=usize::MAX);
    cmd[0] = "P".into();
    completed += check(
        "first_changed_new",
        &pattern,
        &cmd,
        Some(cmd.clone()),
        1..=usize::MAX,
    );
    Arc::make_mut(&mut pattern.rest)[0] = PatternToken::Alts(vec!["a".repeat(65_536); 32]);
    completed += check("alts_empty", &pattern, &[], None, 0..=0);
    completed += check("alts_short", &pattern, &cmd[..1], None, 0..=0);
    completed += check("rest_changed_old", &pattern, &cmd, None, 1..=usize::MAX);
    cmd[1] = "a".repeat(65_536);
    completed += check(
        "rest_changed_exact",
        &pattern,
        &cmd,
        Some(cmd.clone()),
        1..=usize::MAX,
    );
    pattern.rest = vec![
        PatternToken::Single(cmd[1].clone()),
        PatternToken::Single("x".repeat(2_097_153)),
    ]
    .into();
    completed += check("rest_grown_short", &pattern, &cmd, None, 0..=0);
    pattern.rest = Vec::new().into();
    completed += check(
        "rest_shrunk",
        &pattern,
        &cmd,
        Some(cmd[..1].to_vec()),
        1..=usize::MAX,
    );

    // Normal Policy lookup has already selected rules for this same first token.
    let ordinary = PrefixPattern {
        first: "git".into(),
        rest: vec![PatternToken::Single("status".into())].into(),
    };
    let mut ordinary_cmd = vec!["git".into(), "other".into()];
    completed += check(
        "same_first_small_mismatch",
        &ordinary,
        &ordinary_cmd,
        None,
        0..=0,
    );
    ordinary_cmd[1] = "status".into();
    completed += check(
        "small_match_owned",
        &ordinary,
        &ordinary_cmd,
        Some(ordinary_cmd.clone()),
        3..=3,
    );

    let mut boundary = PrefixPattern {
        first: "p".into(),
        rest: vec![PatternToken::Single(String::new())].into(),
    };
    let boundary_cmd = vec!["p".into(), String::new()];
    // Fixed headers plus two one-byte first tokens occupy 66 bytes.
    // Replace a token in the same unique Arc while crossing the threshold both ways.
    for (name, capacity, allocations) in [
        ("capacity_511", 511, 0),
        ("capacity_512", 512, 0),
        ("capacity_513", 513, 1),
        ("rest_back_to_stack", 512, 0),
        ("rest_back_to_heap", 513, 1),
    ] {
        Arc::make_mut(&mut boundary.rest)[0] = PatternToken::Single("x".repeat(capacity - 66));
        completed += check(
            name,
            &boundary,
            &boundary_cmd,
            None,
            allocations..=allocations,
        );
    }
    for (name, tail_bytes, allocations) in
        [("exact_match_512", 223, 3), ("exact_match_514", 224, 4)]
    {
        Arc::make_mut(&mut boundary.rest)[0] = PatternToken::Single("x".repeat(tail_bytes));
        let matching = vec!["p".into(), "x".repeat(tail_bytes)];
        completed += check(
            name,
            &boundary,
            &matching,
            Some(matching.clone()),
            allocations..=allocations,
        );
    }

    println!("allocation_summary cases={completed}");
}
