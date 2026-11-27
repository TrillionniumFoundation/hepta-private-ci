# Recovery of the unpublished sixth source tree

The transient workspace was unavailable when work resumed on 2026-11-25.
The remote integration branch still pointed to public source 804ac018. The
previous sixth-stage local commit e286278a had not been published; its raw
commit metadata was unavailable.

The recovery used the original public fb00 source-input CI archive, GitHub
file patches and content-addressed blobs, plus the two source-pinned SQLite
assets retained in the prior transport staging directory. Every one of 9,932
regular-file or symlink blobs and its mode matched the target recursive tree.
Git generated exactly `9ce80bf521f3d890b7a2f24bb4540f406138645a`. This is the
previously frozen sixth-stage tree, not a claim that the lost e286278a commit
metadata was reconstructed.

The truthful recovery commit is `35e832ea6fe2f8952ffc25a28a2fc1ed3298e5dc`,
with parent `804ac018433ff08dfd195e93eed936394baf5053`. The exact 804 commit and
its source tree were separately restored and verified. The local history uses
804 as a shallow boundary; older public history remains in GitHub. No branch
ref was moved merely to restore these immutable objects. Further actual CI
repairs are separate commits above this recovered source.

The receipt records the original archive and full target identities. The
source-pin and qualification records inside the recovered tree are historical
evidence with their original input identities; they do not imply that the
unpublished sixth source was executed by CI.
