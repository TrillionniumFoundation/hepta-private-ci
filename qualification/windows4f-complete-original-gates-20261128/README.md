# Complete original Windows and native gates at 4f005f9

Qualified production source: 4f005f93769847729446f9b45b31e84b13166f05.
The evidence commit changes only this qualification directory.

- Original three Windows consumers: run 46122701337, job 140910454852.
  All three full targets passed. The original no-flaky gate passed.
  Complete raw job bytes, the full 59-member artifact, and all 37 test logs are retained.
- Original six native jobs: run 46122537319, 453 step records.
  All six jobs completed successfully; complete raw logs contain no actual FAILED or FLAKY gate result.
  All seven artifact ZIPs and all 39,850 members were independently read with CRC and SHA-256 checks.

The earlier three-consumer receipt truthfully says that the independent six-job run was
still in progress when that earlier receipt was written. It is retained unchanged.
The later six-job receipt and this combined record bind the completed observations to
the same production source.

The 113,619,710-byte original owner artifact is stored as ordered raw chunks below
GitHub's single-blob limit. Concatenation in chunked-artifacts.json order restores the
original ZIP byte-for-byte; the full ZIP also remains in the owned physical archive.
All other artifact ZIPs and complete raw gzip logs are retained directly.

These results qualify the original Codex Rust/HIA integration gates at this source.
They are not a claim that the separate Runtime repository has completed all 136 public
handlers or that its active controller has been cut over to pure HIA.
Earlier failed runs and source repairs remain in the normal Git ancestry.
