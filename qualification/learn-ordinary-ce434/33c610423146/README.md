# Exact 33c61042 focused fixture qualification

Source 33c610423146597a3d1102efe77f09507477673e, tree 5d7cea0336f4eca767967a8938734c92ed81ff43.

The original durable job 1a1cbabc5e0-2564-c4d actually passed all six selected native cases: the five failures from exact 8f7 plus the new original evidence-peer idle regression. No retry, error or skip was accepted. Raw terminal pass rows and fresh JUnit agree exactly on package/name/suite. Source SHA/tree and clean status are unchanged before and after.

The original same-source helper build and verification passed. The same fixed source also passed 131 source-closure tests and 12 report-parser controls; just fmt and diff checks made no source changes.

The real merge preserves both the Training timestamp fixture fix (a293dc8b4ce43e0ce432c4ce4552f3ba7d746000) and peer fixture repair (d02af206770255fb0a9c5e44bfe01484b408c2b9). The latter retains the existing HostAuthorityPeerChannel, one 300-second session, and a 500-millisecond complete exchange. The old 5-second / 2-second quick negative fixtures and all production deadlines are unchanged.

manifest.json binds unchanged original records, recorder-named raw log, fresh JUnit and source/parser logs. The focused driver is copied as executed. The terminal JSON is a structured readback from the original job service.

This result is not a complete four-library native pass. It does not qualify later SourceCapture, Material service or positive Selector changes. Complete ordinary positive adoption, complete ordinary NoUpdate/fallback and actual daemon plus Root cold restart remain 0 accepted instances. Earlier c778 and 8f7 failures remain separately retained without relabeling in the sibling native-failures directory.
