# V9 — physically pay only admitted original Granite47 test forwards

**DRAFT / RESEARCH_ONLY / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL / NO MAIN MERGE / NO STEM SELECTION / NO FINALUSE / NO CELL SPLIT.**

Parent: V8 PR #2662 exact `d114809275164646ae0e8a0a978dc31fd6c4646f`. V9 adds only `qualification/stem-optimal-v9/**` and one standalone read-only workflow. It does not modify historical V1–V8 evidence or native Worker/Neuron/Control/NDU/CAS/CNS authority.

## Actual work and why it differs from V8

V8's 8/32 routing used **previously paid full 32-case model predictions**, so its counterfactual `8` was not a physical saving. V9 instead executes **two different fresh-process trials on one GitHub-hosted CPU runner**, with identical byte-pinned original Granite47 model and source, and re-pays the original gated Head's 100 Adam updates in each mode:

| Arm | TRAIN model sequences | HELDOUT model sequences | Hook-verified model forward batches |
| --- | ---: | ---: | ---: |
| Selective | 64 | **8** | **5** (4 TRAIN + 1 HELDOUT) |
| Full | 64 | **32** | **6** (4 TRAIN + 2 HELDOUT) |

The lexical control is recomputed physically from all original 64 FIT/32 label-free HELDOUT text rows in *both* modes and checked against V4's exact original original-prelabel probabilities. The fixed V8 top-two margin policy selects precisely eight low-margin cases before model loading. The selective model is never handed the other 24 heldout texts in `stem_candidate_v1._encode`. The full mode pays for all 32. The emitted original model outputs are independently checked against the archived V3 heldout learned-Head predictions within fixed 5e-4 probability tolerance; the original learned initial SHA and training budget also must match. A changed trained-weight SHA is recorded as non-bitwise parity; it is not silently claimed equal.

Stage owner downloads original immutable V3/V4 archive ZIPs and checks complete ZIP and JSON SHAs with the earlier V5 manifest. An independent late-label reviewer re-opens the exact original PolyAI BANKING77 publisher train/test bytes **after both physical prediction receipts are sealed**, replays V4 cheap predictions and checks V9 source/selected/full same-case lineage, measured forward-hook counts, cost envelope, and paired original-case accuracy/Brier. No protected test labels enter the model/Head/selection stage.

## Important limits

- The work is a **physical same-runner measurement of 8 vs 32 paid heldout Encoder sequences**, not a proven 75% reduction in total CPU: 64 original training sequences, Head training, model download/load, lexical processing and independent review still occur in each arm. Runner cache/order, different feature lengths, and non-attested wall/RSS prevent production p95/p99/energy claims. No GPU, device host attestation, training-free serving, or 4096-Cell execution.
- All labels were historically exposed in earlier V4 studies. This is **retrospective descriptive quality**, not a new prospective source/time-disjoint confirmation or independently owned NDU utility. No declaration of Stem winner is possible.
- Only Granite47 is attempted first. Models 97M/140M are controls already in V3 but are not newly paid by V9.
- An incomplete source-only job, queued physical job, unavailable pinned HF weights or incompatible model output must stay `HOLD_NO_GO`, not fallback to fixture or cached old V3 output as if it were newly paid.

Local source-only numerical regression:

```bash
python -m unittest discover -s qualification/stem-optimal-v9 -p 'test_*.py' -v
python -O -m unittest discover -s qualification/stem-optimal-v9 -p 'test_*.py' -v
```

No production authorization, no `main` merge, no quality-based new-model selection, no physical Cell Split or FinalUse is requested.
