# Exact d1d checkpoint publication receipts

The original checker passed all 97 changed paths from 238fc484 to d1d3896e, with unchanged 512000 threshold and allowlist. The first local preparation failed before invoking that checker because a normalized commit response contained no tree; its original failure is retained. The second used actual Git commit metadata, reconstructed 158 Git objects and the exact full tree, and ran the original checker successfully. Both attempts and the source/controller/API/manifest/publication records are retained in the archive. All archived members were reopened and verified.

This is retrospective evidence for the named d1d head. It does not qualify later source changes, native E6, model learning or a whole new joint execution. The raw Git object directory is not duplicated here; the exact objects are identified and remain reconstructible from the repository and these manifests.
