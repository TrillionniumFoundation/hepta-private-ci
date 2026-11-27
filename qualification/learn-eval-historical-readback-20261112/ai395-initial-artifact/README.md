# Original Initial Artifact readview: rebuilt qualification

This is a source qualification record for the rebuilt Initial Artifact readview.
It does not claim an ordinary A execution, Ledger Decision, independently signed
Observer Outcome, B evaluation, C generation, or full daemon and Root cold recovery.

## Source identity

The executable source starts from remote
`106f5e41f2ff8421c5aad10eeb746d453ed00563`, tree
`23cfee51a9031ab64aade9649f630bcb29e09f44`.

The two rebuilt source/test commits were preserved separately:

| Stage | Local commit | Remote commit | Exact tree |
| --- | --- | --- | --- |
| Source, 402 changed lines | `b028d771e02797d88e3f846c826de9dd813d897e` | `dc04737cde6de444ff566c54099ce920f8b4d107` | `f5cc40cf84a1042943c4445e88584e4626eab4b6` |
| Tests, 89 changed lines | `97496ccc30d6af80e08ef7ad8defce91270ac1b0` | `f5354592de4997c65dda56bdb4b6f1b910d68ee0` | `e24eecdca80c434c4e92a64c22df9c35720cf9d6` |

The guard candidate is remote
`9e5fe517a94ca7acb285537648f97b378fbb3752`, tree
`47da4678986c6e06ca9f3a41ca8032aefbc3f0ab`.
All five guard postimage Git blob hashes match the actual validation record.
No result from an earlier lost workspace is substituted for these executions.

## Implementation boundaries

The fixed Artifact owner enum retains the original writer and introduces a
separate concrete Root Initial readview. The readview retains a weak reference
to the actual Initial client. Opening and using it requires the complete Root
Artifact pin, independent original selection, same client identity, same
five-lane verifier object, and the live original publication session.
Physical CURRENT and withdrawal reads remain in the existing readview.

The public authority constructor retains the writer variant. Initial
publication retains original FinalUse claim, dispatch, consumed witness,
actual genesis checks, and exact CURRENT CAS. Live generation current checks
bracket Artifact and consumed FinalUse revalidation with CURRENT reads.

Update, forward recovery, and local Initial preparation require the original
writer. The six real publication/update call sites that previously attempted
to lock the enum now call `writer()?` before locking. A Root Initial reader
cannot provide this writer.

The actual Initial artifact-authority constructor still has an empty product
caller set at this stage. Ordinary main assembly is a subsequent implementation
stage. The data reader does not grant historical A execution authority.

## Fresh validation

- `just fmt --base 106f5e41f2ff8421c5aad10eeb746d453ed00563`: exit 0.
- `cargo fmt --all -- --check`: exit 0 in the same rebuilt source/test scope.
- First guard attempt: five exact-generic tests passed; Artifact source QA had
  seven passes and one configuration error because a required-order sequence
  contained only one marker. The original failing output is preserved.
- The fix splits that same original call into three consecutive executable
  markers. No authority check was removed.
- `python3 -m unittest discover -s qa/b4-no-bypass -p 'test_*.py'`:
  **253 tests passed**, 19.482 seconds.
- All **511** boundary definition and declared caller markers and all **384**
  protected-file rows passed. This is not the full actual-caller scan.
- `git diff --check`: exit 0.

The narrow generic locator accepts only exact simple type parameter lists used
by the actual guarded functions. Unique-definition, function-body order,
comment/literal/test masking, and nested-function masking remain enforced.
Negative controls reject absent or duplicate definitions and unsupported generic
forms. All pre-existing boundary and protected-file rows remain present.

Raw outputs under `raw/` include the first failure and the successful retry.
The first formatter wrapper's raw metadata is saved as `.raw.txt` because the
wrapper originally wrote a literal backslash-n terminator; it is not relabeled
as valid JSON. Empty stdout/stderr files are preserved.

## Outstanding gates and product work

Full repository actual-caller scanning, fresh native tests, and scoped Clippy
are pending for this exact rebuilt candidate. The parent task owns the shared
native build target. Component and source checks do not establish a product
execution or full recovery pass.

The next ordinary stage must provide actual sealed deployment data, the same
Root Initial lane and existing Artifact/FinalUse owners, and the real Q24
Circuit profile. Root capture requires a genuinely drained runtime and closed
Source owner files. Learning additionally requires Root-pinned learning trust,
the original Generator key and durable Ledger files, an independent signed
Observer Outcome, and durable authenticated RunStart retention. No successful
task result is converted into an Outcome or reward.
