# Original v3 target creation — attempt 2

This is a prepared, separately keyed request. It has not created a target and does not establish a native test result.

The first v3 attempt stopped before its first mkdir because the original private archive was absent. Its script, key and output remain unchanged. Archive-only recovery then actually succeeded: job `1a1d0d20d4d-2564-1bcb`, complete exit0, with the full7554-byte receipt pinned by SHA256 `972452dc254fd0c11ceaed85acea76d55c4b34b0c7c62a018c3cf281a2324af3`. The original receipt and both original SDK responses are stored here byte for byte.

## Fixed creation inputs

Creation remains tied to source `4537458b51b6ca936264aecea7cfe384b941d0d1`, tree `8cbd7b269c9c39df4ee3ffcefed8473060696184`, and the existing isolated worktree. The older worktree remains at `a6717d7228045e6cb60532966f06e6e02c4a6abe`.

The target remains `/data/hepta-learn-ce434-runtime-20261112-v3/target`. The new output is `/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/build-root-recovery-4537458b51b6-v3-attempt2`, and the new key is `learn-ce434-453-private-build-target-recovery-v3-attempt2`. All three created paths must be absent; no existing path is replaced or cleaned.

## Exact extension of the reviewed script

Compared with original script `67c8ae900edfdecef3816a4cc40849be9043f7c4`, seven exact transformations change the output path and add the actual archive-only receipt binding and checks. All nine original function bodies, original source checks, /data identity and64GiB gate, historical receipt hashes, V8 checks, mkdir sequence and failure handling are preserved.

Before the first mkdir and again before success, the added helper reads the complete pinned archive-only receipt and verifies successful scope, both current source directories, the existing private directories and the complete current identities and hashes of both V8 files. Exact mtime and ctime are preserved as decimal strings. The whole before/after observation must remain equal.

The original v3 receipt schema and success state remain. Two fields add the actual archive restoration provenance: `archive_only_restoration_before` and `archive_only_restoration_after`. These are observations of the original files, not authority to execute a task.

## Separate later validation

The intended later test source is `8bf3881afa8cccff286fc58909995c96f3e0b260`. Its source check must be independent of this creation source. A later native request must verify the actual successful v3 receipt; it must not relabel a source453 creation as source8bf, use an old e5c/v2 identity, or treat the successful archive-only receipt as target creation.

No native driver or request is frozen by this package. No additional grant, budget, timeout, retry, signal, download, copy or cleanup is introduced.
