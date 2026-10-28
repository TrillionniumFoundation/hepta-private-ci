# Actual bf325 runtime prerequisite failures

This child of `bf32538ccb9b52e3e0a8e089983eea7e3940b6a5` installs the
existing Linux sandbox dependency `bubblewrap` and builds the existing
`codex-code-mode-host` executable beside `codex` before the complete five-package
native gate. Both actual binary hashes and the installed bubblewrap version are
retained. The sandbox, tests, deadlines, model plans, parent bytes, credentials,
and admission rules are unchanged.

## Original failure evidence

The source-head run
[40517226441](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40517226441)
tested tree `9a25fd8ccf3c13d47464c6e3cf4dffe9d9b9568f` before and after
the command. `scoped-rust.json` records exit 100 and 1,840 passed, 35 failed
tests; the native terminal summary additionally records 26 skipped tests.
The GitHub step's continue-on-error presentation is not a successful native
result. Its actual log contains both of these concrete missing prerequisites:

- The sandbox launcher exits 101 because neither system `bwrap` nor its bundled
  executable is available.
- The code-mode host tests cannot locate `codex-code-mode-host`; ordinary code
  execution also reports its missing executable path.

Adding these dependencies is a candidate repair. This source change does not
claim that all 35 failures share those causes or that a new native run passed.

The separate three-round model gate also failed. Two real rounds completed and
the third candidate's original observer refused a missing-RSS observation after
44,191,744,637 ns. The actual child later exited zero and was reaped with
58,902,700,000 ns of child CPU. The original failed observation remains failed;
post-gap PF_EXITING / zero-vsize diagnostics do not retroactively qualify it.
No child was installed, lint was skipped, and answer-EOS research was skipped.
This prerequisite-only change does not repair or relabel that observer failure.

## Readback and local checks

The exact 141,723,863-byte Actions artifact has SHA-256
`6e948cdd5d5028c62eb1b049144d3a76e5ed0f17c3fb7b370a8072d59d9df2dd`.
All 11,746 original ZIP members were read with CRC verification. The three
ordered `raw-part-*.bin` files reassemble a gzip-compressed TAR containing the
14 selected exact original terminal records and logs. `raw-manifest.json` pins
every part, archive and member. No private issuer or credential files were
extracted into this evidence set.

The unchanged local material-download, descendant-boundary and research-gate
controls passed 2 + 4 + 8 tests. YAML parsing and `git diff --check` passed.
These checks do not execute the missing hosted binaries or qualify a model.
The original complete native, ordinary, three-round, lint and research gates
remain required, and every failed or skipped outcome remains terminally visible.

The initial formatter attempt could not find `just` and is retained. After
installing the workflow-pinned official just 1.59.0, the original `just fmt`
command returned zero on an independent checkout of the same staged tree,
with before/after source equality. Its default dispatcher reported that no
changed files required formatting; this is not a full-tree Rust format run.
The actual command record and 73-byte output are retained separately.

## Recovered delivery and new local readback

The previously staged thirteen-file repair was recovered into a separate local
repository without changing its original worktree. Every changed file matched
the original size and SHA-256 manifest, and the recovered index tree was exactly
`a6bdae3707fc5d248343552b3ed8b3b998d05c63` before adding this readback. This is a
recovery of the existing repair, not a newly successful native experiment.

The [new readback](recovery-20261027/exact-recovery-readback.json) verified all
fourteen archived raw members and compared the parsed complete workflow with
the original `bf32538` workflow. Only the two declared dependency-preparation
steps differ. All other steps, conditions, selectors, deadlines and qualification
outcomes are unchanged. Both changed shell programs pass `bash -n`.

The original material, descendant and research controls passed again: 2 + 4 + 8,
with their [actual command receipts](recovery-20261027/command-receipts.json) and
logs retained. These are the same fourteen controls as above, not twenty-eight
distinct tests. The default `just 1.59.0 fmt` dispatch also completed without
changing source; it has no applicable changed-language files and does not
constitute a whole-tree format check.

The original host-capacity command was actually run with the pinned CPython
3.12.3. It returned exit 1 because the observed cgroup limit is 8,589,934,592
bytes, below the original 12 GiB hosted window. The [observation](recovery-20261027/host-observation.json)
and refusal remain unchanged. No model, native owner, scoped Rust gate or
complete ordinary installation was started on this unsuitable local host.

An ordinary local clone initially failed because the retained object database
lacks a historical tree. Recovery used a read-only object alternate and only
the already verified source tree. The resulting source checkout is sparse;
it does not satisfy the existing full-checkout CI identity gate. A genuine new
complete hosted checkout must execute the original native and model gates.
The scoped thirty-five failures and third-round observer failure retain their
original failed status until such a run produces its own terminal evidence.
