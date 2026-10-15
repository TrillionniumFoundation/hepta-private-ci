# V12 — Source-bound public Stem identity for V5/V10

**Research only. No pretrained efficacy, independent publisher authentication,
NDU qualification or production admission.**

V10 emits 'mmbert-small' / 'granite-97m-r2' candidate identities; V5's older
fixture family used 'mmbert_small' / 'granite_97m'. V5's original official
Granite CLS+L2 preflight recognized only the underscore spelling. A hyphenated
candidate label could reach material admission without the old label-specific
feature-policy check.

V12 binds BOTH spellings to the exact V8 reviewed public repository, model
kind, output width (384), pooling and normalization. Unknown aliases cannot
claim a trusted policy for either of these two public repositories. The
existing V6 Ed25519 and original file-inventory admission remains mandatory;
V12 rechecks the reviewed public policy **after** independent V6 admission
succeeds. The Granite official pooling is also rejected before reading any
external claim, preserving V7's fail-closed early behavior. Other operator-
reviewed nonpublic models still use the existing signed V6 path.

The V10 generated profile is tested against the V5 review policy. Offline
tests also cover renames, cross-publisher repo substitution, wrong output
width, wrong model kind and mocked caller integration. The mock is NOT a real
signature or model execution. mmBERT's mean pooling is explicitly a research
comparison baseline, not a proven optimal mmBERT representation.

Run:

    PYTHONPATH=experiments/shared_stem_cell python -m unittest discover \
      -s experiments/shared_stem_cell -p test_multimodal_public_identity_v12.py -v

Dedicated hosted CI pins a CPU environment, requires **seven** tests and
rejects skips. None of this replaces the V10 pretrained weight-forward,
V11 tied MLM physical parity, a time-sealed no-change baseline or a matched
future-window learning study. **Production remains DENY_ALL / NO-GO.**
