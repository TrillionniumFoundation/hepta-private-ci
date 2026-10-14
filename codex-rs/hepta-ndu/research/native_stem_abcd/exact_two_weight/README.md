# Hepta R13: exact two-weight entropic forward Stem

Self-contained **research-only** certificate; see PROOF.md and RESULTS.md.

Reproduce without any third-party dependencies:

```bash
python -m unittest -v test_certificate.py
python certificate.py > CERTIFICATE.json
```

Optional independent numeric diagnostics (not proof; requires NumPy and SciPy):

```bash
python numerical_checks.py > NUMERICAL_CHECK.json
python quadrature_diagnostics.py > QUADRATURE_DIAGNOSTICS.json
```

The quadrature diagnostics script also writes `QUADRATURE_DIAGNOSTICS.csv` using exclusive-create; use a fresh directory for a second run, or do not run it when the generated CSV already exists. Proof code contains no random samples or float optimizer. The strictly scoped global certificate is derived from known uniform moments, Bernstein convex hulls and a Taylor tail plus global strong convexity; it does not certify previous nonlinear R10 candidates.
