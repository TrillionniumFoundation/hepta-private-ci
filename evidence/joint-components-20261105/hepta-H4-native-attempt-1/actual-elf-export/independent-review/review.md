# Independent review of the actual H4 reference archive

The completed H4 child archive, its independently read original part, and all 62 files in the original execution delivery match their declared bytes and hashes. This review read local originals only; it did not execute the exporter, native tests, or the full dependent consumer.

The authoritative archive job `1a1ae17645d-fc05-5d51` completed with exit 0 at 1793922176412 ms, without timeout or retry. Its stdout is complete and parses to the original completion, stderr is empty, and the frozen plan/exporter hashes remain `c917633e…` / `ce96de09…`.

The actual child is 100,964 bytes, SHA256 `47d3c5efa6b9aa4b2f97ef06a606f2931d8065f068311303f8d079c18a7bbaa5`. Four original binary-read responses independently cover the archive and its original part; each path, initial version pin, later expected version, offset, next offset, EOF, chunk hash and reconstructed whole hash was checked. The archive and part are byte-identical while their observed file versions are distinct.

The child has exactly eight regular members totaling 2,848,290 bytes. Each member was decompressed and hashed directly from the child, then compared with the extracted original and index. The 690,778-byte actual index has SHA256 `3c4355fbd6293e631092c432557289ee770e34ae818c2ec68a590b7388d0041e`.

All eleven H4 selected source images carry actual first- and second-read metadata, identical before/after identity and size, and the second full-read SHA equals the original selected image SHA. They total 1,674,575,368 logical bytes. The source inventory is byte-identical to the native H4 inventory; all 597 original observations and 32 retained aliases remain unchanged. Only eleven selected paths were reread. The other aliases were preserved as observations, not falsely reported as separately reopened.

All eleven images reference complete H3 members, with no new embedded ELF payload. The included parent-verification record describes a real desktop full read of the fixed 283,427,280-byte H3 archive and all sixteen members. Its eleven image entries match each H4 reference. The embedded original H3 index and completion match the already retained originals. H3's historical native outcome is explicitly FAILED; the H4 archive does not repair or inherit native credit from it.

The child completion is `COMPLETE_WITH_REFERENCED_PARENT`, not a standalone archive. The whole H3 archive and all original parts have not been locally read by this review, and the complete two-package consumer was not run. That remains a separate required readback step.

The release proof binds the same archive job and launch nonce, observes its exact unique runtime unit removed and known cgroup absent, and records no mutations or process kills. The original PID and InvocationID were not observed before termination and were not invented. This narrow release observation does not replace the authoritative terminal result.

The independent verifier passed once on the existing local records. The original bulk-download pause state was untouched. No new native, WAN, runtime-closure or joint-release qualification is claimed.
