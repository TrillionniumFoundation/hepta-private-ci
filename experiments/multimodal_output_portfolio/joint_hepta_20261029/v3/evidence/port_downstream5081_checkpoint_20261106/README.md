# Source-bound downstream qualification from #5081

Every behavioral result in this packet is bound to head 99e53dc988476d96c1e61354fbb0aeecd4c1cf17, tree e368e870e179b0e726189192343f03b151bd1fa4, run 42247397355. These are actual original executions and retained source checks, not latest-head or cross-platform claims. The audits preserve precise artifact, job, command, source and byte identities.

| Original scope | Actual outcome |
| --- | --- |
| Independent full upstream AWS | 244 passed, one original ignored, no passed-after-retry |
| Workspace AWS consumers | 209 passed across aws-auth 5, login 195 and secrets 9, no skips |
| YAML and five consumers | 825 passed: 9, 49, 175, 426 and 166, no skips |
| Keyring | One passed, no skip |
| Execution policy | 34 passed, no skips |
| Matrix ordinary packages | 116 passed across protocol 12, store 36, SDK 36 and daemon 32; two original ignored |
| Independent old-version reopen | One selected ignored test actually executed and passed with zero retries; two unrelated tests filtered out |
| Linux Bazel libraries | 13 targets built successfully, 4661 reported actions; build only |
| Original full cargo-deny | Failed on old vodozemac 0.11.1; original failure retained |
| Native ARM Synapse | Failed at start-build, before business tests; original inner compiler error remains unresolved at this snapshot |

The workspace AWS and YAML artifacts bind every one of their 37 and 51 command logs to exit zero, all 320 producer-source blobs, and unchanged 333-entry committed rosters read five and seven times. Matrix separately verifies its 52 command logs, original old-version fixture identities, full original binary stream hash and exact reopen JUnit. All ordinary counts are counted from actual named native output. Internal early-return branches were not separately audited. The 0.18 fixture production and current-store reopen are distinct stages.

The YAML post-test Clippy artifact passed with an empty patch and unchanged source. The Matrix post-test Clippy artifact passed but generated three mechanical lint hunks in real_synapse_e2e.rs. It explicitly does not transfer the original 116+1 behavioral results to the edited source. The original patch was independently replayed in both directions. Unit26 verifies the current 100644 preimage, applies only those three hunks and original just formatting, then was published as #5125. Native and formatted after bytes differ only in whitespace. The early isolated formatter attempt lacked the declared sibling fixture modules; that real failure is retained, followed by a successful original just fmt in a complete owned checkout without a formatting exception. Final-source native qualification remains separate.

The old cargo-deny findings are preserved rather than rewritten after the vodozemac repair. The successful native 0.11.2 proposal and #5119 integrated producer are in the separate vodo_native5119 packet. Similarly, ARM recovery attempt 1 is preserved in #5123 and its one identical retry remains separate. No recovery, Clippy, producer or build-only result is substituted for a behavioral test.

## Exact retention boundary

Seven small original ZIP artifacts are retained whole. For the three larger original artifacts, every member except one explicitly listed compiled executable is retained verbatim: the 40,657,216-byte upstream test executable, 16,086,896-byte diagnostic cargo-deny executable, and 480,145,664-byte Matrix reopen executable are omitted. Their full original ZIP identities, artifact IDs, all member sizes, CRC values and verified SHA-256 values remain in the scope and audit receipts. The executables were fully streamed and hashed during the original independent audits but never executed locally. All original local ZIP files remain unchanged. The three omitted ZIP containers and executable bytes cannot be restored from this compact packet.

This selection preserves original test logs, XML, source snapshots, fixture databases, negative evidence and diagnostics. No file is relabelled as a success and no original gate, bound, timeout or scanner is changed. The GitHub connector's documented refusal to download the 3.67 GB original ARM artifact is retained; it does not justify inferring the unseen internal build failure.

Run `python restore.py /absolute/new-directory` to restore every INDEX input as inert regular 0644 files. The previously reviewed bounded reader differs only in its fixed INDEX SHA-256. It checks the full listed roster and every byte identity before writing and never executes archived code. Recorded local input modes are separate from the native committed-mode proofs. Restoring this packet does not rerun or broaden any qualification.
