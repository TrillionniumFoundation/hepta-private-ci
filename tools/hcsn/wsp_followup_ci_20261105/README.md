# WSP archive input correction and retained CI failures

The first CI for research PR #4823 reported 44 spelling annotations inside one
gzip binary witness volume. The proposed correction appends one path pattern to
the existing `.codespellrc` skip list. It covers the 28 existing compressed
witness volumes in the frozen TRAIN certificate package. All 452 scientific
files, their manifest, all runtime sources, the action version, dictionaries and
other spelling rules remain unchanged. Ordinary source, Markdown and the JSON
part manifests remain checked.

The original report is retained at
https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41959718312/job/127022935017
and its complete decoded-log identity is recorded in `FIRST_CI_DIAGNOSIS.json`.
The 3,341 annotations outside the new scientific package are unaffected by this
pattern. No whole-repository CI success is claimed.

## Actual local verification

Official codespell 2.4.3 source and both default dictionaries were reconstructed
from their recorded Git blob identities. The executable spelling code and
dictionaries were unchanged. Only the build-generated version constant was
supplied locally. No package was installed or upgraded. This used local Python
3.12.14, not the complete CI container environment.

From an isolated repository root containing the original ignore-word file,
candidate configuration and manifest-verified copy of the scientific package:

```sh
python3 -B -m codespell_lib --count --ignore-words .codespellignore \
  --skip ./.git ./tools/hcsn/wsp_followup_20261105
```

This actually completed with exit 0 and zero errors over all 452 files. A
separate temporary Markdown spelling-error control exited 65 and produced the
expected annotation. Complete child CPU costs were 0.416179 and 0.150624 seconds,
respectively; they exclude acquisition, staging and the controlling process.
`FOCUSED_CHECK.json` preserves output lengths and hashes and explicitly marks
its portable path normalization. `SOURCE_IDENTITY.json` identifies the original
checker source. These are focused checks, not a full repository CI rerun.

The exact parser also confirmed that CLI `--skip ./.git` is appended to the
configuration in codespell 2.4.3; it does not overwrite the existing list. The
action invocation is therefore not changed. For the frozen inventory, the new
pattern matches exactly 28 binary chunks and changes no skip decision for the
other 424 files. Its shell-style digit class followed by a wildcard is not a
universal promise about every future filename.

## Remaining repository integration failures

The first run also reports a formatting error in an unchanged workflow and
compile/lint failures in unchanged `codex-rs` tests, including a missing
`DurableLedger.append_qualification` method. Their observed log identities are
retained separately. The cargo-deny job failed, but complete log retrieval was
not available, so its precise cause is not asserted.

This input correction does not repair those baseline sources, bypass their
checks, change a threshold, or declare the research PR ready to merge. Scientific
qualification remains tied to the frozen package, and native runtime software
qualification remains tied to its own two successful exact-head CI runs.
