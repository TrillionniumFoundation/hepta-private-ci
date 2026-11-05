READ-ONLY GIT BYTE TRANSPORT PROBE

Exact repository: TrillionniumFoundation/hepta-private-ci
Exact evidence head: 571c3da959bcbcca6639a5882d49aebadd00bff2
Actual successes: binary 1,044,516 bytes via fetch_file encoding=base64;
UTF-8 2,812,928 bytes via fetch_blob. Both match size, SHA256, and Git blob SHA.
No 5.6 MiB text was tested. These two successes are not a maximum API limit.
No desktop request, Git object creation, push, ref/PR mutation, or authentication change.

The original RPC files remain intact at the source. This archive stores each actual
readback once plus byte-exact RPC prefixes/suffixes and a validated payload codec.
Run: python3 -B scripts/verify_transport_package.py --root . --reconstruct-dir ../rpc-restored
Every member and both reconstructed RPCs are checked before success.
