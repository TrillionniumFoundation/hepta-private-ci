# P12 — digest-bound offline teacher media snapshots

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO**. Stacked on P11 [#3003](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3003), exact parent \`eb7221b0e8d9833d54adf14ad7e8ee0e3bf283d8\`. No base, parent or main branch was rewritten.

## Reproducible integrity blocker

\`teacher_forward.validate_records\` computes an ordered input-source SHA256 from caller-owned text and media bytes. Previously the model processor subsequently received **those original media paths**. Media could change between the provenance hash and preprocessing, binding old evidence to different model input. The existing checkpoint inventory checks protect model files, not these mutable source inputs.

## Corrective boundary

- \`teacher_media_seal.sealed_media_inputs\` copies only validated local image/audio/video files into a fresh private temporary directory. A file must be regular, single-link, non-symlink and within the declared source root; the owner rechecks pre/post-copy file metadata, enforces 128 MiB per-file / 512 MiB per-batch limits, and copies with bounded chunks.
- The existing ordered \`validate_records\` is run on **copied bytes**, and must exactly match the original digest before Hugging Face preprocessing. Processor inputs reference only the sealed copies, which remain live through \`apply_chat_template\`, then are deleted. Text-only records use the existing fast path.
- New standard-library adversarial tests cover post-preflight mutation, hardlink and symlink aliases, private-copy survival of caller mutation, copy budgets and text-only parity. The CPU-only hermetic fake-processor integration test proves the actual \`run_forward\` entrypoint observes frozen bytes even when the original file mutates during preprocessing.
- The exact-SHA Stem Shadow workflow runs these tests both without Torch and with CPU Torch and syntax-compiles the two new files.

## Evidence and remaining boundaries

The five helper-only Python tests passed locally in a minimal isolated environment. The fake-processor integration and full exact-SHA shadow CI must run on the PR head. **No genuine EmbeddingGemma 2/T5Gemma 2 checkpoints, external future/OOD data, production GPU, independent data publisher/rights attestation, learned 150M/300M native Stem, physical forward-count, p95/p99 energy or independent reviewer are supplied by this change.** Snapshot rehashing is integrity, not external provenance.

P11's separate exact-head \`cargo-deny\` RustSec advisories and intermittent Chromium Gitiles \`libcxxabi\` HTTP 503 Bazel dependency fetch remain independent blockers. Do not waive security policy or substitute an unverified libcxxabi commit/archive. Keep original blocking CI, architecture convergence, V8 and platform Bazel checks in force; do not infer pass from ancestor SHAs.

The model and Cell plan stays frozen: 421M cognition control; EmbeddingGemma 2 Perception/Memory candidate; T5Gemma 2 encoder competitor; Hepta native 150M/300M students; only per-Cell Gate/light Adapter/Task-Action-Value heads/Local State/external Memory.
