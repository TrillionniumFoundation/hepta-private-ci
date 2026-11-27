# Native memory: remaining gates after MEM15

**Status: unexecuted research design.** This note records the smallest next research steps supported by a read-only review. No new actor, capture, tokenizer run, model generation, or cohort was executed for this design. It requests no authorization and marks none of the proposed gates as passed.

The reviewed source is **`bbbcc63003a88d0396a9694222dc98dc8c0d59d6`**, tree `fe00b2618f39e942ec6b1a8af2d63ec585e5f892`, with `codex-rs` tree `ed240f298fa2cbb104c65054596e64e7d1e9bca8`.

## Preserve the completed studies

MEM12's original v1 scores, MEM14's separately preregistered v2 endpoint and fixed independent audit, and MEM15's capture-only protocol remain unchanged. MEM15 demonstrates the observed native A-exit/process/capture/revocation path. It contains no scored memory-benefit episodes and does not establish natural-task benefit, complete bypass isolation, production authority, or parameter consolidation.

The three original complete-body mappings require **7,565 / 7,007 / 7,029 tokens** for Attach / reader-off / Withhold, according to their retained tokenizer-only outputs. All exceed the frozen **1,024-input / 32-output-token** limits. These are admission failures, not memory-benefit negatives. The original HTTP bodies already have `tools=[]`; the main removable-at-construction overhead is the default coding-agent instructions and the automatic skills block. The adapter's exact HTTP-JSON-to-single-user-message mapping and all original bytes remain fixed.

## 1. Freeze a separate minimal native candidate

The existing source supports the following configuration surfaces:

| Configuration | Verified source meaning |
| --- | --- |
| Top-level `instructions` | Supplies custom base instructions. |
| Top-level `model_instructions_file` | Reads a nonempty instructions file; freeze its path and bytes if used. |
| `[skills] include_instructions = false` | Suppresses the automatic skills instruction block. It does not by itself disable every skill-discovery/read path. |
| `[skills.bundled] enabled = false` | Disables bundled skills through the existing bundled-skills setting. |
| `[orchestrator.skills] enabled = false` | Disables exposure of orchestrator-owned skills; its scope is narrower than all skills. |
| Top-level `project_doc_max_bytes = 0` | Provides a zero project-instruction budget; verify its effective result in the new capture. |

`base_instructions` is an internal configuration/override field, not the top-level TOML spelling to use here. The loader selects explicit override, instructions-file content, then `ConfigToml.instructions`, and marks the result as custom. Keep permission enforcement and existing authority, retry, and timeout controls intact.

The current fixture writes its own `config.toml` inside `production_episodic_provider_tests.rs`; it does not expose this minimal actor profile as an outer-wrapper option. Its process entry also accepts only `phase=capture` and expects unsuccessful C completion. Therefore the smallest implementation is a **new, explicitly versioned fixture/entry and frozen actor configuration**. Reuse the existing owner, importer, source verifier, process receipts, and adapter where their contracts fit. A later generation entry needs its own explicit behavior and evidence contract. Changing an outer environment variable alone does not qualify it.

Changing base instructions or skills injection changes the actor configuration even if the model weights and adapter mapping stay fixed. Freeze the new source commit/tree, actor text, effective configuration, model/runtime/tokenizer pins, request identities, selector, and plan before collecting its outcomes. This work belongs to a new study, with separate records from all MEM15 attempts.

## 2. Capture the complete new request

Precompile before starting the bounded listener. Retain the complete native HTTP request, exact body, exact mapping, source/profile/PLAN/SERVER bindings, A stdin/ack/OS exit, C stdin/argv/exit, and original journal. Preserve the observed one-request/no-reissue and UNKNOWN rules.

Construct the smaller request through the frozen native configuration. Do not trim captured instructions, remove metadata afterward, extract the nonce, normalize dynamic fields, or substitute another adapter representation. Reader-off and Withhold currently have differing complete bodies despite both withholding the memory text; any new equivalence claim must use actual bytes. Predeclare treatment of fresh thread/request metadata as part of the experimental design.

## 3. Require admission under the existing 1,024-token cap

Apply the pinned tokenizer and unchanged chat template to every planned complete request form with truncation disabled and no model weights or generation. Shorter instructions make admission plausible; character counts do not prove admission. Retain full rendered prompts and tensors. Any request above 1,024 tokens stops at admission, with its raw bytes preserved.

A different input budget or semantic mapping requires another explicitly frozen contract grounded in the actual model configuration and tokenizer limits. This note proposes neither change to the completed studies.

## 4. Close native causal controls, pairing, and isolation

Before a benefit cohort, the new entry needs the following gates:

- **Paired sources:** hold the same admitted A fact/source, actor, public selector, and budgets across each source's interventions. The four independently generated MEM15 nonces are process fixtures, not a paired benefit cohort. Keep A's observed exit before fresh C; the genuine owner may remain alive between tasks.
- **Complete off and retention:** reader-off leaves retained A state present; Withhold still retrieves and revalidates. Implement and verify separate full memory-off and retention interventions, including absence of alternative delivery channels.
- **Relevant deletion/replacement:** use current native source admission and valid owner state transitions. MEM15's tombstone deliberately blocks final use before a turn; it is not a deletion-then-generation benefit comparison. Corrections and withdrawals must not reuse stale receipts as fresh authority or resurrect a retired native slot.
- **Isolation:** current C has a cleared environment and separate work/home/cache directories, but no independent namespaces; the App Server retains the original agent home. Prove the proposed file, history, tool, cache, network, and owner-socket boundary explicitly. Provider-worker isolation alone does not establish isolation of the whole native C/App Server path.
- **Fixed measurement and baselines:** freeze the full-output parser before generation. The current 32-hex nonce task is distinct from MEM14's courier/color endpoint. Compare exact-KV, BM25/RAG, finite-context ICL, and uniform replay with equal declared budgets and observed costs; retain missing/UNKNOWN outcomes and fixed source denominators.

The fixture issuer remains fixture authority. A successful native process path does not promote its public fixture key to production authorization or authenticate private owner custody.

## 5. Register and run a new benefit cohort only after those gates

Freeze source count, interventions, allocation/order, primary contrast, missing-outcome treatment, confidence bounds, model-call budget, and cost accounting. Generate fresh outcomes under that new plan. Keep process qualification, admission, scored benefit, and broader scientific acceptance as separate reported results. Learned association and slow parameter consolidation remain subsequent research questions.

## Source references

All source references below are fixed to the reviewed commit:

- [ConfigToml fields](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bbbcc63003a88d0396a9694222dc98dc8c0d59d6/codex-rs/config/src/config_toml.rs) and [effective core configuration](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bbbcc63003a88d0396a9694222dc98dc8c0d59d6/codex-rs/core/src/config/mod.rs).
- [Skills configuration semantics](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bbbcc63003a88d0396a9694222dc98dc8c0d59d6/codex-rs/config/src/skills_config.rs).
- [Fixture config construction](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bbbcc63003a88d0396a9694222dc98dc8c0d59d6/codex-rs/hepta-agentd/src/production_episodic_provider_tests.rs) and [capture-only A/C entry](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bbbcc63003a88d0396a9694222dc98dc8c0d59d6/codex-rs/hepta-agentd/src/production_episodic_process.rs).
- [Original MEM15 protocol](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bbbcc63003a88d0396a9694222dc98dc8c0d59d6/qualification/memory-cell-mem15-native-a-exit-20261112/PROTOCOL.md). Token counts come from the original continuation03 archive, SHA256 `147bd82bd791c0df8376fc14678a892313de3403884b54be2c176f112917beac`, paths `attach/TOKEN_ONLY.json`, `reader-off/TOKEN_ONLY.json`, and `withhold/TOKEN_ONLY.json`.
