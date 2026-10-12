# Does the frozen Reader solve even a single grounded relation?

Research-only extension to Hepta System2 PR #1546. No new model, Adapter,
Encoder, solver, NDU/FBSDE backend, or production path is changed.

## Why this is the next controlled experiment

The completed pinned 100-attempt multi-hop frozen Reader run **38230686420**
(artifact **11743040489**, ZIP SHA256
`7a0cb798418e7b00ac5258c26617f05e547be9f4c428bb82fb13428ec98647e2`)
ran all model calls and passed its full Python/ruff checks. The Reader failed
**every** strict ground-truth-answer-with-supporting-citations condition, even
when joined retrieval supplied all necessary sources for all twenty questions.
It also refused **none** of the forty zero/insufficient-evidence inputs. This
is NOT evidence that adding another Cell, tree search, NDU head or FBSDE
integrator will fix answer generation.

**Hypothesis ladder:** Can the same frozen Reader correctly read and cite ONE
clearly matched device/token relation? Does adding two truthful unrelated
relations hurt? When the correct relation is missing, does it abstain, or
copy an attractive unrelated token? If single-hop also fails, failure should
not be attributed solely to compositional reasoning.

## Fixed cohort and immutable model

Reuse exactly the **twenty device/token worlds** in the completed experiment.
For each original question about a *project*, register a new question about
its target *device*. The new question asks for the clearance token in an
explicit single document, with no multi-hop chain necessary. The correct
answer is generated with the synthetic world; selectors never receive that
gold answer. The source facts, scopes, original bytes, observation timestamps
and pinned Reader inventory remain unchanged.

Four arms, twenty distinct questions per arm, **80 planned frozen Reader
calls**:

1. `single_fact`: one direct device -> token relation labeled `E1`.
2. `fact_plus_distractors`: same direct relation plus two unrelated, truthful
   device -> token relations, with target relation retained as `E1`.
3. `distractors_only`: three unrelated device -> token relations; correct
   target relation absent.
4. `no_evidence`: no evidence; source history still registered and bounded.

The exact selection algorithm consumes *only the question and original source
facts*, not the generated target token, gold source ID, or model output. Its
complete per-question proof is checked in source tests. There is no adapter
fitting, training data collection or search-budget modification.

The frozen Reader uses the same `bundle_reader.FrozenBundleReader`, system
prompt, decoder (`max_new_tokens=64`), 1024 full-input-token limit, pinned
inventory `afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c`
and Reader profile
`e021a4b0de6103aa7c823c8987f865b1b19db68f9cc66544890e45b90d40a8e3`
as the completed model. No prompt tuning or new Reader download.

## Exact scoring and failure handling

All raw Reader strings, original delivered evidence and model/token cost
receipts are persisted and **sealed before scoring**. For sufficient
single-hop evidence, a useful grounded answer must include **exactly one**
valid token identical to the registered target and a syntactically valid
`[E#]` citation referencing the *target relation*, not just any decoy. Token
mentions without citations remain separately counted and are NOT certified
answers. For insufficient evidence, count the **exact prescribed refusal**;
merely copying another token is an unsupported answer, not correct reasoning.
Report grounded-answer yield and refusal quality separately. A combined
conditional-success score is retained only as a secondary diagnostic.

*Predeclared research preflight*: at least **15/20** grounded answers in the
single-fact arm AND **18/20** exact abstentions with zero evidence. No
result on a correlated synthetic grammar licenses deployment. Every source,
model, prompt and planned query stays fixed before execution. A failed Reader
call retains a start journal and a failure row; it is NOT treated as a
negative label, free computation or a correct refusal.

The original 100-call multi-hop archive is verified from a SHA-pinned GitHub
artifact **before** executing the new Reader calls. The historical artifact
is a control; its answers and native scoring remain unchanged. Repetitions
or extra arms do not create independent questions. Single-hop and multi-hop
questions differ, so no causal model-capacity effect can be inferred from
cross-task accuracy alone.

## Reproduce

In exact checkout, pinned isolated Python/PyTorch/Reader environment:

```sh
export HEPTA_MEMORY_TESTED_COMMIT="$(git rev-parse HEAD)"
python scripts/memory_cell/system2_multihop_completed_audit.py \
  /tmp/previous-100-multihop.zip /tmp/onehop/previous-audit.json
python scripts/memory_cell/system2_onehop_reader.py \
  /tmp/memory-inputs/reader /tmp/onehop/native --development
```

The GitHub Actions run retains immutable source, complete execution journals,
SHA256SUMS, frozen Reader inventory and the original completed-result audit.
The experiment is fictional synthetic English, with no independent human
sufficiency/refusal judgment, no language benchmark independence, no NDU/FBSDE
learned planning value, no general multimodal transfer and no production
qualification. `production_accepted=false`.
