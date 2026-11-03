# Exact final YAML source qualification

This evidence checkpoint leaves product source 9ae81201f2761e7217f019c40b40de952ca4579d unchanged.
Workflow 41680954821 completed all seven jobs successfully on that exact source.

| Original native package | Actual passed cases | Skipped |
| --- | ---: | ---: |
| codex-utils-yaml | 10 | 0 |
| codex-skills | 49 | 0 |
| codex-skills-extension | 175 | 0 |
| codex-core-plugins | 420 | 0 |
| codex-external-agent-migration | 166 | 0 |

All 820 cases were independently counted from every original nextest PASS
record and checked against the original final summary. This workflow did not
retain JUnit files; no JUnit verification is claimed. All original commands
exited zero under the repository's unchanged test runner and stack setting.

The complete all-features metadata contains 1,524 packages matching the exact
Cargo lock and selects the reviewed path parser, with no legacy YAML package.
The original committed Bazel lock check ran before generation, followed by
the original update, repeated check and the actual utility test target.
All four commands exited zero. The utility target ran and passed, and the
generated lock equals the committed bytes (SHA256
5a6fbcf975d99e97e5562677643f3960e34929d423d22e788c6d41a43247ae26).

All 89 recorded input paths were independently read from the exact Git
commit, including all 85 reviewed manifest bindings. Their before/after
maps and every stdout/stderr hash matched. This scope is not every file in
the repository. The seven original ZIPs are retained as bounded raw binary
parts; no archive content was executed during independent verification.

The earlier proof commit 30d65479fea3065ab19ab86c62d1fd1e2e4967e4 retains
the original small receipts/logs. This checkpoint adds the complete original
ZIPs and the separate independent byte verification, without repeating those
extracted logs or changing the tested source branch.

## Restore and independently verify

Run from a clone containing the source commit, using a fresh output directory:

```bash
python3 PATH/restore.py --output /tmp/exact-hosted-results
python3 PATH/verify.py --repo . --artifacts /tmp/exact-hosted-results
```

Replace PATH with this qualification directory. Restoration checks every
binary part, original whole ZIP and member CRC before writing the extracted
evidence. The verifier reads Git blobs and evidence only; it does not run
Cargo, Bazel, native binaries or archived code.

These are scoped exact-source results. They do not confer combined-source,
full-platform, scientific, deployment or paired-host admission. The joint
candidate and original required CI remain separate acceptance gates.
DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO remains in effect.
