# Actual 197-source maintenance attempt v7 and narrow compiler correction

Status: **SOURCE MAINTENANCE FAILED; NOT QUALIFIED**.

The actual isolated attempt used source commit `7434600f61293543f11b3ccd2e2c7102e32b3f3c`, tree `d0a887edbd797583b2ba3d08cd1bb66ea4ae324d`, and the complete 197-file manifest `b2227120620c86ce7634e97a7b11dd74ab313489`. The original qualification staging commit and Draft PR source head were not advanced by that attempt.

## Actual results

- The first and second `just fmt --base cbf6ca7dd619589be3e9e98755f185d34d0f7413` commands both exited 0.
- `just fix --locked --offline` for the eleven explicitly selected crates exited 101 after 29.817901452071965 seconds. Its actual error is E0004 at `rmcp-client/src/rmcp_client_owned_shutdown.rs`: the external, non-exhaustive `QuitReason` match lacks an unknown `Ok(_)` arm.
- The binary check was not run because the fix command failed.
- There was no command timeout or completion-unknown condition. The original reference repository remained clean at its fixed head/tree.
- All 159 dirty paths were inside the fixed 197-file scope; no untracked or outside paths were present. Both captured source maps and complete patches are identical across the formatter/fix/formatter sequence.
- The attempted local evidence commit exited 128 because the isolated clone had no Git author identity. The script restored only its own staged paths; it did not repair identity or publish a ref.
- The real maintenance PTY exited 1, with complete output and no capture error. Tests, the original full caller checker, and native qualification were not run.

## Actual postimages and correction

`FINAL_POSTIMAGES.json` binds all 197 files and the 159 changed postimages. The 756,178-byte full-index `FINAL.patch` has Git ID `7f8e1205d896062566a5f95fbdbe41195d714d9b` and SHA-256 `e776f38c799c1aee19828c33e8262963341990b6c936cfe0eed64841c4037cf0`. Independent and Root byte reconstruction both match the original captured bytes exactly. Transport and parser analysis is not qualification evidence.

The sole additional source correction adds an unknown-`QuitReason` failure arm to the actual formatted file: `829fdc44f86bcd1267f1535068bd47293966ed70` → `4c0c34579b757db415f6e7f7851b2418c8a8c987`. It keeps the four original arms, the original awaited handle, cancellation, error propagation and subsequent stdio cleanup. The corrected source has not yet been compiled in this snapshot.

The updated 197-source input manifest is `2568ae7251360b252bebd965b1aa5a7ca5014635`; its lineage is the actual formatter snapshot plus that one 97-byte insertion. The next maintenance script omits native Git publication, explicitly records that Root must transfer verified postimages, and exits 0 only when source maintenance completes without errors or unknown completion. No publication success is implied.

## Preserved limits

The original checker `7a6709691c372504ca11b5d2a74e14ba819fca8f`, typed helper `e23bb8aa42241b429ef5dbce5a4660853b66eb2f`, and original seven-package/17-Root qualification harness `096b5b69c1295560f3a6c9e0da51e2708a0c996c` are unchanged. The original 500 ms request deadline is not rearmed. No environment, credential, network or permission repair was performed.

Ordinary complete-chain / positive adoption / NoUpdate-or-rollback acceptance remains **0 / 0 / 0**. Independent C and actual daemon + Root OS restart remain unaccepted. This isolated source branch is unqualified; Draft only, no main merge.
