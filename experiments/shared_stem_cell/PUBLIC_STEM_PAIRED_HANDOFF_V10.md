# V10: Two real public Stem canaries → rehashed joint research handoff

**Research only. No model selection, NDU, production authorization, or learning efficacy claim.**

The V8 hosted job previously could successfully execute both mmBERT-small and
Granite 97M R2 but not produce one proof that their local model directories and
probe-input identities were rechecked together. V10 adds the physical-output
join; it does not fabricate missing V8 results.

Run the new CLI only after **both** physical jobs returned success:

```bash
PYTHONPATH=experiments/shared_stem_cell python3 \
  experiments/shared_stem_cell/public_stem_pair_handoff_v10.py \
  --mmbert-root /tmp/hepta-public-v8/mmbert-small \
  --granite-root /tmp/hepta-public-v8/granite-97m-r2 \
  --output /tmp/hepta-public-v8/paired-handoff
```

Each input must retain the exact V8 `pinned-plan.json`,
`material-receipt.json`, `physical-receipt.json`, and full `model/` directory.
V9 rehashes every declared model and tokenizer file and rejects unknown files,
size drift, candidate mismatch, symlinks and unbound source identity. The V9
handoff now demands the V9-versioned input-probe hash and count even when run
in isolation. The V9 pair gate then requires **both** candidates with identical
probe inputs. A missing or failed arm blocks all joint output.

V10 atomically writes five JSON files: one pair summary, two V5 model profiles
and two non-authorizing provenance/linkage reports. No weights are copied to
the output, and the existing Actions uploader excludes `model/` paths.
V8's workflow invokes this join only if both real candidates succeed; its
offline test job also runs the V9 and V10 regressions.

**Not established by this result:** publisher-attested source identity,
independently verified physical inference, no-change baseline, identical
training budgets, future held-out utility, OOD calibration, NDU promotion,
or 64–4096 Cell production performance. All outputs explicitly retain
`production_accepted=false` and `authority=DENY_ALL`.