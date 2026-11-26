# Hosted source carry-forward and CTRL history visibility

This branch uses fixed source/preparation base 6ca37caad90259aaad76c89d4f6a5a64715ab041.
It carries eight files byte-for-byte from 32153753a33a86a30d5d38a53483146c66161acd and changes only
CTRL checkout fetch-depth from 16 to 0. No source guard, whitelist, workflow
trigger, Python version, old source freeze, or prior result is relaxed.

## Evidence retained from the one preparation

The nine registered preparation commands returned zero. Official just fmt
reported no changed files needing formatting; this is not a claim that it
parsed every copied Python or YAML file. The nine-path git diff --check passed.
All 9 bound inputs, 60 workspace files and 44 formatter guards kept exact bytes.
Preparation wall seconds: 0.41177295916713774.
Formatter wall seconds: 0.15159450005739927.
The original scoped diff is +463/-1 text lines and one unchanged binary source.
This publisher runs zero formatters, tests, compilers, models or optimizers.

## Existing metadata evidence, not a new observation

Run 45786899259 attempt 1, job 139795831557, succeeded at source 32153753.
Original artifact 15100974608 has 28,989 bytes and SHA256
881930596a525c4fa5e6f073f1dfeaed02cf8bebb56c8f10478d0425f2505b36.
Its original result SHA256 is
96fdf513c6be0297180de2320b146d4b4c15f791159289bcc7e57083223743d4.
That observation comprised six host validators, including five negatives,
with zero N256 numerical/model work. Those validators are not run here.
The copied workflow retains its exact original branch-creation/attempt guard;
this independent carry-forward branch cannot enter that metadata job.
The old V2 run 45794040857 remains failed, with its exact Python setup failure.

## CTRL scope and limits

Old run 45794043165 passed five preparation tests, then failed to find its
fixed historical commit in the shallow checkout. Full history addresses only
that visibility defect. The current 6ca base still differs at the three fixed
source pins and must still fail the original proposal admission gates.
No CTRL dependency qualification, N256 numerical admission or production GO
is granted. Generic push CI has its own workload and must be accounted for;
new-branch push comparisons may include inherited history beyond these files.

## Byte custody

INDEX.json identifies one real xz archive: 90 raw preparation files plus this
publisher, its input, the frozen helper and MANIFEST.json (94 total members).
Verify archive bytes/SHA and every manifest entry before use. The copied
LEGACY_SOURCE.tar.xz is retained as opaque original bytes, never repacked.
