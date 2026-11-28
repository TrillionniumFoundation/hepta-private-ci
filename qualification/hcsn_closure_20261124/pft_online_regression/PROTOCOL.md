# PFT online regression gate

This maintenance stage follows base
`a2ae528edcaa33a0ab4ec3b296c276a2191b8d8d` (#7207). It creates a recurring
synthetic engineering gate; none of its runs add to a historical scientific
qualification, change numerical thresholds or consume old experimental budgets.

## Fixed scope

Load only the four named unittest classes: LedgerTests (4), CodecTests (5),
PeerTests (4), BinaryPeerTests (4). Require every expected test, refuse skips,
stop after the first failed suite and retain full logs and recorded observations.
Do not discover other tests or invoke any historical qualification/experiment
CLI. In particular there are no original cache, E1-E6, DEV/final or user inputs.
The existing synthetic seed, fixtures and numerical assertions remain unchanged.

The workflow runs on matching pull-request changes and main-branch pushes, or
explicit dispatch. Check out the exact event head and verify actual HEAD,
tracked source bytes and a clean checkout before executing. Capture every test
source and core dependency, runtime versions, SQLite/NumPy configuration,
thread settings and GitHub run identifiers. Recheck source hashes and HEAD
afterward. Output lives outside the checkout and artifacts upload on failure.
Formatting compares the exact event base/before commit (dispatch uses its head),
then explicitly checks the ten PFT implementation/test files with pinned Ruff.

## Runtime and authority

Use the repository's existing pinned checkout, setup-python and upload-artifact
actions, contents:read and persist-credentials:false. Ubuntu 24.04 with exact
Python 3.12.3 follows the existing repository CI profile. Pin NumPy 2.3.5 to the
executed numerical reference and Ruff 0.15.13 for explicit format checks.
Limit BLAS threads to one. The test step has a 120-second process-group cap;
the complete job has a ten-minute limit. Do not retry automatically or erase
earlier runs. No credentials, write permissions or deployment are needed.

Before publication, rehearse this new driver once on the current local
Python 3.12.14 / NumPy 2.3.5 dependency capsule, explicitly recording its actual
local Git head and file hashes. The local capsule is not a hosted Actions run
or a full repository checkout. Preserve the first outcome separately from any
later Actions result; a failed rehearsal requires retained evidence and a
source correction. Register this protocol and freeze the driver before that
first invocation. Run official just fmt and Ruff after local execution, retain
AST comparison and do not repeat the local suite solely for formatting.

This workflow provides regression evidence. It does not modify branch protection
or merge the staged research branches. It proves no source authenticity,
production adoption, useful-work rewards, learned topology or training speedup.
Runtime observations do not certify a complete transitive binary closure.
