# Two private evaluation material projections

The candidate removes the unused digest on the internal verification result and one unused getter on the internal wire request. The verified product commit changes two Rust files by deleting seven lines. The original protocol fields and request checks, holdout digest binding and reconstruction of the estimand preimage still run in the same parts of the program.

| Source | Commit |
| --- | --- |
| Baseline | c6a3ed9c36f88707d2f29630efe1e3ea4ee0e902 |
| Candidate | 4adbacbd99f4d37e415cb90bc15a27b5b105e393 |
| Earlier qualified source compared | 24abd04c825cb0d5d0ce27b52ac5008eda13dde4 |
| Paired execution driver | 8fba44aa537d0921e3e51f8cb4e8502ba3500330 |

The original three-crate all-target Clippy command produced 128 diagnostics on the baseline and 126 on the candidate. The two removed diagnostics named the projections above. The complete diagnostic comparison found zero additions. The original native material lifecycle suite passed 13 of 13 cases per source. The original codec suite passed 8 of 8 per source. Each case ran independently against the ELF compiled from its own checkout. The two executables have distinct SHA256 digests. [Paired native and strict jobs](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45129947088)

The two original GitHub archives contained 42 successful individual native test logs and both complete strict compiler logs. Their SHA256 digests were checked after download. The compact native and strict JSON files in this directory preserve the original archive member bytes.

| Original ZIP | Bytes | SHA256 |
| --- | ---: | --- |
| [Original native logs](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45129947088/artifacts/14798246646) | 261054 | 7d96b72831bb897d9ee5012b22904d8045d6a8bbcebd15f3684a7141ef487d86 |
| [Original strict logs](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45129947088/artifacts/14797762348) | 183701 | 3167e3a21efe692a087ab97f9d3494fafeacf5b21b81097fdc94f549f902e8e1 |

Run `python3 verify_source.py /path/to/repository` with all three source commits available. The alternative command `python3 verify_source.py --github` uses the GitHub CLI for read-only access to the same source objects. Both forms check the exact deletion from the previous source and compare the retained validation against the two-tree Git history.

The original whole-repository caller verifier passed on the candidate and baseline in separate source snapshots. Both receipts matched the hosted baseline receipt byte for byte. Each covered 1,652 boundaries, 826 protected paths and 9,141 Rust files and reported `authorityGranted=false`. The raw 770,005-byte JSON has SHA256 `2de991230d84e60c8d440278ceb189e0f4111ce8b7c200a934ffc7a31257d6c3`. The persistent archive contains the full compressed receipt and its verifier. The snapshot input hashes, candidate run duration and prior hosted checkout identity are in the adjacent JSON. [Original whole-repository receipt](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/7c0e392f4f9348d587c366d145f94325c69fc002/docs/learning/evidence/agentd-private-migration-20261123)
