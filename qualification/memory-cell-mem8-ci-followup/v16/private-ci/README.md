# Original b054 Windows private-state evidence

This package preserves the sole original run 43035589916 / job 130573422080, exact tested source b0547d2f874c0aeb54dabd3491caa2bee49fcb0b and tree 3f89ddeff13d0af85f4abe2690699107357f1038. It contains the full original job log, both unmodified ZIP artifacts, all eleven original artifact files, source readback, exact job metadata, and an offline verifier.

The original main phases contain 34 distinct passing case IDs. A separate positive acquisition control repeats two of those cases. Two deliberately changed acquisition implementations each execute two cases and each produce one expected failure. These repeated and counterfactual cases are listed separately; they are not added to the 34 unique passes. The signed-credit case has its own complete exact-source clean-before/after receipt, original raw log, one actual passing ID and zero retries.

Run `python3 verify_private_original.py .` inside this directory to recheck original hashes, ZIP CRC and members, the complete signed-credit log inside the full job output, exact case counts, full source readback and both mutation patches. This offline audit does not rerun native tests.

These results do not qualify the entire Windows matrix, ordinary/elevated sandbox boundary, real provider, production custody or memory benefit.
