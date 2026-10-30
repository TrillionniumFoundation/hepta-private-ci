# Prospective registration and actual import check

`initialize.py` creates metadata only. It never starts the science controller,
constructs a model, decodes a checkpoint or opens dataset values. All original
scientific source files are checked against the union of recovered freezes.
Every registered Python file must match a real blob in the supplied Git commit.

Registration has two explicit commits because the unchanged followup helper
requires the operational amendment itself inside its declared Git source tree:

1. Commit all executable recovery and supplement code. Run the initializer with
   that full commit and `--prepare-amendment`. It creates the prospective
   repository file `registrations/OPS_EXECUTION04_DURABLE.json` exactly once.
2. Commit the prepared amendment. Run the initializer with this new full commit
   and `--build`. It checks that executable bytes have not changed since the
   amendment's recorded code commit, then creates new A/C/core/envelope freezes,
   the canonical four-job queue, cwd policy and two configurations outside RAW.

The amendment retains `attempt_id=attempt02` only for the unchanged validator
interface. Every new operational artifact additionally identifies
`execution04_durable_20261030`. Repeated seeds add no independent samples. The
prior execution03 state and missing original preflight receipts stay explicit.

The two initial scientific freezes retain exact original A/C parent hashes and
all original scientific bytes. The common closure includes the recovery code,
cost adapter and registered postseal supplement. Later report/followup freezes
inherit this closure. No freeze claims that an unavailable original checkpoint
was recovered or that the former whole-study storage contract passed.

`import_probe.py` then runs using the literal registered venv Python path and
empty cwd, with the policy and freeze SHA supplied externally. It admits under
the unchanged 768 MiB reservation plus 1 GiB margin, imports the original science
modules and exact HCSN source modules, and invokes the original loaded-source
closure check. It creates no model instance, gradient or endpoint observation.
Its receipt reports actual runtime, resource counters and engineering cost. A
successful import is not a scientific-family memory qualification.

Root must publish and verify the source/amendment/registration identities,
persist the actual import proof and initial evidence, and then launch the
supervisor under its separate three-sample resource gate. A partial metadata
creation is preserved and diagnosed, never silently overwritten by a retry.

This restored checkout contains the original study and its pinned dependencies,
not the Rust workspace. No Rust code is changed. Python syntax and operational
semantics are checked without generating bytecode; the repository-wide Rust
formatter is not a validation claim for these changes.
