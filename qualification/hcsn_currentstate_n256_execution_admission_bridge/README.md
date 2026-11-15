# N256 execution/admission compatibility bridge — HOLD

The independently frozen provider in #6338 retains its original v1 admission helper. The later #6341 admission contract is v2, and #6349 introduced a different atomic execution-freeze record. Calling the old helper with those later records cannot provide a valid execution boundary.

This source-only stage preserves the old provider bytes and adds a narrow compatibility layer that:

- validates the v2 provider admission and atomic execution freeze with their owning validators;
- cross-binds the provider source, operator/segment rosters, five resource originals, four external-review originals, execution request, execution key, and admission-before-execution ordering;
- binds a later three-stream manifest to the exact admission and execution-freeze digests; and
- refuses to invoke the provider, write N256 frames, open payloads, allocate a key, or grant qualification/adoption.

The small tests use synthetic hashes and timestamps only. They are interface fixtures, not external custody, resource evidence, provider admission, N256 execution, scientific evidence, or production authority. The historical v1 source identity and every RED/UNKNOWN remain unchanged.

Current state: **HOLD / NoUpdate / all_closed=false**.
