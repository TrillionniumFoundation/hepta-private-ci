# Windows checkout repair

The Windows native-path job fails in checkout before any test executes because
registered compact evidence paths exceed the default Git for Windows path
handling limit. The two workflow files here exactly replay the candidate from
PR #4392, commit `c0ddcc373bd4e63d66f35b1531541973569dd95f`. Both donor preimages
match source commit `cb5019ae86bc52c9baff27858a3ee21cafc89ac5` byte for byte.
The donor is an existing draft; its presence is not reviewer approval.

The new conditional step enables `core.longpaths` before checkout, passes the
same setting through Git's process configuration, and checks its effective
value. The process configuration survives checkout's temporary home directory.
The donor includes six workflow jobs; one currently uses only Linux and macOS,
so its Windows-only step is inactive. Five jobs have Windows execution paths.

Removing only the added steps restores each original parsed workflow exactly.
The Bash configuration command also passed on Linux using a temporary Git
configuration file. Windows checkout and subsequent native tests still require
CI verification. No evidence path or byte, dependency, test command, timeout,
action pin, permission, credential policy, or existing gate changes.

See `validation.json` for exact source and candidate identities and the failed
job URL. The relevant upstream behavior is documented by
[Git for Windows](https://gitforwindows.org/git-cannot-create-a-file-or-directory-with-a-long-path.html).
