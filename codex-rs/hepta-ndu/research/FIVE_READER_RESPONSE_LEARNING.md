# Reader response learning, not an always-refuse gate

Date: 2026-10-13. Source parent: `91fa6e363dbe71c126abe97b71dd225935b061ab`.
Continuation of PR #1697. These changes do not select a serving model, merge
main, supply a human reviewer, waive the five-experiment gate, or reinterpret
historical data as untouched confirmation.

## Observed prerequisite repair

Hosted reference run **38379788669**, source `642f387d...`, failed before
staging: `safetensors.torch` imported `packaging`, which the isolated environment
had not installed. NumPy was also absent. Commit `91fa6e363...` explicitly pins
packaging 25.0 and NumPy 1.26.4 and adds `pip check`, imports and a safetensors/
NumPy roundtrip BEFORE downloading the large archives. The replacement run
**38383781669** completed successfully. That validates the historical reference
pipeline, not a new Reader ability or this subsequent learning increment.

Both container and Python execution probes failed with infrastructure
`ClientError` during this increment. Therefore the new training/driver tests
are submitted, NOT locally passed; no new trained model outcome is claimed in
this document. The exact-source hosted native workflow is required.

## Executable changes

1. `five_native_historical_smoke.prepare_materials` now calls the EXISTING
   verified `stage_clean` copier. The strict official HF loader sees clean
   snapshots, while original metadata, weights and the dataset are preserved.
   Both original and copied weights stay in the excluded material subtree.
   Dataset lookup remains on the original source. There is no automatic switch
   to the separate PyTorch reference implementation.
2. `five_reader_response_learning.py` adds candidate-only LoRA on the actual
   Reader's q_proj/v_proj weights: rank 4, alpha 8, dropout 0, two epochs,
   AdamW 0.0002, fixed seed 20261013. Only assistant response tokens contribute
   to loss. Full chat-template tokenization must preserve the inference prefix;
   the entire prefix is masked with -100. No prompt/evidence loss, independent
   string-token concatenation or silent target truncation is allowed.
3. Original base tensor views are hashed before wrapping and after training
   and reload. Only LoRA parameters may be trainable. Saved adapters are
   detached, reattached from safetensors, checked for equal tensors, and the
   reloaded inference instance is evaluated. No full base embedding weights
   are included in the adapter save. Training input/cost and each optimization
   start/completion are retained.
4. `five_reader_response_trial.py` invokes these paths on the same pinned
   historical archive, using official HF/PEFT libraries, not a fixture backend.

## Scientific controls and selection

Four arms: frozen Reader, aligned-answer LoRA, permuted-positive-response LoRA,
and the nonlearned always-refuse control. The permuted arm uses the same positive
response multiset (including citation strings), the same empty-refusal examples,
initialization, epoch count and question inputs. Because whole positive responses
move, source references can become incorrect too: this is an incoherent-target
negative control, NOT pure isolation of semantic answer meaning. Actual input and
supervised token counts/costs are recorded, not assumed equal from step counts.

The existing native source-family partition is retained. Four question IDs per
training family and two per test family are chosen by identity hash BEFORE
looking at answer/evidence annotations. Source roots must be disjoint. The
selection file is sealed. Ineligible training questions (missing/unresolved or
more than three support sources, absent answer, overlong prompt/target) remain
in a census with no replacements. Their positive and empty-refusal examples
are admitted together. Multiple training families and both response kinds are
required. No held-out question, target, family, or teacher response enters the
optimizer; source SHA binds the original benchmark, not semantic correctness.

This is source-disjoint DEVELOPMENT on a previously exposed public benchmark.
It does not establish unseen pretraining content or independent future tasks.
There is no hyperparameter search, post-result best seed, test-selected checkpoint,
learned stopping threshold, independent calibration or old-task retention claim.

Every selected evaluation question retains four conditions: no evidence,
lexical retrieval, annotated support plus two distractors, and removal of all
annotated support while keeping distractor text/IDs/order/positions. An absent,
unresolved or oversized annotation makes the two oracle conditions unavailable,
not a fabricated sufficient context. These unavailable rows remain in the plan.
Removed-support examples are NOT used as negative training labels: the remaining
sources may still contain semantically sufficient paraphrases. The only new
negative supervision is the explicit no-evidence instruction contract.

## Readout and limits

All original answers and failure records seal before diagnostic target scoring.
The always-refuse control makes an unconditional abstention collapse visible.
Scores keep exact refusal, ordered/case-preserving exact answer body after only
citation-syntax stripping, and source-label syntax separate. Citation syntax and
benchmark exact body are NOT grounded-and-cited semantic judgments. The ordinary
retrieval and oracle conditions do not receive an independent sufficiency stamp.

The driver records all planned rows, unexecuted oracle controls, model/training
failures, actual decoder forwards, serialized adapters, optimizer tensor bytes,
input/response tokens and load/training/inference costs. A started optimization
without completion remains in its journal, not a free retry. A timeout may retain
its observed answer but is not scored as a successful execution. Failures are
nonzero exits with retained artifacts. Unknown FLOPs/energy remain null; wall
limits are observation-boundary checks, not kernel preemption. Whole-process
`time -v` includes staging and fitting but is not per-Cell steady-state latency.

Arm order is fixed and reported, not counterbalanced. The original smoke and
response study currently stage separate copies; that duplicated preparation cost
is paid and not hidden in a shared-compute claim. No TCO or efficiency superiority
is issued. Successful source tests or candidate learning do not open formal E1,
Group/NDU or multimodal admission; real human-reviewed sufficiency and independent
family-level confirmation remain necessary. Test tiny random Llama weights are
explicit fixtures and are not substituted for the archived Reader.

## Run

Use the repository's pinned worker requirements plus packaging 25.0,
cryptography 46.0.4, psutil 7.0.0, regex 2024.11.6 and Jinja2 3.1.6.

```sh
python -m unittest discover -s scripts/memory_cell -p test_five_reader_response.py -v
python scripts/memory_cell/five_reader_response_trial.py \
  /path/to/original-model-material.zip \
  --work /new/private-material-root --output /new/response-evidence
```

The existing `hepta-five-native-execution.yml` now runs inherited matrix,
five-contract, native, Group and new response tests, then this study, then the
original native smoke. It retains failures and excludes original/copied base
weights. It does not change global repository checks or deploy anything.

Primary implementation references:
- https://huggingface.co/docs/transformers/v4.57.1/chat_templating
- https://huggingface.co/docs/peft/v0.17.0/en/package_reference/peft_model

Five independent natural-task experiments remain incomplete. This change adds
actual response-learning machinery and testable controls; efficacy is an outcome
to measure, not a property asserted by the code.
