# HPCA real CPU LoRA clock comparison — actual model training, exposed prompts

**Status: HOLD_NO_GO / DENY_ALL. Executed 2026-11-10.** This is a
non-simulated pretrained-model forward/backward and adapter checkpoint
experiment, not original Owner training, independence, production adoption or
neuroscience efficacy. The original synthetic HPCA findings in EVIDENCE.md
remain unchanged.

## Actual experiment and design

An authenticated operator host ai395 (AMD Ryzen AI MAX+ 395) ran the locally
cached SmolLM2-135M-Instruct 134,515,008-parameter causal language model in
PyTorch 2.9.1 CPU float32. Four seed pairs 11,17,23,29 each trained a rank-4
q_proj LoRA adapter in 30 layers. The adapter has 138,240 trainable parameters,
split into equal 69,120-element early/late groups.

Each arm received the same 12 example IDs, same order, 12 genuine AdamW
optimizer steps, LR=0.001, precision, pretrained model, tokenizer, labels and
exposed source. Uniform clocks updated the early/late group 6/6 times;
heterogeneous clocks 9/3. Each step updated one group, so both write 829,440
parameter-elements per run. This compares an artificial two-group clock,
NOT seven Hepta lineages or a real Q24 credit signal. No B/C hyperparameter
tuning was performed. Data came from an ALREADY PUBLIC fixed fixture from
the prior SmolLM2 study; not a prospectively held-out independent evaluator.
B was the fixture's public evaluation, C eight operator-written yes/no facts.
These are exposed probes, not paid or delegated external tasks.

| Accuracy | Frozen base | Uniform seeds 11/17/23/29 | Heterogeneous same seeds |
|---|---:|---|---|
| Public B (4 questions) | 3/4 | 2/4,2/4,3/4,3/4 | 2/4,2/4,3/4,3/4 |
| Constructed different C (8 questions) | 3/8 | 3/8,3/8,3/8,3/8 | 3/8,3/8,3/8,3/8 |

Paired mean heterogeneous minus uniform = **0.0** on B and C. Two seeds
regress on B versus unchanged parent. This is negative preliminary evidence:
do not deploy either trained candidate and do not infer superiority or
statistical equivalence from four paired seeds and tiny disclosed data.
The NoUpdate recommendation is research-only, not a signed original
Agentd StageOwner decision.

## Immutable execution receipts and costs

- Exact HPCA #5739 Git parent: 15daf24ef21e9d038919fef53b82e3a6fb70358d.
- Original heptaruntime job: 1a1c74dc75f-be2a-6e, exit 0, stdout 522 bytes,
  stderr 0, no truncation; independent checksum and invariant reread:
  1a1c74fbe00-be2a-78 (also exit 0).
- Source Python SHA-256:
  0b6f2cb893ee1909adcd88fe4381560ad337a0fe59dd886548b665bc95c0d084
- Raw archive real_cpu_clock_v1_RESULT.json SHA-256:
  caf20e60f0e0dc09b78b9c5433727dd028a2b6627c945d8dee7b54c238a66615
- Full pretrain model, tokenizer, fixture, config SHA-256 in raw JSON.
  Per-step source ID/loss/input token count and per-arm I/O, CPU,
  forward/eval wall, checkpoint file SHA-256 and exact predictions retained.
- Eight real training arms, 96 optimizer steps, 6,635,520
  parameter-element updates, 20.0698 seconds summed arm wall,
  70.29 total reported process CPU seconds, 1,267,876 KiB
  process peak RSS. Host quota 600% CPU, 10 GiB memory,
  nice 10, 900-second timeout. GPU was not used.
- Each saved local adapter was reloaded into a newly initialized base
  object and reevaluated. All B/C rounded probabilities matched
  (maximum recorded absolute difference 0.0). This is model-file reload,
  not native owner process cold recovery or durable Root evidence.
- Adapter binary checkpoints remain on the operator host, **not in this
  GitHub PR**. The CI here verifies published JSON/source structure only,
  without installing Torch or redoing a training run. Local digest comparison
  does not independently attest who created an effect or trained a model.

Reproduction needs the local pinned-base directory and already-exposed
experiment-plan.json, plus torch, transformers and peft installed:

    python native_lora_clock.py --model PATH_TO_PINNED_BASE \
        --fixture PATH_TO_EXPOSED_PLAN --out NEW_OUTPUT_DIR \
        --seeds 11,17,23,29 --steps 12 --threads 4

Remaining HOLD_NO_GO: owner-attested source/action/feedback chronology; real
ACT/CTRL dense-sparse delayed outcomes, full-energy/resource matched clocks,
MEM typed replay deletion and retained old tasks, genuine independent B and
later different C owner effect, old/OOD multiple-seed confirmatory testing,
2x2 Core-by-NDU comparison, authorized NoUpdate/Adopt and owner cold restart.
No production permissions, models or native owners were changed.
