# V9 — physically execute only eight original selected pretrained inputs

DRAFT / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL. Parent V8 exact
`d114809275164646ae0e8a0a978dc31fd6c4646f`.

V8 merely replayed historical full-32 original model predictions. V9 adds an actual
model-loading and inference experiment: read all six immutable V5 ZIPs, recompute
the exact V8 label-free top-two-margin eight-case route, load one byte-pinned
original Granite47/Granite97/mmBERT checkpoint at a time, execute 64 FIT +
**only eight selected heldout** real Encoder sequences, then perform the original
four-Head 100-update training and replay selected outputs against frozen V3
predictions and both trained/initial Head digests. Any drift over 5e-4 or an
actual different Head digest fails closed.

The experiment pays the entire 64-FIT training and full model load; **it does
not establish an end-to-end savings ratio** from observing 8 instead of 32
heldout model inputs. Compare measured on-run CPU/wall/RSS against independently
measured full-model execution under a controlled same-host environment before
claiming a throughput or energy saving. Training and load time are never
subtracted, nor is this 4096-cell target-host performance.

The prior V3/V4 TEST gold has already been exposed; this is an original
historical replay, not prospective accuracy, independent new-source utility,
causal NDU benefit or authorization. V9 emits DENY_ALL and forbids main merge,
FinalUse, CellSplit, production model selection and physical external effects.

CI: source-only normal / `python -O` tests are separate from push-only
original pretrained CPU jobs, one per model. **No result is qualified until
that exact GitHub run actually completes and its output receipts are verified.**
