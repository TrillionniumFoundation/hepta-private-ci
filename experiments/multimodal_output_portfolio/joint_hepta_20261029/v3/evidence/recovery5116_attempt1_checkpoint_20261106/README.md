# Fixed ARM recovery: first attempt

This packet preserves the complete original failed recovery artifact, original console, source binding, API snapshots and independent audit for PR #5116, run 42280081679, job 128106496652, attempt 1. Its exact source is 7eea44fd62d75579e85c49666ffe44303bfddde9 and tree 07f129414cf4058d66bdac5e582c517f5b428119, with the original #5106 parent.

The source guard passed. The archive phase then raised TimeoutError. The public receipt contains a fixed phase and exception type, with no signed URL or external exception message. The precise API versus storage download subphase is unknown. No completed original ZIP hash, directory catalogue, projection part or internal ARM build error was recovered. Qualification and promotion remain false.

The 693-byte artifact 13534519226 has SHA-256 fdfebaa9f2546fd737004b23f639fc3a319377e46976fd89070fe42503290c3f. Its sole member, RECOVERY.json, was independently read and CRC checked. The complete 1,453,062-byte original console is retained; its SHA-256 is 531770a3876e16649b10a863d5798a97c7219ed8027c7c5391bfa9e59453d105. The raw API tool response is retained separately.

The original collector has no credential scanner. This is a bounded preservation of existing evidence in the same private repository. The source action's official locked artifact 2.3.2 package and API declaration are included: its documentation explicitly permits repeated artifact names across reruns. No claim is made that a later attempt preserves old Actions download visibility. No workflow, timeout, source guard, input identity or collector bound is changed here.

After this checkpoint is committed, one identical job retry can test the observed network failure while retaining attempt 1 independently of Actions retention. This packet does not represent a retry result, a recovered projection, a build pass or current product qualification.

Run `python restore.py /absolute/new-directory` to restore every listed input as inert regular 0644 files. The reader is the previously reviewed bounded reader with only its fixed INDEX hash replaced. Every gzip wrapper contains one bounded segment of the XZ archive; all wrapper, segment, archive, file and roster identities are checked before restored files are written. INDEX records original modes; the reader never restores executable permissions or executes archived code.
