# Hosted continuous-adjoint Torch GREEN originals for #6248

This preserves the existing successful [run43217764472 / job131181247635](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43217764472/job/131181247635) at immutable source `975a169df5f3a1dd51b81ddd51b0a338592a0e0f`.

| Actual completed probe | Value |
| --- | ---: |
| Model-primal forward calls | 166 |
| Adjoint calls / backward attempts | 10 / 32 |
| Guard rejections / optimizer updates | 20 / 0 |
| Full child wall / CPU seconds | 60.759934334 / 60.306657 |
| Full child peak RSS | 454140 KiB |
| Original artifact ZIP | 254226 B; SHA256 `8bca916a6f5dc7b346905268d005fab838805b475e39df738cb5a053b8ffe9d8` |

The original ZIP and all six raw members are retained, including full RESULT,478571-byte ARRAYS, source manifest, stdout,190-byte stderr and WRAPPER-COST. Complete decoded job logs and API metadata are retained. Result fields match the logged summary; raw wrapper/source match their logged records. All ten prefrozen source hashes were independently recomputed from exact-source GitHub bytes. Original bytes and remote blob identities are read back with full SHA256 checks.

The original result records12 checks and20 rejected guards,166 forward records and10 adjoint-backward records. These are retained producer results. This archive does not recompute VJPs or run gradchecks/guards, and takes no credit for the separate independent mathematical audit. The complete SciPy BDF line416 invalid-subtraction RuntimeWarning remains in native.stderr and the job log.

Full-child cost includes Python/Torch imports and source admission. Its nested validation interval is58.241631329s wall /58.208481387s CPU; these scopes are not additive. Runtime is Python3.12.16, Torch2.8.0+cpu, one thread. Adam/restore, discrete adaptive-BDF reverse, full-network, n512 and rare-tail relative qualification flags remain false.

The [first RED](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/b685ec948098461e101c40017b2aeed5126157e6/qualification/hcsn_ci_readbacks/6248-red001) remains immutable with its one completed primal, failure and full cost. This GREEN is a separate source/run identity.

This archival operation adds zero candidate, model, Torch, adjoint or optimizer calls and requests no rerun. New files stay under `qualification/hcsn_ci_readbacks/6248-green002`; the archiver changes no PR source head. Retained originals are not reformatted. Global HOLD_NO_GO remains.
