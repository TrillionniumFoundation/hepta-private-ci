# N128 first-cycle full-state readback

Status: `PASS_BOUNDED_N128_FIRSTCYCLE_ONLY`.

This evidence-only readback preserves the immutable output of source
`85c73b040448bc58929e40118d533a5ea65705e2` and unique identity
`hcsn-n128-firstcycle-fullstate-20261112-c06d-001`.  The exact hosted run
was Actions 43327389327 / job 131563180145, which completed successfully.

The candidate and independent dense oracle agreed bitwise for every stored
coordinate at five checkpoints through the first cycle, before the
generation-2 packet release:

- times: 0, .001, .02, .16, .2;
- coordinate denominators: 1376, 18528, 35680, 155702, 189992;
- total: 401278 / 401278 bitwise-equal coordinates, zero failures, max absolute
  error zero;
- candidate: 11 dynamic segments and 22 matrix exponentials;
- independent oracle: 11 dynamic segments and 22 matrix exponentials;
- five cold dump/load/dump containers were byte-exact;
- Torch calls: zero; optimizer calls: zero.

The complete original artifact is retained as `originals.zip`; the complete
decoded Actions job log is retained as `job.log`.  `READBACK.json` binds
their hashes and the per-checkpoint capsule identities.

This result does not qualify generation-2 release, continuation after .2,
arbitrary histories, N256/N512, full-network training, migration, production
adoption, or all blocker closure.  The historical negative results and
UNKNOWN values remain unchanged.  Global status remains HOLD / NoUpdate and
`all_closed=false`.
