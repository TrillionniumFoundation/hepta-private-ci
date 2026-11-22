# Authentic N256 second-step cursor (HOLD)

This isolated candidate reads the immutable #6927 artifact archived byte-for-byte
by #6928. It cold-decodes each of the ten authentic first-step cursors, performs
exactly one ratio-bound tail check and (only when the result is still non-unique)
one exact recurrence row action, then writes a canonical second-step cursor.

The parent cursor bytes are embedded in every output. Cold output decoding checks
both envelope digests, reconstructs the parent, and verifies the scalar recurrence
without performing a third row action.

## Fixed budget

- one archived ZIP read;
- ten parent cursors;
- ten new tail checks;
- ten new recurrence row actions;
- zero provider outputs, dynamic steps, matrix exponential actions, Torch calls,
  or optimizer steps;
- one GitHub run attempt; reruns refuse before the archived ZIP is read.

This does not qualify N256, complete the provider, establish arbitrary-history
resume, close the resource gate, explain #6901, change HPCA NoUpdate, or authorize
production adoption. Historical negative, cancelled, and UNKNOWN states remain.
