# Actual code-repair solver development

This adds a real code-generation and task-feedback loop to the existing common
executor. It is a development qualification on two already exposed historical
incidents, not a future benchmark, full-budget fission comparison, or evidence
that memory beats a strong retrieval agent.

The fixed solver is the official Qwen2.5-Coder-1.5B-Instruct Q4_K_M GGUF. Its
revision, 1,117,320,768-byte artifact and SHA-256 are in model_manifest.json.
llama-cpp-python 0.3.16 is built from a hash-pinned source release. The CPU run
uses two threads, an 8,192-token context, at most 768 generated tokens per call
and three calls per trajectory. There is no training, network tool or arbitrary
shell tool in the model interface. Candidate implementation execution retains
the existing trusted-candidate boundary described below.

## Common task gate

Both no-history and retrieval arms propose bounded exact text edits. The
controller turns them into complete implementation-file candidates for the
same source-pinned executor. Each original span must occur exactly once; paths,
file creation and bytes are bounded. Model JSON, edits, candidate files, actual
lint/test outcomes and the feedback for the next call are retained. A trajectory
stops at its first actual success or its registered resource budget. Failed
proposals are never silently retried or deleted.

The Ruff task requires the original 76 semantic IDs. The codec task requires
the original 21 media IDs when tools exist and a nonzero refusal when either
required media tool is missing. Codec qualification covers the selected local
workflow entrypoint and static selection constraints, not the whole GitHub job.

Each new runtime first receives an exact tool profile and must pass both
executors' positive and negative qualification. Codec uses a pinned historical
fixed source. Ruff derives its qualification control from the pinned failing
file with pinned Ruff and requires the previously qualified output hash; that
generated file is explicitly not represented as a Git-source blob. These
controls are used only in the qualification stage. Model inputs contain the
failing implementation/workflow, task instructions, optional retrieved history
and bounded actual feedback; fixed repair code and qualification outcomes are
excluded from model prompts. Before model admission, the controller checks the
complete source inventory, frozen task input, runtime tools and qualification
receipts again. This does not establish filesystem isolation from repair gold.

## Retrieval and freeze

Retrieval uses the existing BM25/code/path index. The corpus contains the two
earlier observed Ruff teaching records and selected general Python standard
library implementations. It excludes the task's known repair source. The
corpus, index, runtime profile, exact solver/executor bytes and task sources are
frozen after runtime qualification and before the first model query. Historical
availability labels are not prospective timestamps or independent source grants.

recipe.json is the fixed development design; the executed protocol adds the
actual source and environment identities. The registered task and arm order is
serial and fixed. A fresh model process serves each trajectory; prefix caching
within it and OS page caching across trajectories are reported limitations of
the measured costs.

## Execution and accounting

The dedicated workflow runs only for the explicit qualified-solver branch
prefix or manual dispatch. It has a 90-minute upper bound; each trajectory has
a 900-second trajectory stop threshold plus a 30-second direct-process
supervision allowance. Nested gate processes have their own limits and may
outlive a killed parent; a whole-process-tree envelope is not qualified. The
1,500-second CPU limit applies to the trajectory's own CPU usage, not the sum
of descendant usage. Each file has a 64-MiB hard limit; the 128-MiB aggregate
retention threshold is checked between operations and can be exceeded by the
last operation. These limits are not a complete common-budget guarantee. The model
file lives outside uploaded evidence. Repository source restoration uses a
read-only workflow token only in preparation; that token is absent during
candidate execution.

Records distinguish model-call starts, returned responses, complete token
receipts, worker CPU/wall time, waited-child CPU and retained bytes. Returned
token usage is recovered even if the final receipt was never written. Missing
measurements remain unknown or lower bounds. CPU counted by a parent already
includes its waited children; those child numbers must not be added again.
The model file is shared storage but is a required standalone deployment cost.
Provisioning, the complete OS/library closure, energy, provider billing and
physical token-forward accounting are not fully measured. This is not yet a
complete common-budget experiment.

The executors retain their trusted-candidate boundary. The process wrapper binds
the model worker to its parent on Linux, but candidate Python does not run in a
hostile-code sandbox and does not establish runtime isolation from known fixes.
An execution or integrity failure stops the study and preserves the unexecuted
denominators; an ordinary rejected code edit may receive the next bounded
model call. Late model-byte drift invalidates an earlier task success.
A successful run is not production authorization, source
unlearning or general repair capability. Report actual task outcomes before
calling the retrieval path qualified, and retain all failed runs.
