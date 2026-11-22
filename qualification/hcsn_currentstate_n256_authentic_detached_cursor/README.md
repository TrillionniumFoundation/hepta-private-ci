# Authentic N256 detached-parent cursor (HOLD)

The immutable #6931 index-two cursor embeds its entire first-step parent. Its
original cold decoder validates the envelope, coefficients, exponential sum,
and partial algebra, but does not independently recompute the stored iterate
from the parent's iterate and transition.

This isolated successor preserves #6931 unchanged. It reads the exact #6931
artifact archived by #6932, explicitly recomputes that row-action relation,
and emits a canonical cursor that binds the exact first-step parent by SHA-256
instead of recursively embedding its bytes. Cold decode requires those exact
external parent bytes and independently recomputes the relation again.

## Fixed one-attempt budget

- three immutable original-ZIP part reads;
- ten second-step cursor reads and cold decodes;
- thirty first-step parent cold decodes (two while validating each original
  second-step envelope and one while cold-decoding each detached result);
- twenty exact row-action relation recomputations;
- zero recurrence advancement row actions or tail checks;
- zero provider outputs, dynamic steps, matrix-exponential actions, Torch
  calls, or optimizer steps;
- one GitHub run attempt; reruns refuse before the original ZIP parts are read.

The SHA-256 envelope detects accidental drift; it is not an external signature
or protection against a hostile writer replacing both bytes and digest. This
does not establish arbitrary-history resume, advance the recurrence, complete
the provider, close the resource gate, explain #6901, change HPCA NoUpdate, or
authorize production adoption. Historical negative, cancelled, and UNKNOWN
states remain unchanged.
