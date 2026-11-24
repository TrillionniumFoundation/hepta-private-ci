# Windows cognitive root canonical name

## Observed failure and bounded repair

On the normal Windows run for source
`fb00e4422c293ffb318c9d7535e1991a3bbac707`, all 23 selected cognitive tests
failed with `Invalid("cognitive root is redirected")` before the SQLite or
recovery assertions. The native private-directory open had already succeeded.
The subsequent legacy path-component spelling comparison returned no match.
The log does not contain both path spellings: a specific casing or short-name
difference has **not** been established.

Run: <https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45434906085/job/138589954514>.

The Windows backend now derives its canonical key with
`GetFinalPathNameByHandleW(FILE_NAME_NORMALIZED | VOLUME_NAME_DOS)` from the
already validated directory handle. The query has a 32,768 UTF-16-unit budget;
failure, insufficient capacity, or an output prefix other than a local
verbatim drive is an error. UNC/device paths remain unsupported. Returning a
name does not replace retaining and validating the directory handle in the
consumer's open guard.

Every native no-reparse, local-NTFS, exact effective-user owner, and owner-only
DACL check remains mandatory. An existing reparse ancestor is classified as
redirected before descendant creation; this preliminary metadata inspection
does not replace the native no-reparse lookup if names race. The immutable
source/current-cut and unsupported original-writer recovery boundaries are
unchanged.

## New native assertions

- The normal mixed-case spelling, its OS-normalized verbatim spelling, and a
  case-equivalent spelling reopen the same root identity and namespace witness.
- The canonical name comes from the validated handle and equals the OS name.
- The SQLite inspection entry rejects both a junction root and a child under
  that junction, without creating the target child.

The selected primitive test count increases from 13 to 14. These assertions
have compiled, but **have not executed on Windows for this candidate**.
The previous db23 probe result of 12/13 passing does not qualify this change.

## Validation before integration

On 2026-11-24, actual path-utils production and test sources compiled for
`x86_64-pc-windows-msvc` using Rust 1.96.0:

1. Isolated 55-package `cargo check --tests --locked --offline`: exit 0,
   0.654 seconds, no warnings. This manifest does not compile the cognitive
   consumer.
2. Normal workspace and its existing lock, scoped
   `just fix -p codex-utils-path --target x86_64-pc-windows-msvc --locked --offline`:
   exit 0, 13.202 seconds. The existing unused `imbl` patch warning remains.
   No source file changed during Clippy.

All nine path-utils source hashes and the cognitive backend hash were equal
before and after both commands. This is compilation and lint evidence, not
native execution or complete consumer qualification. The normal Windows
workflow still runs the full primitive, registry, state, cognitive,
directory/schema, prompt-consumer, and scoped Clippy gates.

## Subsequent native execution of the canonical primitive

The normal Windows workflow at integrated source
`ebe2737b4014c9b45ad995adccc53eb71e718f3d` executed the new case:
`sqlite_canonical_name_comes_from_the_validated_handle` **passed** in 0.020
seconds. All 14 selected primitive cases ran: 13 passed, 1 failed, with 5 other
tests outside this selector. The unchanged ordinary-file inheritance case
failed on both attempts because its owner differed from the effective token
user. That source does not yet include the independent owner fixture revision
`640825cbfe71d978991a30959b52a0b60a509895`.

The registry selection separately passed 2/2, with 26 other tests outside its
selector. These results qualify the canonical-name primitive and preserve the
adverse creation-owner result. At this receipt, the normal state/cognitive and
other consumer gates remain in progress; in particular, the cognitive 23-case
selection is not yet qualified. The normal run was not cancelled.

- [Normal native run and job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45445453422/job/138627851875)
- Early artifact: `14945209118`, 5,158 bytes; downloaded ZIP SHA-256
  `129a6da326193ef756605fb7d399235fa5d54995e89b1ed6dec9ea53879f68e0`
  matches GitHub's artifact digest. The contained head matches the source above.
- Primitive log SHA-256:
  `3ee49aabb9f1eb099f359aae02ca22ee6e91653b2c04a13d0b9318ca88ac339e`.
- Registry log SHA-256:
  `e69f04c5e788fecee88d51e6f4a7213d13d6655ba0ef0e90fc70626d75a15dd0`.

## Primary API reference

The subsequently completed run is recorded in the
[full ebe273 receipt](../windows-native-ebe273-20261124/README_ZH.md).
The canonical primitive passed; all 23 cognitive cases advanced to a
creation-owner rejection, so their downstream recovery assertions remain pending.

Microsoft documents that the DOS form returned by this handle query uses
verbatim `\\?\` syntax, with success length excluding the terminating NUL:
<https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfinalpathnamebyhandlew>.
