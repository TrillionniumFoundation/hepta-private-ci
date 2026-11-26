# One candidate retention measurement

This scope measures the fixed V5 peer aggregate candidate on the original
parent's two synthetic held-out populations. The candidate has not previously
been evaluated on this panel. This is distinct from the exhausted E1-E6 study,
the V5 four-tick trial, its cold fixture comparison, and the old parent's
evaluation. None of those executions is repeated.

The complete candidate has SHA256
981304e53920d71cf95672df6317a4f81b0aff4f7b380f6d3bdd8b3e4033ee1c.
The historical parent has SHA256
0127a056c779930fc5ab27558e84aecbd242caa64951f21e47d7885465f0b86f.

## Fixed comparison

Use both original test populations, with seed 271901, 128 examples per
population, and source IDs 730000 and 730100. Regenerate their inputs using
the exact retained corpus function and verify the original x/margin/target
hashes before any model forward. Labels must equal the archived NPZ targets.
The original prediction arrays, archive manifest, evaluator, protocol and
parent profile are pinned and cross-linked. Earlier parent baseline scores
and the linear expected predictions do not substitute for the saved model's
physical prediction arrays.

Run the new candidate through its verified full model profile, with fresh
population state for every chunk of 16 and all 12 original time steps.
This uses 16 new candidate forwards and one model load. Parent predictions
are read from the existing archive: zero parent forwards, zero solves, zero
derivatives, zero training updates, zero candidate exports and zero retries.

Before any new candidate output on this panel is observed, freeze the
protocol and evaluator hashes and publish them as a draft review stage.
For each population independently, require all three conditions:

- No previously correct example becomes incorrect.
- Candidate accuracy is at least the archived parent's accuracy.
- Candidate mean squared error minus the archived parent's is at most 0.001.

Classification uses margin > 0, exactly as the original evaluator. There is
no added floating tolerance. The gate is an explicit finite-panel criterion;
it is not a statistical claim about the complete task distribution. The
historical parent summaries were already known when this new gate was set.
The new candidate outputs on this panel were not available for threshold
selection. No threshold or parameter revision is allowed after observation.

## Execution boundary

Only root may execute this scope after static review, the official source
format gate and publication of the frozen protocol. The process uses the
already pinned pocket4 CPU float64 runtime. The three profile helpers and
the original corpus helper execute from verified source bytes, not cached
bytecode. The physical model remains the original frozen capsule.

The inner limits are 20 CPU seconds and 55 wall seconds. Root supplies an
outer 65 second hard timeout. A missing or partial result is incomplete,
never a pass. The output directory is created exclusively and contains the
run claim, preventing replay into the same operation. No timeout or transport
error authorizes a new operation or another candidate execution.

A completed negative gate is a valid REJECTED observation with process exit
zero. Consumers must inspect both completion and the decision. Successful
completion also requires both panels, exactly 16 forward attempts, unchanged
candidate state, and unchanged retained inputs. H terminal success, durable
complete publication and both stream EOFs are separate execution evidence.

## Claim boundaries

A pass closes only this finite synthetic retention measurement for this
exact candidate and historical reference. It does not establish independent
real users, a prospective B arrival, two authorized B uses, preservation of
all old abilities, a population noninferiority guarantee, production adoption,
new natural-task benefit or total training savings.

The V5 archive evidence bridge remains an assessment of its 14 original
files. Its lack of retention evidence is not overwritten. A V6 result is an
additional, separately identified observation, including any failure.
