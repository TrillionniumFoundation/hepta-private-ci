# Restore exact original records

Concatenate manifest parts in order. Verify each part and the whole ZIP by
byte count and SHA256, then check ZIP CRC and every member's path, size and
SHA256 before extraction to a new directory. Preserve original receipt bytes
and recorded absolute paths. No new execution is implied by restoration.

This snapshot packages closed records or frozen preparation files. Readable
copies elsewhere duplicate evidence for review, never calls, cost or samples.
