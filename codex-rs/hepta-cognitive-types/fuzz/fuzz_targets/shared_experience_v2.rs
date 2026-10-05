#![no_main]

mod support;

use codex_hepta_cognitive_types::shared_experience::{
    SharedExperiencePublicationV2, SharedExperienceRevocationReceiptV2,
    SharedExperienceSnapshotV2, SharedExperienceUseReceiptV2,
};
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    support::exercise::<SharedExperiencePublicationV2>(data);
    support::exercise::<SharedExperienceSnapshotV2>(data);
    support::exercise::<SharedExperienceUseReceiptV2>(data);
    support::exercise::<SharedExperienceRevocationReceiptV2>(data);
});
