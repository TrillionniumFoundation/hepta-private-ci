# Reviewed SDK diagnostic source amendment

The original port source guard correctly rejected the SDK diagnostic changes
introduced after its earlier source records. On pull request 5058, run
42236430509, producer job 127955133360 executed 82 Python checks and reported
two failures and four errors before starting the generator. It uploaded no
candidate artifact. The original decoded log is retained in the gzip file.

The current source was independently bound to commit
`2b8cd4eb823a2ba4ac0469543f1036e6197d50c9`, tree
`f856e8df96c65ac72421dfcffc765b4da6efc014`. Complete current subtrees and
unchanged prior subtrees reconstruct that exact tree with 14,849 files.
The 35 original paths plus existing amendment sources form a 321-path review
set. Its only differences are the two SDK diagnostic files already reviewed
in pull requests 5049 and 5076. The generated artifact snapshot still has 320
paths; the extra reviewed path belongs to the earlier formatting amendment.

`SOURCE_AMENDMENT.v7.4.json` binds those two exact successors, the five prior
source records, the unchanged Cargo and Bazel locks, the current source
identity and the original failure evidence. Its digest is fixed in the common
guard. The historical recipe, integration record and amendments remain
unchanged. Index checks, committed bytes, file modes, the vendor graph and
the original dependency policy still apply. No other source or lock change
is accepted by this amendment.

The producer exports the new record. Consumers compare its identity and
transport bytes against the same checkout; the independent Synapse source
preparation also retains it with the producer provenance.

The prior Unit 17 local replay used the earlier SDK fixture bytes. It did
not qualify the later diagnostic changes. The new local source checks use
both actual current SDK files, real temporary Git repositories and all 89
port tests, including seven new diagnostic binding tests. They do not run
Cargo, Bazel, Synapse or a Windows process. The unchanged native generation
and full source CI remain necessary; no native success is claimed here.

Each gzip file contains one complete original byte stream. Decode it with
the standard gzip utility or Python's gzip module. The source comparison
and provenance provide exact identities; the amendment binds their archive
bytes. The test log records the actual local test names and results.
