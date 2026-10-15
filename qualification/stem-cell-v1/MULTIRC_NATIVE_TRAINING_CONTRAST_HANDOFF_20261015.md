# Genuine MultiRC all-native training versus original first-answer training (2026-10-15)

Research Draft PR #2080, stacked on #2064 (`6f8cf0930a51bce97fc22a09e3c5923a082abae9`).
Tested code commit `d5e73f5a4f430c3c0cfe515e60175f899ebe1835`; baseline-replay test commit `fba30f3264a3729c55a38400c6199f12a29a178e`.

## Measured local mechanism and causal controls

The same original pinned MultiRC training passages and two question IDs are used by four physical PyTorch Readers. Train-only labels are admitted on genuine original candidate IDs: first candidate (6 training examples across 3 source passages) or all genuine answers (12 training examples). Architecture is conditioned cross-attention or mean-pool/query fusion. All four models use 42 parameters, the same seeded initialization and exactly four optimization steps in this tiny synthetic diagnostic. The first-only models' learned weights match the existing original V1 study **byte for byte**, under identical toy encoder and evaluation source.

All four models scored 4/8 on the same 8 genuine candidate-structure evaluation set. This is NOT a quality gain, and this toy task is not human-annotated MultiRC with real pretrained weights. Training cost is measured separately by arm; 4 fixed updates are not fixed data exposure or fixed total system resource. Encoder is physically shared per passage and every genuine alternative question representation is actually executed.

## Execution and safety

The `prepare` stage accepts a source-locked full train parquet and the original selected train panel. It verifies complete 2–8 alternatives per selected question, preserves the V1 first-answer anchor, and does not change selected questions based on labels. The `run` stage fits all four Readers **before calling** a loader for the blind heldout full genuine-candidate slate. The `score` stage separately authenticates the sealed prediction file, externally supplied receipt/hash and every human binary label. It refuses incomplete source groups, changed weights, missing operators and memory overflow. The new CI stage is added **before** preexisting final human dev label scoring, while actual native train-material and scoring work are independently observed.

## Validation

Two complete source-*slice* runs of 651 tests each, in six class-coherent disjoint shards, zero errors/failures/skips/discovery errors; identical inventory and 59 test file SHA256 hashes. Source/test/CI Git blobs match exact local bytes and the four-file patch was replayed on the exact predecessor source. Stock Transformers is NOT installed locally and stock/public pretrained tests require their own hosted CI. No performance benchmark, statistical significance, generalization, source independence, energy or system-wide cost savings are established.

## Scientific next gate

Obtain and inspect the real locked ModernBERT+MultiRC canary with original V1 and full-native results. Compare accuracy, Brier, within-question probability variance, recovered/lost examples and per-model actual costs under identical heldout candidates. If both query representations remain insensitive, improve the query/answer embedding in a newly preregistered arm rather than relabeling or cherry-picking this heldout panel. Do not merge or deploy.
