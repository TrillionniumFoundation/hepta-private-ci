# Independent GRU engineering review

The retained review uses the final eighteen-method stock-GRU contract. It checks
literal state restoration into a different compatible live object and exact
replay of the next tiny forward, backward, and SGD step. The target has incoming
nonzero gradients, zero gradients, absent gradients, two parameter groups, and
existing momentum. The probe deliberately accumulates onto incoming gradients.

`FINAL_REVIEW.json` binds the reviewed writer files, the dynamic receipt, the
exact executed probe, the initial method-inventory counterexample, and the
literal synthetic checkpoint. The files are copied byte for byte from the
independent review workspace; their original paths remain in the receipts.
`probe.py` retains those original workspace paths and source hashes. It is an
execution record, not a portable scientific runner.

`INITIAL_METHOD_GAP.json` preserves the initial zero-forward counterexample:
the earlier thirteen-method inventory accepted an inherited `permute_hidden`
override. The final writer contract adds the five inherited helpers and typed
default checks. The final independent run checks this repaired contract.

`attempt1/tiny_cross_object.state` is a 41,767-byte synthetic 2-by-2 GRU fixture,
with SHA-256
`edb85918756ccc44ccd43ba39e499ef7574c9a7d1c018dfbb5c7dd4b697ca7da`.
It contains no historical scientific endpoint, model checkpoint, training bank,
or holdout. The independent run performed two tiny forward calls, two backward
calls, two SGD steps, and eight explicit random draw calls. The retained writer
attempts separately performed three such steps and twelve explicit draw calls.
Their combined count is five tiny steps and twenty explicit draw calls;
constructor initialization is not included in that explicit-draw count.

The four independent rejection probes observed no application of mutable state
and no change to the inspected public state, object identities, version
counters, or RNG state. Successful restore still requires a step boundary with
no external pending autograd graph and no concurrent writer. Carrying recurrent
hidden state across branch boundaries needs an explicit caller state contract.

This review closes the demonstrated method-inventory gap and the bounded
cross-object toy replay check. It does not establish replay of the scientific
learning kernel, complete capacity bounds, historical raw-byte recovery, or
candidate admission. The proposed V6 scientific candidate remains unregistered
and unexecuted; the historical V5 result remains rejected and admission remains
false.
