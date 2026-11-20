# Final report renderer v5 — historical fact identifier compatibility

The single functional change extends the tail character class of FACT from `[a-z0-9_]` to `[a-zA-Z0-9_]`; the first character remains `[a-z]`. The original historical `native_Root2` identifier is preserved. The old renderer matched 104 of the real 105 frozen bindings, while this pattern matches their exact full set.

Three bounded tools-only controls used the real frozen report spec/template and the original unchanged equality guard: the historical mixed-case identifier matches, all 105 actual identifiers match exactly, and an added unbound identifier is still refused. No renderer build function was called, no report was written, and no archive or experiment was rerun.

Both necessary local Python dependencies are byte-for-byte v4 copies. All renderer functions and other top-level statements retain their AST, including immutable input, type/value, source/freeze/package, missing/unused fact, unresolved field and exact reference guards. The existing v4 package, original spec/cut, old66 identifiers and failed render remain untouched. This revision is an additional publication sidecar and is not retroactively inserted into the successful v4 archive.
