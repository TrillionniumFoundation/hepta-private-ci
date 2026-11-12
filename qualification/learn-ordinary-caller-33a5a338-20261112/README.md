# Original broker-head repair: full CLI still failed

The exact repaired source was `33a5a338637a4787237bc4154b23a06f6ad34357`, tree `9434660576cf6269db9606d5962b1b33c07a4b82`. Its complete historical-capture QA file passed 14 tests. The authoritative full caller CLI then ran for 644.974156656 seconds and returned exit 1. Both commands retained identical source hashes before and after.

The actual failure was an unresolved possible `LearningArtifactOwnerService::open` receiver in `neuron_generation_drained_test_support.rs`. This is not a timeout. The original 195-byte stderr, full command, original source identities, terminal record and driver are retained in the archive.

A separate read-only diagnostic applied that original typed boundary to all 6,885 Rust files, finding five existing test-only helpers with unresolved same-name `open` calls. Their only real production caller remained `production_post_a_artifacts.rs`. Each helper's actual module ancestry was verified to be under `#[cfg(test)]`. This diagnostic is not a full caller gate.

Successor `65c32e639e99912fc5a437afe5dd128271ec05ae` adds only explicit `#![cfg(test)]` to those five helpers and source negative controls for removal, comments and production-capable conditions. All helper implementations and assertions are byte-for-byte unchanged after removing that added attribute. Its initial ordinary-callers QA ran 4 methods with 5 failing fixture subtests because the local test index lacked the real complete-index authority fields. The separate file-cfg QA passed 5 methods. These original failures are preserved. The full CLI at that exact source is still a separate running gate.

Candidate `31a67f4782d5279034d4c90786d3b944d5da629d` adds the actual complete Rust index field context to the negative controls. Its exact postimage was explicitly loaded from tooling against frozen 65c32 sources and all 4 methods passed; this is not an in-repository final gate at that commit. A separate Git index created that reviewable candidate while the running CLI checkout stayed byte-for-byte unchanged. No Rust or native test was executed here.
