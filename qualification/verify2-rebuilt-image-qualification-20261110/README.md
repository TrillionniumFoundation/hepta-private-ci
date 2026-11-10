# Rebuilt amd64 image: actual OpenSSH qualification

Original run42785608600/job129725923450 completed successfully on exact source d9a2cfce60ab2eeb81e581b17ba90ca314c19355. The unchanged checked-in Dockerfile blob86aec25c was built, its resolved Ubuntu material retained, and the local config ID bound to build metadata, iidfile and image inspection before execution.

The native probe actually generated an Ed25519 key, signed and verified SSHSIG, and refused the changed message with exit255. OpenSSH package version is 1:9.6p1-3ubuntu13.20; executable SHA256 is f0b9e19ffa077d62ef6795a44d50c721f03456067a874395e015ec69c276dca6. No unresolved dynamic dependencies were printed. Private keys lived only in removed-container tmpfs.

Independent artifact verification checked all40 manifest files including the complete211754496-byte tested-image.tar, ten zero-exit command receipts, exact source commit/tree, four source Git blobs, and image config content inside the Docker save archive. Config ID sha256:bea8b1e7a719c0c00ea88001721d72ecfa1aa30ff31ab6966307b9b8e3e53b03 matches all recorded local build/inspect identities. This is a local config identity, not a published registry manifest digest.

The complete original72284511-byte ZIP is SHA256 35ae029913ac9e4256a9696a8a4c3a3466bb9ced30b5fb0a6e743aedbbd424ed, artifact13758137359 (original expiry2026-11-17). It was preserved without recompression as native file ORIGINAL-ARTIFACT.zip, library_file_id libfile_fde3_f-42d68b3c5da08191b20a8d9982381eaf_0ce1b0b60ad08191b6976e2fe4851ad1. The complete tested-image.tar has SHA25630abb7d26bdde47707c32a6d28125c2830eab52e30b908660ae3e62687a2abb1. Read the saved ZIP for image bytes.

records-without-image.zip intentionally omits only tested-image.tar and preserves the other41 original ZIP members byte-for-byte. Its MANIFEST still describes the full original artifact; the image entry is verified against the saved full ZIP, not silently marked present in this smaller archive. VALIDATION.json documents that omission and retains all verification identities. original-job.log is the complete decoded connector text, not raw HTTP transport bytes.

The earlier old-image missing-tool result and exit125 infrastructure failure remain unchanged in parent #5708. This newly built image is a separate identity. The local ai395 preparation failure (missing Buildx before fetch/build) also remains unchanged; the original GitHub result made a duplicate install/build unnecessary.

No registry publication, production activation, remote executor admission, arm64 qualification or original operator-target pass is established. All require separate exact-image evidence. Current production pins and every original test/permission/trust gate remain unchanged. Scientific HOLD and authority NONE remain; no real-task or complete physical-cost/net-benefit claim follows from this engineering result. This evidence head requires its own CI outcomes; historical source passes do not transfer.
