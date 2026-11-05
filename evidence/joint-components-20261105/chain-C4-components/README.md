# C4 parser cache coverage correction

C3 completed nineteen original applicability cases but reached the unchanged 300-second command limit. The two observed repeatedly parsed Rust sources exceeded the cache eligibility threshold. C4 changes only that threshold from 262144 to 524288 characters. Each independent parser LRU is still bounded to 128 entries. Character count is not a byte or measured RSS bound; original source reads, path checks, immutable parse results, all tests, actual CI resources and timeout remain unchanged.

The complete C3 base passed the original project audit and raw source guard before this commit. Its actual key stdout/stderr and source manifests are retained separately in ../chain-C3-history. This component record does not claim a C4 native or release pass.
