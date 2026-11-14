//! Compile the actual public function with HIA dispatch and compare it with
//! the same source compiled separately without the feature as a Rust oracle.

use std::alloc::GlobalAlloc;
use std::alloc::Layout;
use std::alloc::System;
use std::cell::Cell;
use std::hint::black_box;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

#[path = "../../codex-rs/utils/string/src/hia_native.rs"]
mod hia_native;
include!(env!("CODEX_HIA_STRING_SOURCE"));

thread_local! {
    static TRACK_ALLOCATIONS: Cell<bool> = const { Cell::new(false) };
    static ALLOCATIONS: Cell<usize> = const { Cell::new(0) };
}

struct CountingAllocator;

fn record_allocation() {
    let _ = TRACK_ALLOCATIONS.try_with(|enabled| {
        if enabled.get() {
            let _ = ALLOCATIONS.try_with(|count| count.set(count.get() + 1));
        }
    });
}

unsafe impl GlobalAlloc for CountingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        record_allocation();
        unsafe { System.alloc(layout) }
    }

    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        record_allocation();
        unsafe { System.alloc_zeroed(layout) }
    }

    unsafe fn realloc(&self, pointer: *mut u8, layout: Layout, size: usize) -> *mut u8 {
        record_allocation();
        unsafe { System.realloc(pointer, layout, size) }
    }

    unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
        unsafe { System.dealloc(pointer, layout) }
    }
}

#[global_allocator]
static ALLOCATOR: CountingAllocator = CountingAllocator;
static COMPARISONS: AtomicUsize = AtomicUsize::new(0);

fn compare(text: &str, budget: usize) {
    let expected = string_reference::take_bytes_at_char_boundary(text, budget);
    let actual = take_bytes_at_char_boundary(text, budget);
    assert_eq!(
        actual,
        expected,
        "string bytes={}, budget={budget}",
        text.len()
    );
    assert_eq!(
        actual.as_ptr(),
        text.as_ptr(),
        "prefix must borrow the input"
    );
    COMPARISONS.fetch_add(1, Ordering::Relaxed);
}

fn report_comparisons() {
    println!(
        "native_string_original_rust_comparisons={}",
        COMPARISONS.load(Ordering::Relaxed)
    );
}

#[test]
fn unicode_boundaries_match_the_original_rust() {
    for text in [
        "",
        "a",
        "ascii text",
        "\0a\u{7f}",
        "é",
        "汉字",
        "😀abc😀",
        "a\u{301}",
        "👩\u{200d}🔬",
        "\u{7f}\u{80}\u{7ff}\u{800}\u{d7ff}\u{e000}\u{ffff}\u{10000}\u{10ffff}",
    ] {
        for budget in 0..=text.len() + 2 {
            compare(text, budget);
        }
        compare(text, usize::MAX);
    }
    report_comparisons();
}

#[test]
fn deterministic_unicode_matches_the_original_rust() {
    let mut state = 0x7a6b_51e3_9980_219d_u64;
    for sample in 0..2048 {
        let mut text = String::new();
        for _ in 0..sample % 41 {
            state = state
                .wrapping_mul(6_364_136_223_846_793_005)
                .wrapping_add(1);
            let scalar = ((state >> 16) % 0x11_0000) as u32;
            if let Some(ch) = char::from_u32(scalar) {
                text.push(ch);
            }
        }
        for budget in [
            0,
            1,
            2,
            3,
            text.len() / 2,
            text.len().saturating_sub(1),
            text.len(),
            usize::MAX,
        ] {
            compare(&text, budget);
        }
    }
    report_comparisons();
}

#[test]
fn multi_megabyte_input_has_no_frame_limit() {
    let text = "é😀汉a".repeat(900_000);
    assert!(text.len() > 8 * 1024 * 1024);
    for budget in [
        0,
        1,
        2,
        3,
        (1 << 20) - 1,
        1 << 20,
        (1 << 20) + 1,
        (1 << 20) + 2,
        (1 << 20) + 3,
        text.len() - 4,
        text.len() - 3,
        text.len() - 2,
        text.len() - 1,
        text.len(),
        usize::MAX,
    ] {
        compare(&text, budget);
    }
    report_comparisons();
}

#[test]
fn native_prefix_performs_no_heap_allocations() {
    let text = "aé汉😀".repeat(200_000);
    let budgets = [
        0,
        1,
        2,
        3,
        (1 << 20) + 1,
        text.len() - 3,
        text.len(),
        usize::MAX,
    ];
    ALLOCATIONS.with(|count| count.set(0));
    TRACK_ALLOCATIONS.with(|enabled| enabled.set(true));
    for _ in 0..256 {
        for budget in budgets {
            black_box(take_bytes_at_char_boundary(
                black_box(&text),
                black_box(budget),
            ));
        }
    }
    TRACK_ALLOCATIONS.with(|enabled| enabled.set(false));
    let allocations = ALLOCATIONS.with(Cell::get);
    assert_eq!(
        allocations, 0,
        "the borrowed prefix API must remain allocation-free"
    );
    println!(
        "native_string_allocation_free_calls={}",
        256 * budgets.len()
    );
}

#[test]
fn concurrent_callers_keep_independent_frames() {
    let text = "é汉😀abc\0".repeat(37);
    std::thread::scope(|scope| {
        for worker in 0..8 {
            let text = &text;
            scope.spawn(move || {
                for iteration in 0..256 {
                    compare(text, (iteration * 13 + worker) % (text.len() + 7));
                }
            });
        }
    });
    report_comparisons();
}
