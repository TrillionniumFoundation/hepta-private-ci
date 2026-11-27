# Authentic N256 exact generator reconstruction review — HOLD

This independently frozen stage consumes the exact N256 new-export originals
bound by Draft #6334. With Python standard-library `Fraction` arithmetic, it
reconstructs all 255 birth–death generator rows, 510 positive off-diagonal
rates, 255 exact row-balance identities, lower/upper boundary flows, and the
two-coordinate reset interpolation.

The first local execution is retained as RED. It incorrectly required the
metadata's decimal display fractions to equal the NPZ binary64 values as exact
rationals, and rejected 255/257 nodes before generator construction. The
repair requires all 257 decimal fractions to round-trip to the exact NPZ
binary64 nodes, records the representation deltas, and uses the NPZ values as
the authoritative generator geometry. No threshold changed; the RED executed
zero dynamics or matrix exponentials.

It does not import or call the candidate, oracle, NumPy, SciPy, Torch, or an
optimizer. It performs no dynamic propagation or matrix exponential and emits
no coordinate reference stream. This closes only the generator-reconstruction
review input required by #6316; provider independence review, tail and rounding
certificates, all-roster dynamic semantics, resource admission, and the full
18,225,028-record execution remain open.

The exact reconstruction does not select or change a numerical threshold.
The N256 export remains new-only, not recovered historical bytes. Historical
RED and UNKNOWN remain unchanged. Global status remains
`HOLD / NoUpdate / all_closed=false`.
