# Frozen a32 Wine diagnostic on a read-only host

This directory preserves all three original files from commit
`e1a4f619a5677d5cdc4f5307d1dc7cf1af61821e`, with exact Git blob and SHA-256
identities in `MANIFEST.json`. The workflow copy is outside the active workflow
directory. The maintained Wine diagnostic and its gate are unchanged.

The frozen mode has a different contract from the maintained diagnostic. It
runs one original parallel Wine suite after admitting existing host policy;
it never changes host policy, installs host Python, or writes global Git
configuration. It pins Bazel and DotSlash downloads, limits tools to separate
job-local directories, and binds Python, tool bytes and policy before, after
and at final collection. Incompatible or changed inputs produce HOLD or
invalid evidence. Its original tests remain alongside the source.

The maintained mode uses one original observation followed by four cases on
separate hosted jobs, with a final gate requiring every observation and source
provenance. Its source guard, bounded log snapshots and event records remain
in place. The read-only mode is retained separately because its fixed source
contract requires exactly the a32 parent and exactly the original three added
files. Renaming it into the current executor would violate that contract.

## Verification

The consolidation audit ran the retained synthetic contract suite: 119 tests
passed, with no failures, errors or skips. It also ran the maintained harness
suite: 97 passed. These exercise synthetic source, host-policy, tool-identity,
parser, result and evidence fixtures. They do not execute native Wine tests,
download or execute tool assets, modify host policy, or establish a native
qualification. Historical observations are not promoted to current CI results.

To rerun only the retained contract tests from the repository root:

```sh
python -I -B -X utf8 -m unittest discover -s qa/repository-consolidation/20261118/a32-wine-readonly-frozen/.github/scripts -p test_a32_wine_diagnostic.py -v
```

For an exact original source checkout, after the historical commit is part of
the consolidated history, create a detached worktree at the source commit:

```sh
git worktree add --detach /path/to/new-a32-readonly-checkout e1a4f619a5677d5cdc4f5307d1dc7cf1af61821e
```

Choose a fresh path. The historical driver still requires its exact source,
branch and hosted-run identity; copying these files over main or changing
identity variables is not a qualified reproduction.
