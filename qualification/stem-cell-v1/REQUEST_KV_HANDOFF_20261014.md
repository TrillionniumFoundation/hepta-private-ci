# Request-local KV decoding after remote generation recovery

Remote parent: `999fbfd74bdb64f83dabce8430e80569c0b78d23` (PR #1760).
Tested Python candidate: `67efeb296a4af714919522ce55cad4719a487d60`.
Branch: `research/shared-stem-request-kv-cache-20261014`.
Research-only; no main merge, production model change or native installation.

## Prior increment is now remote

PR #1760 publishes the exact fourteen paths from the previously local-only causal
generation delivery, plus an explicit recovery note. Original historical handoff
and receipt bytes are preserved. Their no-publication statements describe that
prior session; they are not rewritten to pretend it had published. The current
375-test baseline was rerun in four processes (92/95/96/92), all exit 0. Source-slice
Git history is not presented as a full-repository ancestor.

## What executes differently

`causal_generation.LocalCausalProposer` has an opt-in generation V2 cache policy.
The default V1 policy bytes and uncached behavior remain compatible. A proposal
creates one local RequestKV session: the full prompt is prefetched once, then
only the newly appended token is sent to subsequent model forwards. Attention
masks cover past plus current tokens; position_ids/cache_position stay absolute.
A changed prefix cannot reuse the session. The next request or revision always
starts from no cache. Shared parameters are not copied into separate models.

`causal_cache.py` validates the declared number of layers, key/value tensor
geometry, CPU FP32 precision, finite contents and storage identities. Cache
backing storage cannot alias model parameters. The preflight bounds the logical
payload for the maximum declared sequence. Returned tensor backing capacity is
measured, not inferred only from numel: a small view of a large storage is charged.
The old/returned storage union is checked at each boundary. Missing, nonfinite,
wrong-shaped, oversized or otherwise incompatible caches reject, with no hidden
fallback to the more expensive uncached strategy.

The cache is closed in the generator's finally block on success and failure.
Reports retain only counts and identities, not cache tensors. Tests use weak
references to verify that the successful adapter call retains no cache objects;
changing the returned report cannot alter the session. The released flag means
adapter-owned references were dropped, NOT that the allocator returned all pages
or that process RSS fell. Arbitrary model callbacks, hooks, tracebacks or other
owners can hold their own references; this is not an OS isolation proof.

The storage union is a conservative union of two observed boundaries, NOT an
instantaneous process peak. Dynamic caches may replace and free old tensors inside
forward; attention activations and other intermediates can exceed these counts.
A model allocation can occur before its returned storage is checked. These bounds
are not hard OS memory containment, a complete KV allocator, paging or native
multi-tenant recovery. This profile handles one unpadded sequence on CPU only.

## Existing execution and source contracts stay in use

Cached generation is still the same proposer object type consumed by System2,
fixed-depth/no-search controls, paired capture and empirical NDU. No alternate
reasoning loop or critic is introduced. WorkLedger observes actual dispatched
arithmetic. The cache source joins the capture fingerprint inventory: historical
captures must be replayed with their own exact source, not relabeled current.

The loader accepts only the explicit stock GPT2 Transformers 4.57.1 DynamicCache
profile with matching layer/head geometry. It does not automatically convert an
arbitrary cache class. Stock-HF support is IMPLEMENTED BUT NOT EXECUTED locally:
Transformers and tokenizers are absent. A separate real DynamicCache/full-prefix
per-step comparison is added to the existing hf_generation_checks.py entry point;
this script is already called by the restored workflow. Neither of its two checks
executed locally, and neither is included in the source regression passes.

Official versioned interface references inspected:
- https://huggingface.co/docs/transformers/v4.57.1/cache_explanation
- https://raw.githubusercontent.com/huggingface/transformers/v4.57.1/src/transformers/cache_utils.py

## Actual numerical and work observations

The new test model is a 2,259-parameter attention network, actually trained for
180 steps on fifteen next-token prefixes from three colour tasks. It memorizes
the closed training task and revision format; this is not pretrained inference,
held-out learning or reasoning emergence. Plain and cached adapters reference the
SAME frozen model. Greedy token outputs agree for all six initial/revision inputs.

The additional diagnostic compares ten random model seeds for six incremental
steps each. All sixty per-step logit comparisons satisfy rtol=1e-5/atol=2e-6;
the largest absolute error is 3.5762786865234375e-7, and greedy token IDs agree.
This finite diagnostic is not a universal floating-point parity proof.

| Same-task control | Model forward calls | Forwarded token positions | ATen formula work |
|---|---:|---:|---:|
| Uncached no-search | 2 | 11 | 33,279 |
| Cached no-search | 2 | 6 | 18,009 |
| Uncached two-round fixed depth | 5 | 41 | 132,585 |
| Cached two-round fixed depth | 5 | 17 | 53,871 |

The revision alone changes forwarded positions from 9+10+11=30 to 9+1+1=11.
Both fixed-depth cases return `red done`; both no-search cases return `unsure`.
Cache boundary storage unions peak at 1,296 bytes for the initial proposal and
2,256 bytes for revision in this particular tiny graph. Full process peak memory
and energy are not measured. Arithmetic counts use the existing formula profile,
not hardware instructions or complete system costs. Hashing, tokenization, Python
control and cache validation have time costs even when floating work is zero.
The one-shot instrumented fixed-depth timings actually show the cached path slower
in this diagnostic. No latency speedup or proportional energy improvement is claimed.

A boundary regression chooses a cap between the observed cached/uncached counts
to test budget-stop behavior. That cap is post-hoc TEST data, not a preregistered
scientific comparison. The positive-critic integration uses SYNTHETIC support and
five real neural callbacks; it is not independent calibration of this generator.
The pair-capture test checks one retained endpoint/trace, not a completed critic
training or final task campaign. No task-group labels are used to claim independence.

## Verification and review stages

The final source passed 393 DISTINCT tests in two complete module-partitioned
runs: 375 retained plus 12 cache and 6 integration tests. Each run comprises
99/98/98/98 tests; all eight ordinary unittest processes exited 0, with no failures,
errors or skips. Exact test-ID coverage and no duplication were checked. All eight
uploaded Python blob IDs match the tested bytes. Compileall and diff whitespace
checks passed. No arithmetic registry or scientific acceptance threshold changed.

Development logs preserve the initial weak-reference test failure caused by the
mock retaining call arguments, and strict-meter refusals of the first fixture's
unregistered matmul/to/where overloads. The fixture now uses equivalent bmm and
tensor-mask operations already covered by the registry. The meter was not relaxed.
Stock-HF generation failed at import with missing tokenizers (0/2 checks); the
separate Encoder check failed with missing Transformers (0/3 checks). Neither
counts as a passing test. No full-repository/Rust/native/GPU/pretrained or hosted
CI success is inferred from these CPU source-slice results.

```sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m unittest discover \
  -s qualification/stem-cell-v1 -p 'test_*.py' -v
python -m compileall -q qualification/stem-cell-v1
# Separately provisioned exact stock-HF environment:
python qualification/stem-cell-v1/hf_generation_checks.py -v
```

The package retains source, baseline/final/failure logs, diagnostic script and
trained toy weights. The incremental patch applies to #1760; a cumulative patch
from #1757 also includes its recovered predecessor. Choose one, do not apply both.

Remaining work includes actual admitted pretrained model/task execution, validated
stock/native cache behavior, independent final outcomes, total-cost and energy
measurement, safe batching/recovery and calibrated NDU owner integration. This
change does not enable the nine-arm matrix NDU lane, multimodal generation,
1024/4096-Cell serving or 10T/100T-equivalent capability.
