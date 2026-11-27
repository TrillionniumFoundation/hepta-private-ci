# Supervisor source union evidence

The original Linux package run passed all 136 executed tests after a
durable restart count recovery repair. One existing controlled child
fixture remains ignored as a standalone test and is invoked by the two
real process tests. The prior run with 130 passes and one failure is
preserved together with its source vectors and original logs.

The six reviewed source changes combine the incoming branch behavior
with the existing cold recovery and signed intent checks. A later
three-file repair restores consumed attempts from one validated durable
read and adds five regression tests. All original assertions, guards,
timeouts, features, and retry settings are retained.

Each physical carrier is an independent gzip file. Use the ordered
carrier list in manifest.json.gz: decompress each carrier, concatenate
the decoded bytes, verify the original archive hash, then decompress
the reconstructed archive. Check every extracted original against the
same manifest. No original evidence byte is rewritten.

All four native stages preserved 7766 native and 8081 total inputs.
These results qualify the specified Linux package scope only.
