#!/usr/bin/env python3
from pathlib import Path

path = Path("codex-rs/hepta-context-compiler/src/provider_closure.rs")
text = path.read_text()
needle = "mod tests {\n    use super::*;\n"
if text.count(needle) != 1:
    raise SystemExit("provider_closure.rs: test module anchor drift")
text = text.replace(
    needle,
    "mod tests {\n    use super::*;\n    use proptest::prelude::*;\n",
    1,
)
if not text.endswith("}\n"):
    raise SystemExit("provider_closure.rs: unexpected file ending")
extra = r'''

    proptest! {
        #[test]
        fn generated_segment_maps_are_total_deterministic_and_single_context(
            prefix_len in 0_usize..2048,
            suffix_len in 0_usize..2048,
            seed in any::<u64>(),
        ) {
            let payload = format!("CTX::{seed:016x}::END").into_bytes();
            let mut request = vec![b'p'; prefix_len];
            request.extend_from_slice(&payload);
            request.extend(std::iter::repeat(b's').take(suffix_len));
            let first = build_segment_map(&request, &payload, digest("generated-payload"))
                .expect("generated map");
            let second = build_segment_map(&request, &payload, digest("generated-payload"))
                .expect("deterministic map");
            prop_assert_eq!(&first, &second);
            prop_assert_eq!(
                first.iter().filter(|segment| {
                    segment.kind() == FinalRequestSegmentKindV2::CanonicalContextBundle
                }).count(),
                1
            );
            prop_assert_eq!(
                first.last().expect("last segment").end_offset(),
                request.len() as u64
            );
            prop_assert_eq!(
                compute_segment_map_digest(&first),
                compute_segment_map_digest(&second)
            );
        }

        #[test]
        fn generated_gap_and_overlap_mutations_fail_closed(
            prefix_len in 2_usize..512,
            suffix_len in 1_usize..512,
            seed in any::<u32>(),
        ) {
            let payload = format!("UNIQUE-CONTEXT-{seed:08x}").into_bytes();
            let mut request = vec![b'a'; prefix_len];
            request.extend_from_slice(&payload);
            request.extend(std::iter::repeat(b'z').take(suffix_len));
            let valid = build_segment_map(&request, &payload, digest("mutation-payload"))
                .expect("valid map");

            let mut gap = valid.clone();
            gap[0].end_offset -= 1;
            prop_assert_eq!(
                validate_segment_coverage(&gap, request.len() as u64),
                Err(ProviderClosureErrorV2::SegmentCoverageInvalid)
            );

            let mut overlap = valid;
            overlap[1].start_offset -= 1;
            prop_assert_eq!(
                validate_segment_coverage(&overlap, request.len() as u64),
                Err(ProviderClosureErrorV2::SegmentCoverageInvalid)
            );
        }
    }

    #[test]
    fn generated_unicode_control_corpus_keeps_exact_escaped_identity() {
        for index in 0_u32..1024 {
            let payload = format!("政策:{index}:🧪\\ncontrol:\u{0001}");
            let encoded = serde_json::to_string(&payload).expect("encode");
            let encoded = &encoded.as_bytes()[1..encoded.len() - 1];
            let mut request = format!("{{\"model\":\"m-{index}\",\"instructions\":\"")
                .into_bytes();
            request.extend_from_slice(encoded);
            request.extend_from_slice(b"\",\"input\":[]}");
            let segments = build_segment_map(&request, encoded, digest("unicode-corpus"))
                .expect("corpus proof");
            validate_segment_coverage(&segments, request.len() as u64)
                .expect("complete coverage");
            assert_eq!(
                segments
                    .iter()
                    .filter(|segment| {
                        segment.kind() == FinalRequestSegmentKindV2::CanonicalContextBundle
                    })
                    .count(),
                1
            );
        }
    }
'''
text = text[:-2] + extra + "}\n"
path.write_text(text)
