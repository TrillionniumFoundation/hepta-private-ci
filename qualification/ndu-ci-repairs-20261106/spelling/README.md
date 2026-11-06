# Exact technical spelling entries

The failed Codespell job on source commit
`cb5019ae86bc52c9baff27858a3ee21cafc89ac5` reports five locations containing
four distinct technical lines. One regex recognizes the words cache and caching
in Python and in two sealed JSON protocols. The other two lines use a local Rust
decoder count variable. They are intentional expressions, and the evidence files
must retain their original bytes.

The change appends those four full lines to the existing exact-line registry.
It does not add a general word exemption, skip a source file, change the
Codespell workflow, or skip other spelling checks. With Codespell 2.4.3 and the
original configuration, the original files reproduce all five findings. The
candidate produces zero findings. An ordinary spelling error still fails, and
a misspelling added to a near match of a registered line still fails. The
negative-control output is preserved in compressed receipts.

`validation.json` records source hashes, the registry hash, and results. The
compressed logs preserve original diagnostics without adding intentional
misspellings to the source tree's ordinary text scan. This local reproduction
does not substitute for the full Codespell job on the published commit.
