# Proposed matched-capacity research gate

This is a research-only, `DENY_ALL` candidate-geometry preflight. It is not a trained model, signed weight, production route or NDU acceptance.

For a fixed shared feature width `d`, proposed Cell hidden width `h`, private dense affine input adapter, binary Head and fixed Q24 identity temporal-to-activation projection, the counted scalar totals are:

- V2: `(d+3)*h+1`.
- V3: `(d+6)*h+1`.
- Diagonal SSM: `(d+5)*h+1`.
- Low-rank minGRU: `(d+5+4*r)*h+1`.

All candidates must consume the same frozen source features. No fake padding, zero-use weights, or copied optimizer states are allowed. The extra adapter is a *new proposed operator*, not supported in the existing trainer without implementation. Actual tensor files and full memory/compute parity remain unverified.
