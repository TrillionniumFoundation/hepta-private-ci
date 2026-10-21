# Exact foundation CodeQL finding review

This report reviews the forty annotations on CodeQL check `118888053804`
for source `b58d870a2c38ebee0aa0b974d9f03767c888fa7e`, tree
`5bdd6960c53a0bc9dd034865d9dfa07a3cbc73f5`. Each annotation has exactly
one matching result in original Rust analysis `1992617134` for
`refs/pull/2937/head`. The analysis contains 174 results; the other 134
results are not classified or dismissed by this report.

## Findings

`review-index.json` binds every decision to its alert number, rule, full
location, source blob, SARIF result, fingerprint and detailed review.
Thirty-three fixed values are intentional credential-store fixtures:
19 under `cfg(test)`, eight explicit integration-test cases and six cases
in the explicitly declared `iostest` example static library. The example
is not `cfg(test)` and operates test keychain entries when deliberately
run. Preserve these behavior fixtures; do not randomize them to silence
the scanner.

The other seven results are individually reviewed false positives:
the Matrix output salt buffer is fully overwritten before successful
cryptographic use; three Win32 out pointers are populated, checked for
success/null, bounded within a validated live ACL and read unaligned;
and three keyring retrieval expressions are receivers of `Vec::remove`,
whose generated model overstates the logging sink. The exact model
pack commit and Rust implementation hashes are recorded in the logging
review. An independent review concurs with those three conclusions.

This commit records review evidence. It changes no alert state, query,
path exclusion, production source, fixture or native gate. Any subsequent
alert disposition must preserve this source binding and record the
original API responses, per-alert reason and verified resulting state.
Already-fixed or differently reviewed alerts must not be overwritten.

## Original evidence

`original-reader-artifact.zip.base64` preserves the complete original
84,124-byte Actions artifact `12349956006` from run `39606595435`,
including all fifty-four inventoried responses and the original SARIF.
Its decoded SHA256 is
`4ae4accc13b7458909bc5d41743969d8621b769dfdb4cf62483554928a223656`.
Decode with a standard base64 decoder, verify that hash and then verify
each member against the included `inventory.json` before using it.
No GitHub credential or signed download URL is included.

These are source and data-flow reviews, not native execution results or
a claim that all repository security findings have been resolved.
