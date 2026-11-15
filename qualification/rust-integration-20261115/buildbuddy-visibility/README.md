# BuildBuddy CI visibility correction

The source change removes two inherited `.bazelrc` lines: the unconditional
`VISIBILITY=PUBLIC` metadata override and the incorrect `openai/codex` repository
URL override. Every other byte of that file, including `ROLE=CI`, authenticated
remote-cache and RBE configuration, targets, and test settings is preserved.

## Repository visibility observation

A read-only GET of the [repository API](https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci)
on 2026-11-15 at 11:52:26 UTC reported `private: false` and
`visibility: public`. The description still said “Private verification-only mirror
for Hepta hosted CI”; that descriptive text does not establish access permissions.
This observation establishes the current API state, not historical repository
visibility or anonymous access to any BuildBuddy invocation. The correction removes
a forced-public BuildBuddy metadata policy; it does not change GitHub repository
visibility. The response identity and hash are recorded in `receipt.json`.

## Observed execution path

An ordinary local Bazel invocation selects no BuildBuddy endpoint. The existing
wrapper enables remote services when `BUILDBUDDY_API_KEY` is nonempty; CI supplies
its configured secret to the build steps. For this repository, the wrapper uses
the generic BuildBuddy service. The OpenAI tenant requires the distinct trusted
`openai/codex` GitHub workflow identity.

The retained CI run `43704268123` contains actual generic BuildBuddy selections
and build-result streaming URLs in jobs `132782016159`, `132782016306`,
`132782016313`, and `132782016372`. This proves that the remote build-event path
was used, beyond merely finding an unused configuration. The Linux and Windows
CI configuration chains also include the common `ci` metadata block. The full
original job logs are retained, losslessly compressed, with both original and
compressed hashes in `receipt.json`.

BuildBuddy's official [metadata guide](https://www.buildbuddy.io/docs/guide-metadata/)
and [GitHub Actions guide](https://www.buildbuddy.io/docs/rbe-github-actions/)
state that authenticated build results default to organization access and that
the explicit public visibility setting makes them available outside that
organization to people with the link. Removing the override stops this file from
forcing public visibility and permits the documented authenticated default to
apply. Actual permissions of future invocations were not tested.

## Scope and verification

This change does not modify historical invocation permissions, remove existing
evidence, change credentials, or disable the configured remote service. Anonymous
access to the historical invocation content was not tested; the review does not
claim a verified inventory of publicly visible content.

`buildbuddy-routing-review.json` records six local, pure command-construction
cases with dummy credentials only, along with the configuration expansion and
source hashes. No Bazel subprocess or remote service was invoked by that check.
`buildbuddy-runtime-evidence.json` identifies the original CI evidence lines.
The final static comparison in `receipt.json` verifies exactly the two approved
line removals. No new test or CI run was added for this configuration edit.
