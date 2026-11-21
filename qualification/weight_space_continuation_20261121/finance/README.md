# Financial source and readout audit

This source-only offline reader binds complete authenticated-read receipts to
the captured checkpoint, financial plan, training source, installed evaluator,
and original quote-chain header. It parses the small actual F32 readout and
uses its verified normalized-feature contract to calculate a conditional
Cauchy bound, without running an encoder or optimizing parameters.

The input records are private and are intentionally not included. The reader
is narrowly scoped to the captured one-row candidate whose reward was revoked,
the recorded zero-observation financial evaluation, and the selected quote-free
sealed segment. Different evidence requires a separate audit; it does not
silently carry this conclusion to another model. Raw execution-ledger replay,
local-witness signatures, canonical-owner authentication, current service
liveness, and global financial-label inventory are outside its checks.

The mathematical readout range assumes a feature norm bound. A separate range
allows norm up to 1 + 1e-6, explicitly as an assumption rather than a verified
floating-point bound for the full encoder. Both ranges describe the real
linear form, not runtime dot-product and output multiplication rounding. This
arithmetic error has not been bounded. The single-row SGD recurrence is an
analytic diagnostic of existing weights, not a new training or quality trial.
The code always stops before any financial edit or adoption.

Run the self-contained reader controls with:

```sh
python3 -m unittest discover -s . -p 'test_financial_audit.py'
```

With the separately retained, authorized receipt bundle, run:

```sh
python3 audit_financial_source.py --root /path/to/receipts --output audit.json
```

No host path, raw financial record, private identifier, or actual checkpoint is
embedded in this public source delivery.
