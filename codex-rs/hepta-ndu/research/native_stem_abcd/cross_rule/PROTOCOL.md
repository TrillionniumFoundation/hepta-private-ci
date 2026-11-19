# R11: retrospective cross-rule corroboration, not a new acceptance gate

Parent R10 PR #1898 at f8cb099a79fa2bd7e3b40ad49113cf7c8b6185e3. This is a new read-only audit of ALL 96 frozen R10 outcomes, not a new fitted model, blind registration, or new independent training distribution.

**No change** to historical R10 qualification, weights, threshold, seeds or checkpoints.

Frozen historical gate: max(CC5,CC9) <= 0.04850 and |CC5-CC9| <= 1e-6.
Independent corroboration diagnostic: max(CC9,GL9,CC17) <= 0.04850 and spread(CC9,GL9,CC17) <= 1e-8.
The latter is specifically **not** a rigorous quadrature error bound, a new scientific acceptance criterion, or a certificate of global neural-model optimality; higher-order rules may share bias.

Input: original R10 read-only audited SCORES.csv with 96 rows and all four cost columns. Reject missing rows, duplicated runs, non-finite values, and any mismatch between reconstructed and recorded historical qualification. Output complete 96-row classification and grouped denominator, never replace the source. Run with:
```bash
python cross_rule_audit.py --input SCORES_R10.csv --out /tmp/new_audit_dir
python -m unittest -v test_cross_rule.py
```

To claim a **rigorous** continuum result in a later stage one must additionally establish a valid uniform error bound for the actual recursive neural-integrand family, accounting for parameter domains, environment recursion, derivative or interval enclosure, and roundoff; merely comparing CC9/GL9/CC17 is insufficient. No original workflow, production model or deployment owner is modified.
