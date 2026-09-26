#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:80]!r}")
    file_path.write_text(text.replace(old, new, 1))


replace_once(
    "codex-rs/hepta-context-compiler/src/lib.rs",
    "mod candidate_bound;\nmod requirements;",
    "mod candidate_bound;\nmod provider_closure;\nmod requirements;",
)
replace_once(
    "codex-rs/hepta-context-compiler/src/lib.rs",
    "pub use candidate_bound::compile_candidate_bound_with_requirements;\n",
    "pub use candidate_bound::compile_candidate_bound_with_requirements;\n"
    "pub use provider_closure::ExactFinalRequestTokenizerV2;\n"
    "pub use provider_closure::FinalProviderRequestProofV2;\n"
    "pub use provider_closure::FinalRequestSegmentKindV2;\n"
    "pub use provider_closure::FinalRequestSegmentV2;\n"
    "pub use provider_closure::FinalRequestTokenizationReceiptV2;\n"
    "pub use provider_closure::FinalRequestTokenizerIdentityV2;\n"
    "pub use provider_closure::MAX_FINAL_PROVIDER_REQUEST_BYTES_V2;\n"
    "pub use provider_closure::MAX_FINAL_PROVIDER_REQUEST_SEGMENTS_V2;\n"
    "pub use provider_closure::ProviderClosureErrorV2;\n"
    "pub use provider_closure::VerifiedAdmissionSnapshotSuccessorV2;\n"
    "pub use provider_closure::prepare_delivery_from_successor_v2;\n"
    "pub use provider_closure::prove_final_provider_request_v2;\n"
    "pub use provider_closure::verify_admission_snapshot_successor_typed_v2;\n",
)
replace_once(
    "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    "    pub const fn successor_snapshot_digest(&self) -> Digest32 {",
    "    pub fn successor_snapshot_digest(&self) -> Digest32 {",
)
replace_once(
    "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    "    let [start] = matches.as_slice() else {\n",
    "    let [start] = matches.as_slice() else {\n",
)
replace_once(
    "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    "    let end = start\n        .checked_add(encoded_payload.len())",
    "    let start = *start;\n    let end = start\n        .checked_add(encoded_payload.len())",
)
replace_once(
    "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    "    if *start > 0 {",
    "    if start > 0 {",
)
replace_once(
    "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    "            *start,\n            &request[..*start],",
    "            start,\n            &request[..start],",
)
replace_once(
    "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    "        *start,\n        end,\n        &request[*start..end],",
    "        start,\n        end,\n        &request[start..end],",
)
replace_once(
    "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    "        request.extend(std::iter::repeat_n(b'z', 1024 * 1024));",
    "        request.extend(std::iter::repeat(b'z').take(1024 * 1024));",
)
