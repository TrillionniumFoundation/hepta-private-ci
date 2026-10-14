# Shared causal generation: real checkpoint capture and hosted regression repair

Remote parent: `08cb87a6df5fb0c68b9db3f1bb00d67579bf68c4` (PR #1757).
Final Python/workflow code: `4b46d14114dc43af9d36c570efb3e03a59732193`.
Branch: `research/shared-stem-causal-generation-20261014`, PR #1758.
Research-only. No main merge, selected-model mutation, native installation or deployment.

## The execution change

`hf_causal_generator.LocalCausalProposer` loads one frozen local Llama causal LM
and implements the existing System2 propose callback. It supplies the actual task,
observations, previous candidate and feedback through the pinned chat template.
Every generated token is chosen from the model's vocabulary logits. There is no
procedural answer oracle, hidden answer injection, random-weight fallback or
implicit truncation. Prompt bytes/tokens, combined context and output tokens/bytes
are bounded. Empty outputs reject. EOS and token-budget termination are distinct.

Loading is CPU FP32, eager attention, stock Transformers 4.57.1 and local-only
safetensors. Geometry is preflighted and every materialized state tensor is checked;
omitted tied output weights require an actual shared physical tensor view. Snapshot
identity is checked before loading and again at explicit batch boundaries. All
parameters stay frozen. These are content/consistency checks, not owner signatures.

The shared instance starts a fresh prefix for every request. No KV state persists
across calls, so this is an auditable full-prefix recomputation reference, NOT an
optimized serving implementation. Sharing weights does not share the computation
of different prompts, and repeat tests do not establish concurrency or tenant
isolation against arbitrary in-process code. The last observation is cleared
before each attempted call so a failure cannot inherit a prior successful receipt.

`public_causal_probe.py` generates the initial candidates AND their revisions from
that same model, then uses the existing PairCollector, terminal sealing and common
late score join. It does not invent a high NDU value to force sampling. The reviewer
always requests one revision with format feedback; it is explicitly NOT a trained
or correct-answer verifier. The fixed exact-integer scorer runs after all endpoints
seal but in the same diagnostic process, not an authenticated independent observer.
The four arithmetic tasks are public plumbing cases, not a scientific test set.

The previous safe public acquisition helper now permits the named
HuggingFaceTB/SmolLM2-135M-Instruct model as well as the unchanged ModernBERT default.
It resolves and freezes a Hub commit and safe file inventory before transfer.
Only JSON/safetensors are acquired, with no remote code or pickle conversion.
Uploaded CI evidence includes complete outputs and failures, never model weights.

## Actual cloud evidence, not the old missing-local-dependency assumption

The parent run 38494242718 had already completed its real ModernBERT canary and
stock HF architecture checks. Its execution-regressions job 115626269062 failed
with 23 import errors: safetensors.torch needed packaging, absent from the minimal
CPU job. The session's larger environment hid that omission. Packaging is now
explicitly pinned and imported in a prerequisite smoke check. No test is skipped
to bypass the failure. Existing workflow permissions and all original gates remain.

For code `59cbf06b95013ef13b8f4a5af1f904295a2258f0`, hosted run 38496683772
passed the 360-test focused regression, three existing ModernBERT checks, three
new actual trained-Llama architecture checks and the real public causal canary.
The downloaded artifact records checkout of prospective merge
`c6b2a91376246c95387303786c7b3d87eb581b5c`, not a claim that main was merged.
The later final-code change only clears failed-call diagnostics and adds a test;
its local 361-test suite passes twice. Final-code hosted run 38497282611 also
passed 361 distinct tests (44.996 seconds) and both three-test HF suites. Its
actual prospective merge checkout is b84bf40b4a597dbe218dd641d6c2dfc41b12cb3d.
Both final-code public canaries also completed successfully. Causal artifact
11864771376 has SHA256 a7b777a8dd1d173e965c2288606e7718ceba3cb1230a55190e2dbc63b055509a.
Its raw initial and revised outputs match the first run exactly: all eight hit
the 16-token limit, all exact-integer scores are zero, and critic fitting remains
blocked. Both runs and their differing code/merge identities are retained.
No hosted result is silently inherited across revisions.

Real causal canary artifact 11864626046 contains all initial/revised outputs,
per-token observations, four paired terminals, objective scores and fitting refusal.
Its ZIP SHA256 is 15adc0c2a886326d935ec6b672d32723040b489c5719d045abfa3fb7178954ff.
Public model revision: `12fd25f77366fa6b3b4b768ec3050bf629380bac`.
Snapshot SHA256: `3ba462804b961de2a935618c3fe82b91c3d0223a6d57854d53bdd392701628af`.
Actual unique model parameters: 134,515,008. Retained weight storage: 538,060,160
bytes, including buffers under the inventory's convention, not full process memory.

## What the real outputs show

All four initial and all four revised generations reached the fixed 16-token cap.
A ninth generation exactly repeated the first initial output after intervening calls.
The revisions repeated the same capped text. Every exact-integer score was zero.
For example, the model began describing how to add 2 and 3 rather than returning
only the integer before its budget expired. This is real neural generation and
failed task delivery under the diagnostic budget, NOT demonstrated reasoning gain.
The budget/prompt/scorer was not relaxed afterward to convert these observations
into a passing task benchmark. The original records remain retained.

Unknown HF operator coverage leaves full formula work null. The existing critic
fit therefore rejects with `invalid complete paired segment work`, retains every
row, and does not produce a usable critic. Partial counts, whole-process high-water
RSS and missing energy are not relabeled as complete system cost. Success of the
canary means execution/recording worked, not task quality or critic qualification.

## Tests and reproduction

The untouched local parent passed 342 tests. The first source passed 360 twice.
Final source passed 361 DISTINCT tests twice, zero failures/errors/skips. Nineteen
new tests use an actually optimized tiny PyTorch model with a fixture tokenizer,
not pretrained weights; they cover autoregression, bounds, empty/nonfinite output,
shared-instance restart, failed receipt clearing, capture and separate scoring.
The two three-test installed-HF suites fail to import in the session container,
which still lacks Transformers. Their successful HOSTED executions are recorded
separately; the local import failures are not counted as passing or skipped tests.
Compileall, YAML parsing, source hashes and patch whitespace are checked.

```sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONHASHSEED=7347 python -m unittest discover \
  -s qualification/stem-cell-v1 -p 'test_*.py' -v
# On the pinned installed-HF environment:
python qualification/stem-cell-v1/causal_profile_checks.py -v
python qualification/stem-cell-v1/public_causal_probe.py \
  --acquire-public --output new-public-causal-directory
```

The source package includes exact local logs and downloaded hosted artifacts,
checksums, real outputs and source provenance. No pretrained weight files are
included. Repository-wide Rust/native testing is not inferred from focused CI;
this session source slice has no codex-rs checkout for just fmt.

## Remaining acceptance

The shared generator is now available to the existing callback path, but this
increment does not train Cell-specific language adapters, enable the nine-arm
matrix NDU arm, or qualify a learned verifier/critic. It does not establish
multimodal generation, multigeneration retention, native ownership/recovery,
1024/4096-Cell scale, equal-total-cost gains or 10T/100T equivalence. Next experiments
need preregistered useful generation budgets, real no-search/fixed-depth/NDU
comparisons, valid disjoint final tasks, complete accounting and independently
assessed outcomes. A four-case execution canary cannot replace those experiments.
