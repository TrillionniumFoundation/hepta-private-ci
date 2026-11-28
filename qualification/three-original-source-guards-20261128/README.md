# Three original source guard corrections

Base: `85ccf3305e34c90d3d10bdb1a6294d4e6adcf893`, tree
`a8d4c0fd1f523d6214bbe9e000b321834194ae34`.

The original repo-checks job 140889636263 ran the complete privileged caller
checker successfully: 6,272 Rust files, 257 boundaries, 257 inventory entries,
236 protected files, and `authorityGranted=false`. Its subsequent 125-method
Python regression suite failed three methods because their independent expected
inputs had not followed the actual paired production callers and human-input
signature. The original failing log is retained in full.

The source delta contains eight added and three removed lines:

- The independent kernel inventory names the actual paired admission and first
  enrollment callers of the original registry CAS.
- The independent bootstrap expectation names the actual paired startup caller
  of the existing private sealed-bytes helper.
- The Notes mutation fixture targets the actual human check, including
  `OriginalHumanInput::First`, so removing that check reaches the original
  protected-source verifier.

The original comparison, mutation, unexpected-caller rejection and protected
source checks remain active. Production Rust, the caller checker, its lexical
helper and `CALLERS.toml` retain the exact base bytes.

## Executed verification

The three original methods each passed once, with no failures, errors or skips.
Command time was 5.330905277049169 seconds; source preparation was
6.528908767970279 seconds; the complete driver took 14.067465653875843 seconds.
The command had a prospective 60-second limit and six seconds for cleanup.

The private source context contained every one of the base's 6,272 Rust files,
the complete original manifest and checker/helper, and the required original
Python modules with this three-file delta. The 6,265 baseline raw files and 23
exact changed Rust blobs were verified independently before assembly. All
6,279 input files matched their frozen hashes after the command. This was a
complete source context for these methods, not a claimed full Git checkout.

The original `just fmt` entry completed in 0.24806702393107116 seconds. Its
actual scoped selection reported no formatter for these QA paths; no Ruff
execution is claimed. The three postimages remained byte-identical.

An earlier Git-object setup probe did not complete. Its owned terminal was
closed, with exit -15 and a complete empty output archive confirmed by the
original terminal owner. No tests or Cargo commands ran in that attempt. The
successful source assembly used pinned existing raw files and verified changed
blobs without another Git lookup.

## Retained evidence and limits

`NATIVE_ORIGINALS.json.gz` retains the prospective input bundle, all input
hashes, driver, before-execution record, result and complete stdout/stderr.
`HOSTED_AND_REVIEW_ORIGINALS.json.gz` retains the full original failed job,
two further independent CI observations, exact merge metadata, source
preimages, formatter result and setup refusal. Every member includes its byte
length and SHA-256; `MANIFEST.json` pins the published files.

The two additional CI logs concern the source-head architecture job at
`1d3be13f539e627af59e423909f7f81aefe037f0` and Linux Clippy at merge
`3e30f3c261214d953c33f06baf0b0db6bd5f0b0d`. The latter's tree equals the base
tree above. These observations keep their own source identities.

This correction establishes the three source controls only. The entire
125-method suite was not repeated locally, and later combined source revisions
require their own CI evidence. There were zero Cargo commands and zero model
fits; all existing experiment and native-command ceilings remain unchanged.
