# Current c0f first stack signal: four-caller addendum

## Conclusion

The current c0f first signal has a concrete stack-allocation explanation: four simultaneously active caller functions reserve **7,242,272 bytes** in their initial prologues; the next `PositiveFixture::ready_for_publication` poll attempts another **2,284,152 bytes** plus register pushes and its call return address. Its page probe reaches the original 4 KiB guard below the unchanged 8 MiB test-thread stack. This observation is specific to the recorded panel case and pinned c0f ELF.

The fixed a96 preparation already contains two relevant inner boxing changes. They can alter enclosing future layout and construction temporaries, including code paths whose bodies have not yet executed. Their actual effect on the next compiled candidate is **Unknown**. No additional boxing hunk is produced from these old-ELF measurements; the prior source preparation and frozen 59-file package remain unchanged.

## Exact executed and static inputs

The executed source was commit `c0f78493f815780f68b9bf5e390a21314d79311f`, tree `313ee34febc8ccc54c611ab56286e289518c63cb`. The pinned ELF is 282,318,328 bytes, SHA256 `b63053496fb1a8f610445862a6ce980ccb7beead4e08796feaa97ab21813e119`.

The original case is:

```text
runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::evaluation_provider::panel_members::original_panel_reads_actual_b_and_retention_with_full_original_signatures
```

The first-signal raw record is blob `e0c0d9d82475980089e921ec2332c907469b02a6`: 43,646 bytes, SHA256 `a5794043e3cb211fb7e4131f5a06dee329edb5a67fb11e2127fb85be67daf70d`. The new bounded disassembly is blob `f919c40fff919bf7395a87e492bcc34be0f4c624`: 17,335 bytes, SHA256 `8b604cc77402afa956e85ecb2f5978e0c2f6f2f0a14f7ef92317f7070b72b210`. It was independently read in full and checked against both SHA256 and its Git blob SHA. Native's exact-byte recovery proof is `babbc91e2d21b4546d4780e5e1c2c10dfdbd26dc`; its already-issued view response is `a50197de87a44c4dffe41b737024c6b067b600ce`.

The static result `8208865988e7bf8e8aa80fa4217b153ce3dbdf46` records unchanged source and ELF before/after, no binary execution, no Cargo, and no tests. It reports the CFI attempt as **unavailable**: the bounded scan stopped at its stream limit, retained no covering frames, and returned `-15`. No extra scan is requested, and no unwind-size claim is inferred from that incomplete CFI.

## What the actual prologues say

Each of these four prologues copies `%rsp` to `%r11`, subtracts the page total from `%r11`, then probes one 4 KiB page at a time until the target is reached. It subtracts the listed remainder after that loop. No initial register pushes occur in these four retained prologues.

| Actual GDB frame | Function | Page total | Remainder | Local reservation |
| --- | --- | ---: | ---: | ---: |
| 2 | `preregistered_for_publication` poll | `0x121000` | `0x918` | 1,186,072 B |
| 4 | `PanelFixture::completed_for_publication` poll | `0x1c6000` | `0x748` | 1,861,448 B |
| 6 | Panel test poll | `0x27c000` | `0xc58` | 2,608,216 B |
| 16 | Panel test entry | `0x183000` | `0x568` | 1,586,536 B |
| | **Total** | | | **7,242,272 B** |

Frame 16 additionally contains an actual stack-to-stack `memcpy` with length `0xc19d8` (793,048 bytes). This is an instruction-level observation, not a new Rust `size_of` measurement or a claim that each byte represents a live logical value.

GDB's previous-frame SP is `0x71d6fe915b60`; the stack top is `0x71d6ff000000`. Their difference is 7,251,104 bytes. The four measured local reservations account for all but 8,832 bytes of that distance. Return addresses, intermediary `Pin`/runtime frames and other overhead are not individually attributed without complete unwind information.

The writable stack starts at `0x71d6fe800000`, leaving 1,137,504 bytes below the reported previous-frame SP. The ready poll's existing prologue reserves `0x22d000 + 0xa78` = 2,284,152 bytes; its two pushes add 16 bytes and the call return address adds 8. Completing that plan would exceed the writable stack by 1,146,672 bytes. Execution actually faults during the page-probe loop at SP and fault address `0x71d6fe7ffb48`, inside guard range `[0x71d6fe7ff000, 0x71d6fe800000)`. It does not successfully complete the planned reservation.

This explains this immediate signal without attributing it to recursive execution, a database wait, or the old e8 collision point. The member-completion phase is not on this first-signal stack.

## Source-bound comparison with the prepared candidate

The complete source comparison is retained in prior facts blob `c3f233b1c308c6a57a9fb1a44c93a0f4187bef98`. It covers all 23 Rust paths in the fixed a96 31-source/config delta, the exact c0f/a96 merge baseline, the frozen 59-file package, and the three independent Rust increments. The candidate projection is based on fixed `a96d1b821d10ed3d9e99dd06c5141f9f242ae318` plus preserved c0f changes, not on a later live branch.

| Source | Relevant exact identities and observation |
| --- | --- |
| `codex-rs/hepta-agentd/src/circuit_model_selection_owner_support_tests.rs` | Blob `127e9731d146a8a30b2f6cfa8b563f97afe694a8` is identical in c0f, fixed a96 and the composed baseline, and is absent from the 59-file overlay and three increments. `PositiveFixture::ready_for_publication` is unchanged. |
| `codex-rs/hepta-agentd/src/circuit_original_evaluation_provider_tests.rs` | c0f `a42826fa67ed1c598916c3bd9046dfd255e64280`; composed `c1cf7010e8dcc20a29f821a5e6eb46715340cd6f`. The relevant `preregistered_for_publication` body already boxed `PositiveFixture::ready_for_publication` in c0f and remains the same. New boxes in other provider test entries are separate from this case. |
| `codex-rs/hepta-agentd/src/circuit_original_evaluation_panel_tests.rs` | c0f `c968ff41de9cca02f5321cb2fa813ef5f8eeef6b`; composed `89e82d4b77f7cd76ac8df20e4ad88790e66a7158`. The single new box in this file wraps `PanelMemberFixture::complete` inside `completed_member`. The direct-return `completed` helper, boxed `completed_for_publication`, and its two boxed `completed_member` awaits already existed in c0f. The measured test body is unchanged. |
| `codex-rs/hepta-agentd/src/circuit_original_evaluation_panel_member_support_tests.rs` | c0f `0e7f3c909fcc97742e228eb4ad189bd074727604`; fixed a96/composed `2bdf58f807f79da78a0d1e8ee66ebf735fb7cb7b`. The other new relevant box wraps the original `qualification_owner.qualify_or_readback`. Original member inputs, complete Ineligible assertion, signing and retention-first order remain intact. |

The full a96 delta also adds boxing in the new evaluated Selection tests and four distinct provider test entries. The frozen 59-file package adds boxing in four new mechanism-test files. None of these is falsely described as the only new box in the whole candidate; their exact sites remain in the earlier source-facts catalog. The three later Rust increments (route alignment and two exact-type call qualifications) add no boxes.

A boxed future's stored state and its poll function's stack locals are different quantities. The ready poll still runs on the current thread stack even though the caller already holds it through `Box::pin`. Conversely, the two new inner boxes can shrink a future type that an enclosing poll constructs, so they may alter that enclosing prologue before the corresponding branch is reached. The old ELF does not quantify either effect in the new compiled candidate.

## Acceptance boundary

This addendum makes no claim that the prepared candidate passes the case, that the existing a96 boxes are sufficient, or that all 24 focused stack failures have this same cause. The exact next source still needs its original maintenance and execution under the existing stack and time contract. No stack size, timeout, production authority, receipt, assertion, or qualification rule was changed to obtain this result. A further fixture-layout hunk should be driven by a remaining observed candidate failure, rather than by treating old-frame byte counts as new-build measurements.
