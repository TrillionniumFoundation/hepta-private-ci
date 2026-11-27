# Actual full caller failure on 4537458b51b6

The original full caller verifier completed on the fixed source `4537458b51b6ca936264aecea7cfe384b941d0d1` / tree `8cbd7b269c9c39df4ee3ffcefed8473060696184`. The verifier self-test exited 0. The actual full verifier exited 1 after 1318.145882239798 seconds, within the unchanged 4800-second budget. H published a durable, complete terminal failure; neither timeout nor cancellation occurred. The before/after source checks were clean at the same SHA and tree.

The full 191-byte stderr is preserved in `verify.stderr.original.log`. It rejects an unresolved possible `CellQ24ModelProposalOwnerV1::readback` receiver in `codex-rs/hepta-agentd/src/cell_q24_model_current_owner.rs`. The exact original terminal JSON, recorder result, launch result and H terminal SDK payload are retained separately so the original verifier exit cannot be confused with the launcher or observation classification.

This evidence records the failure before any repair. It does not validate the later private adoption dispatch child or a proposed receiver disambiguation. The original verifier, allowlist, custody, budgets and role boundaries are not changed by this evidence commit. Ordinary positive adoption, complete ordinary NoUpdate/fallback, new-session C and actual daemon/Root cold restart remain unproved.

Only the original files named by `readback-manifest.json` are included; this directory does not claim to contain every launcher/self-test log. Parent evidence retains the separate actual 443/62 source pass and native preflight failure on the same source. No main-branch merge or live owner effect is performed.
