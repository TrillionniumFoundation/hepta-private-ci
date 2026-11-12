# Actual-source recovery checkpoint

**Status: ACTUAL_ONLY_V1_PARTIAL_GUARDS_UNCOMPILED_NO_QUALIFICATION**

This independent branch preserves the frozen initial assembly after the primary executor became unavailable. It is a data recovery checkpoint, with 105 materialized source and QA files (98 Rust, 7 Python QA) over exact parent `a96d1b821d10ed3d9e99dd06c5141f9f242ae318`, tree `f96bebefbc1e7d8187efadb62f88d524cdd18451`.

The source layers are actual-formatted C14, S12, C11, Current13, Root12, Root caller UFCS V2, Version V3 actual40, and the actual five-file native diagnostic instrumentation. The seven frozen QA postimages are included. The lib.rs mechanical merge and the explicitly approved dual test-module union retain their exact frozen bytes. No new formatting or compilation is claimed here.

The original 187-file backup is preserved in ASSEMBLY_BUNDLE.json as gzip plus base64. It contains all 105 work files, all 55 existing base files, merge evidence, and the frozen reports and patch. The gzip SHA256 and decompressed JSON SHA256 match their pre-outage identities. Every source/base byte count, SHA256 and Git blob ID was independently recomputed and matched the frozen COMMIT_FILES.json. The actual parent Git trees also prove all 55 existing base blob IDs and all 50 new-path absences.

The original bundle omitted one referenced three-byte empty-list artifact, UNCHANGED_PAYLOAD_FILES.json. Its exact text `[]\n` has been reconstructed; its byte count, SHA256 and Git blob ID match the original frozen manifest. This is identified separately in CHECKPOINT_VERIFICATION.json. The original bundle has not been changed.

## Explicitly incomplete

- The later actual Root3 postread/progress layer, Version V4 layer, and Training transaction v3 layer are not part of this initial checkpoint.
- Profile's four final QA postimages are pending.
- Central CALLERS.toml and blob allowlist integration are absent; those baseline files are unchanged.
- The full combined source/caller gate and native compilation/tests have not run on this tree. Some included QA expects later pending product/registry layers.
- This checkpoint makes no claim that the partial tree compiles or passes the combined gates.

Ordinary NoUpdate, ordinary Adopt, and complete daemon plus Root cold-recovery qualifications remain **0**. Isolated mechanism or source-mutation results from earlier inputs are not a qualification of this tree.

No existing branch or the main PR is updated by this checkpoint.
