# Lane E exact-head qualification policy

Lane E repository closure is evaluated only for the immutable Git commit and
tree named by the check run. Results from an earlier branch tip, a mutable branch
name, or a source-only run do not transfer to a later candidate.

A repository-controlled candidate is qualified only when all of the following
succeed for the same source head:

1. the closed-world traceability verifier and its self-test;
2. locked all-target compilation for every Lane E owner and composition crate;
3. all owner regression tests and the cross-crate causal-learning closure;
4. strict Clippy with warnings denied and rustfmt with an unmodified index;
5. an ordered-parent synthetic merge whose first parent is the integration base
   and whose second parent is the exact Lane E source commit;
6. the same verifier, compilation, tests and formatting checks on that synthetic
   merge tree.

Passing these checks closes repository-controlled source and integration gaps.
It grants no product-writer, outcome-observer, model-provider, selector,
operator-acceptance, promotion, deployment or release authority. External gates
remain fail-closed until an independent owner issues an evidence receipt bound
to the exact candidate, objective, environment, authority epoch and validity
window.

Any source change after a successful run invalidates that run for merge
qualification and requires a new exact-head evaluation.
