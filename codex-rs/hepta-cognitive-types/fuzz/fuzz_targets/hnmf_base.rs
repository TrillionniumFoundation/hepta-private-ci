#![no_main]

mod support;

use codex_hepta_cognitive_types::hnmf::{
    CrossModalBindingV1, MemoryEventV1, ModalitySpanRefV1,
};
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    support::exercise::<ModalitySpanRefV1>(data);
    support::exercise::<MemoryEventV1>(data);
    support::exercise::<CrossModalBindingV1>(data);
});
