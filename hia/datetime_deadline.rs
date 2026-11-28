//! Transport for the qualified HIA duration and UTC arithmetic components.
//! Duration admission and checked deadline arithmetic execute in HIA.

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
}

type Entry = unsafe extern "C" fn(*const u8, u64, *mut u8, u64, *mut u8, u64) -> u64;

fn transfer<const N: usize>(entry: Entry, words: [u64; 8], output: &mut [u8; N]) {
    let mut source = [0_u8; 64];
    for (slot, word) in source.chunks_exact_mut(8).zip(words) {
        slot.copy_from_slice(&word.to_le_bytes());
    }
    // SAFETY: the two private call sites select a validated native entry and its
    // exact output size. Source and output are disjoint live allocations. Both
    // qualified components require zero workspace and retain no pointers.
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
    assert_eq!(status, 0, "native deadline component rejected its frame");
}

fn words<const N: usize>(bytes: &[u8]) -> [u64; N] {
    assert_eq!(bytes.len(), N * 8, "native deadline output length");
    std::array::from_fn(|index| {
        u64::from_le_bytes(
            bytes[index * 8..(index + 1) * 8]
                .try_into()
                .expect("complete native deadline word"),
        )
    })
}

/// Add a canonical standard duration to a UTC timestamp through native HIA.
pub(crate) fn add_std(
    seconds: i64,
    nanos: u32,
    duration: std::time::Duration,
) -> Option<(i64, u32)> {
    let mut duration_output = [0_u8; 168];
    transfer(
        codex_hia_duration_units,
        [
            1,
            9,
            duration.as_secs(),
            u64::from(duration.subsec_nanos()),
            0,
            0,
            0,
            0,
        ],
        &mut duration_output,
    );
    let duration = words::<21>(&duration_output);
    assert_eq!(duration[0], 1, "native duration result version");
    assert!(duration[1] <= 1, "native duration admission flag");
    if duration[1] == 0 {
        return None;
    }
    let mut deadline_output = [0_u8; 64];
    transfer(
        codex_hia_datetime_arithmetic,
        [
            1,
            0,
            seconds as u64,
            u64::from(nanos),
            duration[2],
            duration[3],
            0,
            0,
        ],
        &mut deadline_output,
    );
    let deadline = words::<8>(&deadline_output);
    assert_eq!(deadline[0], 1, "native arithmetic result version");
    assert!(
        deadline[1..3].iter().all(|word| *word <= 1),
        "native arithmetic result flags"
    );
    assert_eq!(&deadline[5..], &[0; 3], "native addition reserved fields");
    if deadline[1] == 0 || deadline[2] == 0 {
        return None;
    }
    Some((
        deadline[3] as i64,
        u32::try_from(deadline[4]).expect("native timestamp fraction fits u32"),
    ))
}
