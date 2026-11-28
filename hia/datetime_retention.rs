//! Transport for the qualified native duration, arithmetic, and timestamp objects.
//! Retention arithmetic executes in HIA; callers supply their original UTC clock.

unsafe extern "C" {
    fn codex_hia_duration_units(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_len: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
    fn codex_hia_datetime_arithmetic(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_len: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
    fn codex_hia_datetime_units(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_len: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

type Entry = unsafe extern "C" fn(*const u8, u64, *mut u8, u64, *mut u8, u64) -> u64;

#[derive(Clone, Copy)]
#[repr(u64)]
pub(crate) enum Unit {
    Days = 2,
    Hours = 3,
}

pub(crate) struct Cutoff {
    pub(crate) seconds: i64,
    pub(crate) milliseconds: i64,
}

fn transfer<const N: usize>(entry: Entry, words: [u64; 8], output: &mut [u8; N]) {
    let mut source = [0_u8; 64];
    for (slot, word) in source.chunks_exact_mut(8).zip(words) {
        slot.copy_from_slice(&word.to_le_bytes());
    }
    // SAFETY: these private call sites select the admitted entry and exact
    // output size. All buffers are live and disjoint. The three qualified
    // objects require empty workspace and retain no pointers.
    let status = unsafe {
        entry(
            source.as_ptr(),
            source.len() as u64,
            output.as_mut_ptr(),
            output.len() as u64,
            std::ptr::null_mut(),
            /*workspace_len*/ 0,
        )
    };
    assert_eq!(status, 0, "native retention component rejected its frame");
}

fn words<const N: usize>(bytes: &[u8]) -> [u64; N] {
    assert_eq!(bytes.len(), N * 8, "native retention output length");
    std::array::from_fn(|index| {
        let mut word = [0_u8; 8];
        word.copy_from_slice(&bytes[index * 8..(index + 1) * 8]);
        u64::from_le_bytes(word)
    })
}

/// Preserve the original duration-constructor panic and checked date subtraction.
pub(crate) fn subtract(seconds: i64, nanos: u32, unit: Unit, amount: i64) -> Option<Cutoff> {
    let mut duration_output = [0_u8; 168];
    transfer(
        codex_hia_duration_units,
        [1, unit as u64, amount as u64, 0, 0, 0, 0, 0],
        &mut duration_output,
    );
    let duration = words::<21>(&duration_output);
    assert_eq!(duration[0], 1, "native duration result version");
    assert!(duration[1] <= 1, "native duration admission flag");
    if duration[1] == 0 {
        let message = match unit {
            Unit::Days => "TimeDelta::days out of bounds",
            Unit::Hours => "TimeDelta::hours out of bounds",
        };
        panic!("{message}");
    }
    let mut arithmetic_output = [0_u8; 64];
    transfer(
        codex_hia_datetime_arithmetic,
        [
            1,
            1,
            seconds as u64,
            u64::from(nanos),
            duration[2],
            duration[3],
            0,
            0,
        ],
        &mut arithmetic_output,
    );
    let cutoff = words::<8>(&arithmetic_output);
    assert_eq!(cutoff[0], 1, "native arithmetic result version");
    assert!(
        cutoff[1..3].iter().all(|word| *word <= 1),
        "native arithmetic result flags"
    );
    assert_eq!(&cutoff[5..], &[0; 3], "native subtraction reserved fields");
    if cutoff[1] == 0 || cutoff[2] == 0 {
        return None;
    }
    let mut timestamp_output = [0_u8; 80];
    transfer(
        codex_hia_datetime_units,
        [1, 0, cutoff[3], cutoff[4], 0, 0, 0, 0],
        &mut timestamp_output,
    );
    let timestamp = words::<10>(&timestamp_output);
    assert_eq!(&timestamp[..2], &[1, 1], "native timestamp result flags");
    assert_eq!(
        &timestamp[2..4],
        &cutoff[3..5],
        "native timestamp transport changed its operands"
    );
    Some(Cutoff {
        seconds: timestamp[2] as i64,
        milliseconds: timestamp[4] as i64,
    })
}
