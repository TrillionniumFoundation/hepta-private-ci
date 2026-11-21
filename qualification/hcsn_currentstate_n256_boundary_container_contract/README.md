# N256 pre-exponential boundary container contract

**Status: SOURCE_ONLY / HOLD / authentic execution disabled / not qualified.**

Draft #6854 froze the exact 68,105-coordinate boundary but did not publish the
two actions' authentic generator, initial-state, or selector bytes. This
independent stage freezes only their transport and comparison contract:

- four ordered little-endian FP64 sections with exact shapes;
- per-section and whole-container SHA-256 digests;
- finite-value, endian, length, order, identity, shape, and trailing-byte
  rejection;
- exact preservation of all bytes, including signed zero;
- a separately implemented parser/comparator with zero mismatch allowance.

The synthetic zero/signed-zero fixtures are local development checks only.
They are not authentic originals, are not precommitted numerical evidence, and
cannot fill the missing boundary. No workflow, runner, admission, artifact, or
idempotency key is added. Authentic input reads, boundary builds/comparisons,
dynamic steps, exponential actions, Torch calls, and optimizer steps remain
zero.

Future work must separately freeze both authentic boundary builders, publish
their complete raw containers, and compare all 68,105 coordinates before either
exponential action. A mismatch must stop with zero downstream exponential
calls. Even an exact boundary would only localize #6823; it would not qualify
the sparse kernel, final N256 step, N512, later cycles, arbitrary histories,
finite-domain accuracy, full prior, migration, full-network training/benefit,
asynchronous cost, C2 full replay, HPCA external custody, production, or
adoption.

Historical RED/OOM/cancelled/UNKNOWN remain unchanged. HCSN stays HOLD, HPCA
stays NoUpdate, C2 full replay stays 0/6, and all_closed=false.
