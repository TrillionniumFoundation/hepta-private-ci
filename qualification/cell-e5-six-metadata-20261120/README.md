# E5: six additional source candidates, metadata stage

This independent continuation starts at `705797ce07ca90ab4c520f0c6ae632b2e783acc8` from #6777. `INTENT.json` freezes six named repositories before any candidate metadata or license retrieval. All six are disjoint from the 36 earlier/future exclusions and the 12 already declared source candidates.

The existing first-ten rule is unchanged: merged pull requests with `fix` in the title, ordered by creation descending. This stage may inspect repository/PR metadata, changed filenames and exact license notices. Runtime/test patches, native children, model calls and training remain absent. Every inspected rejection or lack of a candidate will remain in the selection audit.

A metadata shortlist is not native admission. No new source, user, model or training update is counted, and E5 source growth remains unqualified.
