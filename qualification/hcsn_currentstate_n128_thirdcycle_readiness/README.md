# N128 third-cycle readiness — static HOLD

This package freezes a zero-numerical-work readiness gate derived only from the
successful bounded #6285 source and its immutable order-7 capsule.  It does not
implement or execute a third-cycle continuation.

The exact capsule at logical time `.36` contains 22 pending packets.  Advancing
on its canonical boundary schedule reaches simultaneous releases at `.4`:

- generation 2 / target 2 / origin 1, dimension 127;
- generation 3 / target 3 / origin 2, dimension 255.

The admitted #6285 implementation intentionally requires exactly one releasing
packet and only targets 1 or 2.  Its capsule state has 1,320 scalars and stores
only two active generations.  Therefore removing the guard would not supply
the missing generation-3 active state, accruals, upper occupancy, serializer,
or independent oracle.

For a bounded `.4 -> .401` successor, the frozen required schema is:

- active generations 1/2/3: `5*3*127 = 1,905` scalars;
- upper origins 0/1/2/3: 20 scalars;
- M and H for generations 1/2/3: 15 scalars each;
- A for origins 0/1/2/3: 20 scalars;
- total authoritative state: 1,975 scalars.

Lower flux born from active generation 3 must be retained as a target-4 packet
on `[.6,.601]`, even though it does not release in the bounded `.401` horizon.
The three prospective block dimensions are 127, 254, and 382, with augmented
dense dimensions 128, 255, and 383.  The largest single binary64 dense matrix
payload is 1,173,512 bytes, excluding SciPy workspace and all other arrays.
The prospective conceptual full-state comparison denominator is 984,136
coordinates.  These are static consequences of the frozen roster, not executed
costs or numerical results.

Admission of a numerical successor requires a separately frozen candidate and
independent oracle, a new serializer/state identity, exact target-4 retention,
fresh-process restore, full raw coordinate output, and a measured resource
profile.  A failure or timeout must remain terminal for its unique key.

Historical #6285 direct-slice RED and UNKNOWN call count are unchanged.  This
stage executes 0 dynamic segments, 0 matrix exponentials, 0 Torch operations,
and 0 optimizer updates.  It does not qualify third-cycle numerics, arbitrary
histories, N256/N512, finite-domain accuracy, full-network training, async cost,
production adoption, or `all_closed`.

Global status remains **HOLD / NoUpdate / all_closed=false**.
