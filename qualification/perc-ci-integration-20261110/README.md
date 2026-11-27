# Exact PERC fixture integration

Apply only the existing #5639 `.gitattributes` delta to PERC #5608, retaining the
canonical JSON fixture bytes and its native digest assertion. The target preimage
is `17da38650745923743630d38d3eb0327b7a55d1f`; the reused postimage is
`d71d32c264e3bdb2be879cc6793c28ce83918149`.

The #5608 Windows shard 3 failure is job `129615749129`, at
`perception_tests.rs:12`. Actual Git checkout with `core.autocrlf=true` reproduced
the extra CR and the native payload hash mismatch; the exact path-specific LF rule
restored the 2,188-byte fixture and expected payload digest. Neighboring JSON still
used CRLF. EOL_PROOF.json retains the complete contrast.

This is a Linux Git checkout reproduction, not native Windows test execution.
Native Windows confirmation and the complete blocking CI remain pending. Existing
cross-platform test-root repairs need their own native validation; Cargo/Bazel
advisory repairs require PERC-specific resolution preserving its AWS Smithy patches.
No security check, production authority or scientific threshold is relaxed.
