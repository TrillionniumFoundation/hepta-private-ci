# Neuron Stem Qualification — shadow only

This directory contains executable research tools for three planned comparisons:
(1) four frozen encoder backbones, (2) four feature representations and six
low-parameter Head architectures, and (3) 64/256/1024/4096-cell scaling.

No script here can select production artifacts. The tests run without network
access or downloaded pretrained weights, and do not establish model accuracy.

## Data

Input JSONL rows must contain case_id, group_id, scope_id, task_id, split,
language, state, question, options, label and event_time. The required splits
are train, calibration, test, future, ood. Group and exact-content leakage are
rejected, and future events must follow the earlier windows.

## Commands

First generate the plan and audit the dataset:

    python3 qualification/neuron-stem/qualified_eval.py matrix --models qualification/neuron-stem/models.json --out matrix.json
    python3 qualification/neuron-stem/qualified_eval.py audit --dataset TASK.jsonl --out audit.json

Train one task-specific Head from a frozen, SHA-pinned real HF Encoder:

    python3 qualification/neuron-stem/hf_trial.py --model mmbert-small --revision FULL40HEXSHA --task-id decision-v1 --dataset TASK.jsonl --mode joint --head film --budget 2048 --shots 32 --steps 100 --output candidate.jsonl

Assess predictions against independently collected no-change predictions:

    python3 qualification/neuron-stem/qualified_eval.py score --dataset TASK.jsonl --baseline no-change.jsonl --candidate candidate.jsonl --out comparison.json

Probe an actual HF inference backend (not the Hepta production worker):

    python3 qualification/neuron-stem/scale_probe.py --model mmbert-small --revision FULL40HEXSHA --dataset TASK.jsonl --mode joint --cells 1024 --active-fraction 0.25 --repeat-fraction 0.5 --similarity medium --requests 256 --batch-size 8 --db /tmp/stem-scale.db --output /tmp/stem-scale.jsonl

## Evidence limitations

Production teacher predictions for Laya 421M / Laya Multilingual 322M,
task outcome evidence, signed NDU receipts and data permissions must be
provided independently. Jina's optional remote model code requires an
explicit, pinned, reviewed opt-in. Encoder revisions must be full commit SHAs.

The scale probe genuinely executes batched frozen Encoder forwards and
independent Cell Heads, and measures SQLite WAL clean-reopen consistency.
It does not measure production worker queues or verified crash recovery.
A first warm forward is not a cold-load observation; model load time is
reported separately. CPU/RSS data are valid only on the measured host.

Never treat reported utility IDs or measurement labels as cryptographically
verified receipts. All results remain shadow-only. Independent Evaluator,
Selector and Executor promotion boundaries remain unchanged.

Run offline tests:

    PYTHONPATH=qualification/neuron-stem python3 -m unittest discover -s qualification/neuron-stem -p 'test_*.py' -v
