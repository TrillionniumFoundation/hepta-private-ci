# P2: prospective on-policy original Reader integration contract

**DRAFT / RESEARCH_ONLY / DENY_ALL / NO MAIN / NO MODEL PROMOTION**

Extends P1 (#2484), preserving its existing finite off-policy portfolio and archived negative findings from parent #2319. P2 introduces a callable **on-policy protocol**, not a bundled pretrained model, a claimed new Reader run or a bypass of Hepta's original product ModelWorker. This offline qualification adapter is **not permitted to serve as product authority**.

## Admission and execution

`onpolicy.py run` accepts only frozen original TRAIN action scores, PUBLIC task groups/buckets, a PUBLIC prompts file and an explicit SHA256-pinned local Python adapter that exports:

```python
from onpolicy import Response, Meter
def execute_reader(task_id: str, prompt: str, action: str) -> Response:
    # Must perform an actual original model forward/decoding run for this action
    # and return its real model metering/receipt; no access to test gold or
    # precomputed outputs of the unused alternatives.
    ...
    return Response(
        answer="actual model output",
        meter=Meter(input_tokens=..., cached_input_tokens=...,
                    reasoning_tokens=..., output_tokens=...,
                    incremental_latency_ms=..., full_latency_ms=...),
        receipt_digest="64 lowercase hex of original model execution receipt",
    )
```

The adapter is imported as **locally trusted executable Python code**: SHA pinning establishes byte identity only, *not* sandbox confinement, author identity or permission. Do not load untrusted adapters. It must reside in an already authorized isolated research environment, must never receive gold labels or hidden task answers, and must use the original platform-authorized model execution entrypoint. Do **not** treat this offline script as permission to make product tool/network/model calls. Model identifier, source/model weights and complete prompt/adapter versions must be fixed before execution.

The runner rejects invalid SHA identities, missing/duplicate prompts, unregistered keys, TRAIN/PUBLIC source overlap, unsupported task strata, over-budget additions, malformed Reader answers and missing original receipt digests. It invokes only selected actions, not the complete alternative slate. Its attempt is sealed by canonical SHA256. If an adapter fails mid-run, the CLI returns failure and does **not** publish an attempt. However external model calls made before the failure may have already consumed compute and must be accounted for separately; no rollback of a model invocation is claimed.

`direct` has zero **incremental reasoning** and zero **additional latency** by P1 contract, but its base model call still produces real input tokens, output tokens and full latency. `reasoning_tokens` is a **separately returned, model-reported number**, not an assertion that chain-of-thought bytes are accessible. Model telemetry must expose enough fields to avoid counting hidden reasoning twice. Input, cache and output totals are reported separately. P2's two-budget scheduler includes admitted incremental reasoning tokens and incremental latency; the complete service TCO is not optimized by that limited scheduler.

`onpolicy.py score` accepts only a sealed original attempt and separately withheld external exact-answer labels. It computes exact-match task correctness; no LLM judge, source-dependent answer normalization, or internal NDU reward can replace this external metric. The script does not provide independent signatures, provenance attestation or score-owner authentication: a real acceptance campaign needs those outside this research script.

## CLI — only when a genuine Reader adapter is available

```sh
D=experiments/ndu_tree_fbsde_gates/merton/token_portfolio_p1
python3 -W error::ResourceWarning -m unittest discover -s "$D" -p 'test_*.py' -v
python3 -O -W error::ResourceWarning -m unittest discover -s "$D" -p 'test_*.py' -v

python3 "$D/onpolicy.py" run \
  --manifest /frozen/manifest.json --train /frozen/train.json \
  --public /frozen/public.json --prompts /frozen/prompts.json \
  --policy ndu_discrete \
  --model-sha256 /not/a/path-but/64-lowercase-hex \
  --adapter-sha256 /64-lowercase-hex \
  --adapter /trusted/pinned/original_reader_adapter.py \
  --output /new/unique/attempt.json

python3 "$D/onpolicy.py" score \
  --attempt /new/unique/attempt.json \
  --gold /separate/postseal/independent_gold.json \
  --output /new/unique/score.json
```

Replace both digest placeholders with actual 64-character lowercase SHA256 strings. The example paths are illustrative and do not attest an existing, approved model. The production CI workflow runs **only constructed mock-adapter tests**, not these real-model commands.

## Outstanding scientific acceptance gates

1. Pin an actual pretrained Reader with immutable model weights/tokenizer/template/hardware/device, original objective and complete task labels withheld until after original output sealing.
2. Run **all seven policy arms** independently on matched prospective source and time groups, controlling input identity, model version, acquisition/validation budgets and decode randomness. Previously observed heldout source and historical AG News/E25 panels are not newly prospective.
3. Make the adapter metering independently reproducible; include base input/output/cache plus incremental reasoning tokens, p95/p99, actual CPU/GPU/wall/energy where available, verifier and strategy-training costs. Reject missing or inconsistent meters instead of estimating fictitious usage.
4. Compare exact external correctness and total lifecycle cost. NDU should **not** be promoted if a cheaper fixed, ordinary neutral or identical-profile comparator matches task outcomes. A risk-profile change is not evidence of a better mathematical optimizer.
5. Preserve the original Hepta ModelWorker, Control/CNS, FinalUse, protected blocking CI, independent signed custody, failure/restart and artifact selection authorities. No main merge or serving activation follows from this research-only implementation.

**Observed status at authoring:** neither a new real Reader execution nor independent host-certified metering has occurred. Tests of this package use synthetic task panels and mock Reader adapters exclusively.
