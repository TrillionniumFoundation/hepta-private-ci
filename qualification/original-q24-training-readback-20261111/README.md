# Original Q24 Trainer readback for independent B

Status: implementation candidate based on fixed source
`11a9aeccfe60693ff1f6181f732630a758cf466b`. This delta has not been formatted,
compiled, tested or checked by the complete native caller verifier. It must be
qualified on the final integrated source. Ordinary full loops, positive adoption,
ordinary NoUpdate/rollback and independent-consumer qualification remain **0**.

## Actual production connection

The concrete ordinary aggregate already owns the native Trainer and its
Generator receipt journal. `original_training_readback` runs in that aggregate's
existing admission lane, reads the completed original Dataset-bound Trainer,
and exports an opaque `OriginalCellQ24TrainingReadbackV1`. It retains the same
TrainingStage, Prepared Dataset and cancellation fence. No public constructor
accepts a receipt, key, descriptor or arbitrary provider.

The host supplies its already completed, independent B resources through
`OriginalCellQ24EvaluationInputsV1`. Its Trainer field now explicitly selects
`OriginalCellEvaluationTrainerV1::OriginalQ24` with that handle, or
`External` with the existing `LearningIterationEvidenceClientV1`. The aggregate's
B installation checks actual Arc identity for the native handle, not just equal
receipt bytes, before opening the B receipt owner or accepting its slot.

The native path reads the same original Trainer through its existing semaphore.
A narrow read-only method requires the Trainer's private original Dataset
provenance before and after reading its original completion and Generator
attestation. Missing and Pending cannot fit, sign or create a result. The
readback handle checks the complete Training prefix, scope, live Dataset/source
and aggregate fence before and after that read. It never reenters the aggregate
lane, so Evaluation can safely call it while already holding that lane.

## Preserved B and external contracts

The public external `OriginalCellEvaluationReceiptSourcesV1` and the original
receipt owner's external attestation/readback method signatures are preserved.
They convert to a closed internal source and use the same validation body as the
native handle. The separate process client's original UID, PID, pidfd, peer,
session, exact-receipt and signature checks are unchanged.

The Evaluation receipt owner's original execution namespace, runner readback,
final-holdout/qualification inputs, Generator/Evaluator principals, controller
separation and current evidence validity remain mandatory. The source-kind enum
does not establish independent B. It only selects where the original Trainer's
already issued evidence is reread. No evidence is manufactured, no scientific
input is inferred, and no authority flag or durable wire schema changes.

An existing external aggregate handoff now wraps its original client explicitly
in `OriginalCellEvaluationTrainerV1::External`; it cannot silently fall back from
an unavailable native owner. A native handoff obtains the handle from the same
aggregate and installs it with the actual B inputs. Equality to a copied receipt
cannot substitute for that owner identity.

## Recovery and evidence boundaries

Reopening a daemon still requires the original host to supply its original
Trainer, source, witness and Root inputs. The recovered aggregate exports a new
in-memory readback handle after reading the exact retained Training cut. B's
original Recover mode retains the original execution and receipt signature;
this adapter does not renew an expired Generator/Evaluator window or grant a
replacement owner. Cancellation and uncertain original readback remain errors.

Three new component methods use actual ordinary task/source, authenticated
Dataset, HQ24T002 batch, original E/D journals, native training and Generator
receipt owners. Credentials, CURRENT custody and role profiles remain fixtures.
They check exact readback without further writes, altered receipt/source and
foreign fence rejection, missing-owner no-fit behavior, source withdrawal,
current Dataset correction and aggregate cancellation. A test-only constructor
calls the same private readback validator with those actual owners; it does not
exercise Root export admission or establish an ordinary production deployment.
The existing B execution/holdout tests retain their original scope; no synthetic
observation is relabeled as an independent business experiment.
