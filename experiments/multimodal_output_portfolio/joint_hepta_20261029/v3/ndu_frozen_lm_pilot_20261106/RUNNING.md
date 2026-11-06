# Execution contract and reproduction

The source/task freeze precedes any model forward in this pilot. The public
weights are a pretrained 134.5-million-parameter class model, not a scripted
worker or newly trained random network. The exact loaded parameter count and
fingerprints are recorded by actual inference, not assumed from the model name.

## Registered execution

Eight previously disclosed tasks from two source clusters each receive one
direct-answer episode and one model-selected-tool episode. Task order is fixed;
arm order alternates by task index. Both arms see the same public question,
answer format and applicable SQL schema. Only the tool arm sees its actual
chosen tool observation. The controller never receives expected answers or
oracle tool payloads. An exact verifier grades a completed answer and does not
feed its grade back to the model.

Strict JSON parsing does not repair invalid model output. An invalid plan,
failed tool, timeout or invalid answer is retained and scores zero. There is no
model, prompt or task replacement after seeing results. Up to 24 task model
requests are admitted; one separate execution-qualification prompt is recorded
outside that limit and outside task accuracy. All model requests start a fresh
process, including weight verification, loading and tokenization in the deadline.

The supervisor uses the existing durable intent/terminal ledger and monotonic
absolute deadlines. POSIX process termination, scheduling and final ledger writes
are not hard-real-time OS guarantees. A fatal host or ledger exception leaves an
incomplete run, whose remaining planned episodes are NOT_RUN; it is not a
completed 16-episode result. Source changes or parameter drift invalidate acceptance.

## Commands

Acquire the registered files and isolated environment with `acquire.py`, writing
separate fresh acquisition ledgers for its `environment` and `weights` stages.
The completed acquisition receipts and observed package inventory are under
[evidence/acquisition](evidence/acquisition/). Keep all failures and install logs.
Then, from the repository root:

```bash
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_frozen_lm_pilot_20261106.run \
  --runtime /tmp/ndu-local-lm --output /tmp/ndu-lm-qualification-new --qualification
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_frozen_lm_pilot_20261106.run \
  --runtime /tmp/ndu-local-lm --output /tmp/ndu-lm-pilot-new
```

Runtime identity is conditional on the supplied package inventory and platform;
the loader forces local files, safetensors, no model-repository Python, FP32 CPU,
two threads, frozen parameters and greedy decoding. It verifies the publisher's
weight hash and every tokenizer/configuration file before each request. Model
responses include actual token IDs, usage and full parameter fingerprints before
and after generation. Package installation is separate acquisition expenditure.

## Cost and claim boundary

Raw request intervals are nested in episode host envelopes. Episode CPU and wall
totals are inclusive; never add the nested intervals to them as extra costs.
Parallel environment/weight-acquisition elapsed times are also not a serial wall
duration. No external paid inference API is called. Host monetary allocation and
energy remain unmeasured, and the final cost gate stays HOLD. This is a small
language-model engineering pilot, not a frontier-model claim, an untouched test
set, NDU controller validation or a monetary net-benefit result.
