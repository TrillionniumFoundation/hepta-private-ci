# External Root input codec: prospective source slice

Base: signature extraction `4eb790a0746c98be31a8c0ae12dacaca4cbec8eb`.
This slice is a non-authorizing input codec and four unexecuted controls. It is
attached only under the original issuer's test configuration. The following
slice promotes the same module and connects the already reviewed original Root
CLI, consumed Prepared session and current-record registration consumer. No
public API is added to avoid a temporarily unused private module.

Three independently supplied Root configuration files carry a complete root
pin, a full externally signed original distribution, and an external Root
acknowledgement declaration. They use explicit V1 schema/operation names. The
original `read_root_json` retains Root directory/file custody and its 64 KiB
bound. Pairwise-equal paths are refused before reading. This slice does not
claim independent organizations merely because three paths differ.

All four object schemas reject duplicate and unknown fields. Native IDs and
digests use their original parsers; keys are exact 32-byte arrays, signatures
are exact 64-byte arrays, integer fields remain integers, and roles have exactly
the original six names. Complete signer, role and signature material is mapped
without filtering or normalization. This structural codec deliberately does
not authenticate a signature, validate a complete trust set, choose currentness,
activate trust, infer an acknowledgement or grant any operation permission.
The original full signature verifier remains mandatory at the actual consumer.

The four prospective controls cover complete native-value equality, strict
duplicate/unknown/version rejection, native ID/digest/numeric/key/role/signature
shape rejection, and separate-file refusal plus preservation of invalid excess
signers/duplicate roles for later full verifier rejection. Synthetic signature
bytes are explicitly invalid; they are not user or authority evidence.

No Cargo, Root provisioning, native control, file recovery, fit or scientific
experiment is run by this slice. The existing native pool and all previous
outcomes remain unchanged. Actual `just fmt` and a narrowly scoped original
source-checker proof may be recorded. Neither substitutes for native execution
or the actual Root current-owner and recovery-consumer path.
