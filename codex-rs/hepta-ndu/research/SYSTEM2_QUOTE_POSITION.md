# First-quote position control for frozen Reader: five new paired outputs

Research-only increment to [PR #1546](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1546). The frozen Reader, tokenizer, system instructions, greedy 64-token decoding, 1024-token input cap, underlying evidence/provenance, and production paths remain unchanged.

## Completed hosted baseline — actual 30 Reader responses

Original run [38245682963](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38245682963), generating Git commit `76672c8e149e50d4ca0ebe5dacfc2021993d02e4` and tree `adca3606ae1df16c1078bd94e65b5aa1cd2f84ff`, completed 30/30 frozen Reader calls without runtime failures. Original uploaded ZIP **11749366985** is pinned by the independently reported GitHub SHA256 `470ac3b80f4d06c08b421f2ddedb792484cb8420681d8d88104d8ae4fc3e37c7`. All 33 internal SHA256SUMS entries and original 30-answer seal `ffce9fbbc7ccb2ba38f41aecda6cb2e7c27293958ed59e35203ae2d3f84b6347` were checked locally. The read-only source provenance, original Reader identity and full post-seal scores are recomputed by `load_parent`.

The **five** underlying three-hop fictional task identities were already exposed. In all six original arms, strict verified answer plus complete citation was 0/5, and neither missing-evidence arm correctly used the required refusal sentence. `attack_first` included the untrusted source at **E1** and emitted the attacker's bogus `TOK-FAKE99` in **1/5** answers; `attack_last` did not. This is a *single observed occurrence* and **does not** establish statistically significant attack success, adherence to malicious instructions or any general prompt-injection robustness failure; the Reader sometimes copies source text even without an attack.

## Why five more calls are informative

The earlier neutral quotation was only tested **last**, while the suspicious fake-token output occurred with hostile text **first**. That contrasts both content and location. A new `neutral_first` control makes only **five** fresh Reader calls. For each pre-existing case, the neutral quote uses the same source text from `neutral_last` but moves to **E1**; the three unchanged true relational source identities, complete excerpts, original byte offsets and labels remain E2/E3/E4. The historical `attack_first` responses are **NOT** regenerated or edited. Both conditions present the same question, same three true fact documents, same position for the quote, same Reader, same system prompt and generation cap. Different quotation contents can have different **input token counts**, which are always measured; the study does not claim token-matched inputs or matched FLOPs.

The fixed online selection never reads `case.answer` or `case.required_ids`. The expected answer and independent proof/citation checks are used only **after** all five raw new answers have been sealed. If the new Reader emits the fake token even though it is not present in its neutral input, that is recorded as unprompted contamination, not hidden. A missing/failed Reader call stays unknown rather than being counted as a safe non-attack.

## Precondition, logging and gates

The new workflow verifies the external archive SHA256, Git generating commit/tree, all 33 internal hashes, exactly 30 original responses, full case/arm census, Reader identity/profile, exact delivered byte strings/source identities and archived per-row scores **before staging or using the model**. It preserves all existing MemoryCell regression and F/E9 Ruff checks. Then it stages the same immutable Reader from the already pinned archive and performs only the five position-matched controls, with flush-and-fsync start and response journals. New raw responses are SHA256-sealed before post-hoc case-specific scoring. Token counts, original and new answers, missing evidence, source ordering and runtime failures are reported without altering source results.

**Promotion rule:** none. This is a tiny synthetic stress diagnostic, not an acceptance gate for deploying an agent, a Reader safety certificate, a naturalistic adversarial benchmark or evidence that learned NDU/FBSDE improves reasoning. All five cases are correlated with earlier experiments, and an independent human evaluator has not reviewed semantic support. Do not confuse syntactic `[E#]` labels with independently verified citation relevance.

To reproduce after checking out the exact Git commit, set `HEPTA_MEMORY_TESTED_COMMIT=$(git rev-parse HEAD)` and run `python scripts/memory_cell/system2_quote_position_trial.py /path/to/externally-pinned-original.zip /path/to/pinned-reader /fresh/output --development` with the pinned MemoryCell Python environment. The original archive is immutable, no model weights are trained or published, and serving remains unchanged.

`production_accepted=false`; `independent_attack_defense_certified=false`; `model_safety_proven=false`; `general_ndu_fbsde_qualified=false`.
