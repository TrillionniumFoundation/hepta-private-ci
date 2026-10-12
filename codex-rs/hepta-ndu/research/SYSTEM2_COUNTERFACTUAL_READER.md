# Minimal-pair evidence composition: synthetic, frozen Reader only

Stacked research add-on to hepta-private-ci PR #1546. No changes to production,
Reader weights, Encoder, NDU native APIs, Riccati, or FBSDE dynamics.

## Research question

Does a frozen language Reader actually compose multi-hop relations, or merely
copy a convenient token from an evidence set? The earlier synthetic tasks include
only one named correct relation chain per question; retrieving and copying a
salient clearance token can be mistaken for inference. This study creates **16
fixed counterfactual pairs** (32 distinct source scopes, original case indices
40:56). Each pair has an exactly identical English question, identical whole-
corpus lexical term multiset and document order/byte lengths, but the assignment
of one typed relation changes which token actually follows from the project.

- Two-hop examples swap the clearance-token targets on the intended and decoy
  device relations. The project-to-device mapping is unchanged.
- Three-hop examples swap the unit assignments of the named and decoy project.
  Unit-to-device and device-to-token relations remain unchanged.

The grammatical generator validates unique project-to-token paths, different
paired targets, original byte bounds, and that every required relation is
necessary. All targets are programmatically synthetic, not reviewed facts.
The unchanged corpus-level bag of words prevents trivial whole-corpus lexical
statistics from distinguishing the two variants.

## Five frozen Reader conditions, 160 planned model calls

Every arm supplies exactly three original UTF-8 evidence spans, bound to a
unique scope and query-time source frontier with the existing `EvidenceBundle`.
The Reader has the same fixed 1,024-token prompt cap, system instruction and
64-output-token configuration. It is never trained or changed between arms.

| Condition | Relation evidence? | Diagnostic purpose |
|---|---|---|
| BM25 top-3 | Usually incomplete | No learned reasoning retrieval baseline |
| Joined top-3 | Complete | Programmatic positive evidence supply |
| Reversed joined top-3 | Complete, same IDs | Presentation/order effect |
| Missing-start top-3 | Incomplete | Correct token remains, critical first edge removed |
| Terminal-only top-3 | Incomplete | Correct token remains without its relation chain |

Online selection receives only question and source documents, never `Case.answer`,
`required_ids`, gold citations or a solve oracle. Joined paths are a **fixed
symbolic upper control**, not a learned Hepta Cell or an LLM-generated proof.

## Registered evaluations

The runner records all 16×2×5 = **160** attempts, actual model token counts,
raw answers, evidence hashes, source bytes and elapsed time. Each attempted
Reader answer is written unchanged. SHA256 of the complete raw-answer journal
is sealed *before* accessing labels for scoring. Unknown/failing answers remain
in the full denominator, never recoded as negative task labels or zero cost.

After sealing, evaluate separately:
- evidence completeness and exact generated token;
- valid evidence labels and coverage of every necessary premise;
- strict refusal when a path has been broken, even though the tempting correct
  token is still present in a terminal evidence fragment;
- the fraction of paired cases for which **both** counterfactual variants have
  the correct and cited answer (denominator 16 pairs, not 32 independent facts);
- model input/output tokens and observed CPU runtime. Same source count does
  not imply identical prompt token or FLOP costs.

A correct target token with no path is an **unsupported copy**, not an answer
success; a right token with incomplete citations is not strict success.

## Local / hosted boundary

Locally, all **32** generated variants and **160** selection/condition entries
were validated. BM25 had 10/32 complete paths; positive joined/reversed each
32/32, negative missing-start/terminal-only each 0/32. Eleven focused tests
ran: ten passed and one native `EvidenceBundle` integration check skipped
because that source-only environment did not contain the original package.
These are mechanics tests, not pretrained Reader effects.

The GitHub workflow reuses the exact historical Reader artifact and its pinned
inventory, runs the full MemoryCell regression + scoped static checks, executes
only this experiment (does not repeat the prior 100+30 Reader calls), and retains
all partial outputs, tested SHA/tree, environment, raw seals and SHA256 manifest.
Any failed Reader attempt preserves its record and exits nonzero after
writing the complete planned-attempt census.

Neither an all-correct symbolic path nor a frozen Reader result alone is
independent human adjudication. Synthetic grammar, identical symbol prefixes,
shared intermediate rational/typed states and small correlated pairs limit
conclusions. No production gate, new NDU/FBSDE reasoning claim, or multimodal
capability is established by this stage.
