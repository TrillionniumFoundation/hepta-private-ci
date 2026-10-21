# P18 — pre-projector cross-modal source snapshots

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO**. Exact source parent P17
[#3029](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3029)
at `8009deb61bb22f7e9dd2f89f9a0da06ec3c2784d`. No ancestor, `main` or production authority is changed.

## Source-level blocker

The Slotizer in P17 copied and digested each modality immediately before that
modality's projector call. A `text` projector hook could mutate or remove a
later `image` input, rewrite its claimed source digest, or change missingness
before that image was captured. An invalid late modality was also discovered
only *after* the earlier projector had already run. Earlier per-modality hashes
were correct for the bytes used, but the overall batch did not have stable
pre-projector source custody.

## P18 repair

- Complete every modality's bounded preflight, feature/timestamp detached copy,
  material-byte SHA256 and declared source digest snapshot **before** calling
  any projector.
- Freeze the initial registry and missingness for the receipt and returned
  `LatentSlots`; only project from copies of the frozen modality tensors.
- Adversarial CPU regression mutates and deletes the image input and changes its
  declared digest in a text projector hook. P18 must return exactly the original
  full-batch slots, missingness and digest, matching a clean control.
- Another regression sends an invalid later modality and requires zero earlier
  projector calls.

This is pre-hook consistency, **not** a simultaneous multi-thread/process data
snapshot or independently authenticated teacher/source evidence. A concurrently
mutating producer still needs external locking or immutable source ownership.

## Qualification and limitations

Exact-P18-head CPU Stem Shadow tests, blocking-ci (cargo-deny, Linux/macOS/
Windows Bazel), architecture convergence, V8 and provenance review are required.
No successful qualified pretrained forward, actual 150M/300M distillation,
future/OOD source attestation, 1–4096 Cell GPU timing/energy, Cell promotion or
memory authority is claimed. Frozen 421M cognition control, EmbeddingGemma 2
perception/Memory Stem, T5Gemma 2 Encoder competitor, native latent candidates
and per-Cell Gate/Adapter/Task-Action-Value/Local State/external Memory remain.
