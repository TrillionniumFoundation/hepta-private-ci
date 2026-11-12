# Profile recovery checkpoint

This independent checkpoint preserves complete stored originals after the scratch executor became unavailable. It changes only recovery-checkpoints/learn-profile-037c; it does not change product source paths, the main PR branch, CALLERS, the verifier, or the blob-size allowlist.

The canonical Version V4 input gzip contains the twelve exact pre-format inputs and eleven existing actual-V3 bases. The Root progress input gzip contains its three exact inputs and bases. Their request, driver, provenance, and input manifests are preserved without editing. The earlier Version design and the five-file native diagnostic formatter inputs are historical source snapshots.

Original request snapshots retain their original NOT_SUBMITTED state. Later formatter runs were reported as exit 0; those later statuses are listed separately in RECOVERY.json. Actual formatter after files, patches, and manifests are not supplied by this first checkpoint. They will be recovered from immutable remote result payloads and verified before a separate append-only checkpoint.

Every indexed artifact was independently checked in the available JavaScript runtime against its stored exact byte size and SHA-256. Git blob identifiers are computed over the exact UTF-8 or decoded gzip bytes. Original line endings are preserved. No native tests, final 57 source tests, or full caller gate ran during this recovery. All ordinary qualification counts remain zero.

The existing source QA result from the pre-format design is not reused as a final actual-input pass. The central CALLERS proposal v1 had a recorded strict patch EOF-whitespace failure; it remains an unadopted proposal and is not silently repaired here.
