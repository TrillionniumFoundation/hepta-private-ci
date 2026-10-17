# V22 — P0 physically observed Qwen loader correction + root-isolated blinded evidence review

**Research only · DRAFT / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL · no production/model selection/main merge.**

## Immutable lineage and actual observed hosted failure

This adds narrowly scoped research changes to PR #2552, frozen V21 head `c22ce1b1bec634112925481c3d46fad16de1f8c8`. Existing V17 original 135M Reader, V19 native Qwen3 reference design, V20 pinned material/token preflight, and V21 human-evidence intake are preserved except for the explicitly diagnosed model-loading call below. No protected main, native Neuron/Worker, NDU/BSDE solver, CAS/CNS or FinalUse ownership changes.

**Actual GitHub Actions run [38925755341](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38925755341), job `117156535686`, completed FAILURE.** The complete source chain ran on original ten-root LoCoMo; official Qwen3-0.6B immutable revision `16706fc57485378d4ffaf54139b29ccc66ae08fa` staged seven original publisher-pinned materials. V20's real tokenizer preflight inspected 120 logical original requests with **96 distinct physical inputs**, **12,008 unique input tokens**, **13,663 logical input tokens**, and **258 maximum input tokens**. That same hosted run then genuinely completed **96 original 135M requests and 1,777 CPU model forward calls** in 92.403 seconds wall / 183.190 seconds CPU (not a newly executed V22 result).

It failed **before a single Qwen model forward** with:

`TypeError: Qwen3ForCausalLM.__init__() got an unexpected keyword argument 'dtype'`

Pinned `transformers==4.53.3` passes `dtype` as a model constructor kwarg; the admitted loader keyword here is **`torch_dtype=torch.float32`**. `v19_qwen_reference.load_frozen_qwen_model` now uses that exact loader argument without mutable weight fallback or relaxing hash checks. A strict fake `AutoModelForCausalLM` accepts only the 4.53.3 API, reproduces the old TypeError as a negative control, and proves the repaired call's expected keyword, FP32 dtype, local-only model, disabled remote code, safetensors, and eval mode. This local mechanism regression **is not proof of a successful new Qwen physical run**.

The V22 Actions workflow orders the **real Qwen generation before the already existing 135M repeat** after all SHA/Tokenizer admission, so a newly discovered Qwen forward issue does not waste an additional 1,777 already-proven 135M forwards. The same frozen 30-case/120-arm plan, private before-effect start journal, Qwen token alias reviewer, original physical 135M source reviewer and postseal publisher scoring remain required. Only sanitized derived results are uploaded upon complete terminal success; a timeout/failure or cancellation cannot certify model skill. `blocking-ci` and Architecture remain mandatory.

## Root-isolated evidence adjudication — why V21 needs one more guard

V21 generated 96 unique blinded evidence messages from 120 logical original requests. Its private owner packet contains **multiple evidence variants of the same question and related questions from the same source conversation**. Sending that whole packet to one assessor would allow evidence from a different variant to leak into sufficiency judgments. This would invalidate a causal comparison of evidence adequacy or the first-source lesion.

V22 **does not alter the frozen original evidence**. It reuses the real SHA-locked original V21 private source-ticket and HMAC identity maps and constructs an auditable, owner-private *root-isolated exposure assignment*:

- Each of 96 distinct tickets receives **two separate blinded reviewer-slot assignments** (192 proposed review exposures). The 24 logical aliases remain deduplicated and do not earn separate votes.
- Every reviewer slot sees **at most one ticket from any of the ten distinct original conversation roots**, preventing within-reviewer exposure to another arm or question from the same source root.
- The number of slots is the exact minimum `2 × max(original root's unique ticket count)` for this strict exposure rule; on real original LoCoMo the maximum was eleven, hence **22 separate reviewer slots**. Slot packet counts range from 7 to 10, 192 total.
- The complete original source-root/arm map, private HMAC key, full owner roster and secret assignment remain `0600` in a `0700` owner directory. A reviewer receives only its own source- and question-bound private packet; no arm name, original conversation-root ID, gold answer, other evidence variant or model output is included.
- An independently implemented private replay regenerates all 22 packets byte-for-byte from the parent V21 source-bound identity and detects missing/tampered/extra/reassigned records, including a forged self-resigned SHA receipt. The Git tree stores only aggregate counts and digests; no raw questions/utterances/review packets or blinding map.

**22 is a count of isolated review *slots*, not a count of enrolled humans.** Actual signed reviewers and independence/trust roots must be established outside this source-only experiment. No human assessments have been received or authenticated; no sufficient-evidence, cited-answer entailment, model correctness or NDU gain can be certified from this code.

## Actual verification and reproduction

For the loader fix and V22 source mechanics, run the unchanged inherited V19/V20/V21 tests plus the new V22 tests in normal and `python -O -S` modes. The V22 dedicated workflow runs all science/identity checks at the exact head and the full paired pretrained physical experiment only on one research-branch push. Its original material fetch and model run may fail due to actual network, device or library conditions; that is a non-waivable physical failure, not simulation success.

To reproduce the **private** exposure assignment using real prepared V21 source tickets:

```bash
PYTHONPATH=research/hepta_v17_reader:research/hepta_v19_reader:research/hepta_v21_reader \
  python -S research/hepta_v22_reader/root_isolated_review.py prepare \
  --private-v21 "$PRIVATE_V21" --output "$PRIVATE_V22"
PYTHONPATH=research/hepta_v17_reader:research/hepta_v19_reader:research/hepta_v21_reader \
  python -S research/hepta_v22_reader/root_isolated_review.py verify-private \
  --private-v21 "$PRIVATE_V21" --private-v22 "$PRIVATE_V22"
```

**No permission escalation:** `HOLD_NO_GO`, `DENY_ALL`, no Stem winner, no automatic Cell Split, no main merge, no selected Qwen/135M model, no FinalUse; no future independent source windows or real human correctness evidence.
