# AuthBus immutable evidence chain

## Purpose

AuthBus source, documentation, product-callers and qualification evidence must
refer to one immutable candidate. A passing check for another commit, a
source-mutating workflow, a skipped required lane, or an artifact assembled from
mixed commits is not qualification evidence.

## Commit-neutral source map

`IMPLEMENTATION_MAP.json` is a commit-neutral source map. It deliberately does
not embed the SHA of the commit that contains it: such a SHA would be
self-referential and would become stale on every edit. The read-only
`scripts/authbus-evidence-projection.py` binds that map at runtime to:

- the checked-out commit and tree;
- the exact parent set and candidate kind;
- the current-implementation document;
- the verification, crash-consistency and product-caller contracts;
- all mapped source and test paths;
- hashes of the documentation and observed source set.

The generated `implementation-map.bound.json`,
`current-implementation.bound.json`, `qualification-dossier.bound.json`,
`release-status.bound.json` and `source-head.json` are written only under the
runner temporary directory.

## Required lanes

For a pull request or a manually selected pull request candidate, both lanes are
mandatory:

1. exact PR source head;
2. deterministic GitHub synthetic merge whose parents equal the declared base
   and head and whose tree equals `git merge-tree --write-tree`.

`AuthBus immutable evidence gate` fails unless both required jobs terminate with
`success`. Cancelled, failed, action-required and skipped results are rejected.

A main-branch push runs the exact main head lane. It cannot reuse a pull-request
receipt.

## Read-only qualification

Qualification has `contents: read`, checks out with
`persist-credentials: false`, writes generated evidence only below
`RUNNER_TEMP`, and verifies a clean tracked tree before and after execution.
The target-host workflow is also read-only. It no longer formats, commits or
pushes source.

## Receipt identity

`authbus-exact-head-evidence.py` emits schema
`hepta.authbus.exact-head-evidence.v2` and binds:

- commit, tree and parent set;
- pull-request base/head when applicable;
- workflow run, attempt, job, event and workflow ref;
- runner OS, architecture, image and Rust target triple;
- Cargo lock, migration, relevant-source, test-log, projection and build
  artifact digests.

`qualificationComplete: true` means every preceding command in that job
succeeded. It never means target-host, security, activation or release
acceptance; those remain explicit `false` fields.

## External evidence

Real ENOSPC, power loss, permission loss, rollback restore, owner collision,
WAL corruption, backup race, trust-generation mismatch and filesystem
publication failures run only on the protected target-host environment.
Independent security acceptance, KMS/HSM composition, activation, canary and
release remain separately governed artifacts.

## Performance evidence

The target-host evidence bundle also contains a performance receipt and bound
performance manifest. The required matrix covers concurrency 1, 8, 32 and 128,
multiple durable-state sizes, slow storage, checkpoint publication failure and
recovery/backup overlap. A report that omits any stage between product entry and
caller acknowledgement is rejected.
