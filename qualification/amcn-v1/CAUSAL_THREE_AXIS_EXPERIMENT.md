# AMCN task-level three-axis causal audit (research SHADOW)

**Status: `DENY_ALL`, no independent natural-task uplift demonstrated.** This
bounded, read-only protocol is a child of the newest inspected #1968 commit and
includes #2001's independent source-first scorer unchanged. The task-level
protocol supplies a stricter **external original-Reader answer handoff**, not a
new model runner, truth issuer, LLM or memory writer. It preserves #1777 and
#1968's study owners, train-only source discipline and no-promotion boundaries.

## Original design question and contrasts

A fixed pre-registered source-first question cohort uses one fixed Reader,
tokenizer, prompt, source-availability frontier and identical maximum input /
output token budgets for all nine arms:

| Arm | Distinguishing intervention |
| --- | --- |
| `strong_hybrid_rag` | **Actually executed**, externally tuned hybrid RAG baseline; not a BM25 alias |
| `frozen_shared` | Untrained shared Head |
| `learned_shared` | **Two-head equally trained unspecialized bank**, each Head fitted on pooled TRAIN sources; deterministic externally frozen per-type slot selection and one physical active Head per query |
| `learned_typed` | Two independently trained typed Heads under **equal total parameter, optimizer step and minibatch-example budgets** |
| `typed_swapped` | Exact same bank, routing deliberately reversed |
| `typed_fixed_graph` | Same typed weights, nonlearned source-bound topology |
| `typed_learned_graph` | Same typed weights, genuinely fitted relationship weights |
| `typed_graph_lesion` | Same typed weights, registered critical connections ablated |
| `unsplit_equal_graph` | Same learned graph but equal-capacity unspecialized Head bank |

The exact bank manifests declare two distinct Head SHA identities for both
pooled/untyped and typed arms, two independently trainable Heads per bank, and
exactly one active Head read per question. Both banks use the same precommitted
case-type slot; **only the typed bank may specialize training rows by type**.
This equality is asserted against the supplied physical training receipt, but
receipt issuer authenticity and actual optimizer execution remain external.

The evaluator contrasts parameter learning, type specialization, routing swap,
fixed association, learned association, critical-edge lesion, equal-capacity
unsplit graph and strong hybrid RAG **at the final complete question/Reader
answer**, not per negative-dominated evidence row. All invalid/missing/failed
model calls stay in the planned denominator. A request binds the exact final
source IDs and bytes, original question, version/scope, frozen model and prompt
identity, and one maximum token envelope. Actual token and wall costs remain
visible; equal *ceilings* are not falsely reported as equal actual compute.

## Producer/Reviewer phases (must be truly independent for any scientific claim)

1. **Freeze before outcomes**: owner-pinned eligible source cut, original
   questions, root/family alias graph, HNMF type inventory, full nine-arm
   source-first final contexts, frozen encoder/Reader/prompt/model identity,
   equal physical bank training budget, fixed/learned/lesioned graph source
   receipts and an immutable `plan.json` SHA. Gold labels or original answers
   are forbidden in this file. A printed SHA is not an authenticated issuer.
2. **TRAIN only**: run the original #1777/#1968 physical Head trainer and
   Tensor readback with labels from training roots. Sequester SELECT, FUTURE_A/B
   and RETENTION targets. Do not claim all parameter change is new stored fact.
   Only qualified source/learning owner records can authenticate lineage.
3. **Real answers**: use the same frozen pretrained Reader to generate each
   `(question_id, arm)` once. Record every raw completion (or physical failure),
   exact final source excerpts, tokens, latency, original inference receipt and
   immutable `answers.json` bytes. No final answer interpolation, revised citation
   insertion, teacher/student label leakage, or gold-selected shortlist.
4. **Separate evaluation**: after original answer SHA is sealed, supply a
   `judgments.json` census from an independent assessor, bound to each exact
   answer SHA, including failures. A judge signature/trust roster must be
   verified outside this read-only source audit; this tool never self-attests.
5. **Score**: compare by *transitively connected* source-root/family groups, not
   by questions, candidate rows, shards or rewritten family names. Alias
   edges cannot cross SELECT/FUTURE_A/FUTURE_B. Emit simultaneous conservative
   paired intervals for eight registered contrasts, original cost receipts,
   source-citation omissions and explicit **no production authority**.

## Usage

From repo root (stdlib; no pretrained model silently downloaded):

```sh
PYTHONPATH=qualification/amcn-v1 python3 -m unittest discover \
  -s qualification/amcn-v1 -p 'test_amcn_causal_task_audit.py' -v

python3 qualification/amcn-v1/amcn_causal_task_audit.py \
  --plan /approved/plan.json --plan-sha256 <EXTERNALLY_SEALED_SHA256> \
  --answers /original/answers.json --answers-sha256 <ORIGINAL_RAW_SHA256> \
  --judgments /independent/judgments.json \
  --judgments-sha256 <INDEPENDENT_ORIGINAL_SHA256> \
  --output /create-only/three-axis-review.json
```

The CLI rejects duplicate keys, NaN, symlinks, oversized inputs, source text or
revision tamper, changed Reader/prompt/request, foreign sources, missing arms,
more than final 16 source IDs, budgets inflated by an arm, false split aliases,
missing original generated answers, answer rewrites, score drift and a failed
model run counted as a success. `sha256` arguments must come from elsewhere;
self-pinned inputs alone are NOT independent attestation.

## Results already available, **not promoted**

- #1452: LongMemEval native RAG+LoRA diagnostic token-F1 was **below** RAG;
  this is not task-level semantic Reader success.
- #1968: the retrospective 44-question weak publisher reference study found
  lexical Hit@1 **14/44**, untyped **11/44**, typed **12/44**. It used earlier
  locally validated research Head material and previously exposed LoCoMo families.
  Neither typed nor untyped surpassed even lexical Top-1.
- #1777: the earlier fixed graph's expanded shortlist improved coverage in one
  diagnostic, but hard final Top-16 removed that positive signal.
- #1914: organized historical authored code evidence yielded strong Qwen
  8/8 versus Smol 1/8, with different frozen Reader/tokenizer; this diagnoses
  capacity, not a causal MemoryCell gain.

**Until actual matched natural Reader answers, independent authentic scoring,
original strong hybrid RAG, 200 effective independently admitted source-family
samples, two prospective calendar windows, citations, deletion and deployment
receipts exist, the entire causal claim remains `NO-GO`.** A synthetic perfect
fixture or successful GitHub job cannot promote a graph, Cell or model. Do not
merge this candidate into main or weaken `blocking-ci` or Architecture gates.

## Deliberate limits of this increment

This code checks original source bytes against SHA declarations and exact
recorded requests; it does not itself verify physically loaded pretrained
weights, the external model dispatch, true graph-edge learning or independent
human decisions. It does not recompute model logits from tensor bytes, conduct
reader generation, source-label semantic entailment, source-origin authority or
cross-host unlearning. All positive capability/authentication fields remain
false and citation precision `null`. Those must come from independently
executed existing owners before any future claim. The tests use six fully
synthetic question envelopes and synthetic reply strings for **contracts only**,
not new language-model inference.

## Physical frozen Reader-generation entry point (candidate only)

`amcn_causal_reader_generation.py` is a **real** opt-in local
`AutoModelForCausalLM` dispatch adapter, not an automatic benchmark launcher.
Given all nine externally frozen label-blind source/Head/graph choices, a
previously staged exact local safetensors Reader model inventory and all three
external SHA pins, it validates every original source text/revision, verifies
full Reader model and tokenizer bytes, loads weights without remote code or
network/model substitutions, and actually generates each nine-arm answer with
the same Reader, prompt, source-envelope and token ceilings. The `answers.jsonl`
append-only fsynced journal retains all raw model outputs, citations and token /
wall resource counts. `starts.jsonl` precedes each attempt; incomplete and
interrupted runs are never falsely sealed. Deliberate insufficient-input, model
and generation failures remain failed attempts, not reconstructed answer text.
The final `answers.json` is directly consumable by the independent nine-arm
`amcn_causal_task_audit.py` once a separately authenticated, independently
scored `judgments.json` exists. A local self-hash over execution receipts is
**not** a Worker signature or evidence of independently witnessed model execution.

```
python3 qualification/amcn-v1/amcn_causal_reader_generation.py \
  --plan /approved/plan.json --plan-sha256 <EXTERNAL_PLAN_SHA256> \
  --reader-model-dir /approved/pinned-safetensors-model \
  --model-inventory /approved/reader-model-inventory.json \
  --model-inventory-sha256 <EXTERNAL_MODEL_INVENTORY_SHA256> \
  --output /create-only/original-reader-run
```

The separate `test_amcn_causal_reader_generation.py` injects explicitly fake
model responses in 11 fault tests: source/prompt/Reader byte drift, invalid
model/symlink inventory, unlisted weights, excess tokens, wrong citations,
failure/cancellation journals and overwrite refusal. These tests execute **no
pretrained weights or Reader calls**. The actual pinned public pretrained Reader
model files, original source-first nine-arm plan, real physical Head/graph
coefficients, qualified strong hybrid RAG, independently adjudicated answers,
and prospective task windows are **not supplied** by this increment. The new
opt-in Runner must refuse those missing inputs; it may not silently substitute
mock parameters or a different Reader. `production_accepted=false` remains
mandatory regardless of local execution.
