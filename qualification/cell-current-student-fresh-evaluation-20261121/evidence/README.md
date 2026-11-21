# Original code-validation receipts

`validation.tar.gz.base64` retains six local offline-control runs and the
original remote formatting command, its durable terminal status and exact
post-command file inventory. `CONTENTS.json` binds every retained raw file.
Decode Base64, decompress gzip and inspect the tar members to read them.

The final pre-format run passed 10 synthetic controls in 0.034 s. The initial
local import failure and earlier control runs remain visible; they are not
scientific/model experiments. The actual repository `just fmt` returned zero
and reported that no changed files needed formatting. It changed no bytes;
this is not a claim that a language formatter checked these qualification
files. All nine source/doc files were independently read back byte-identical.
No tests ran after formatting. No candidate-source content, actual models or
native upstream test children were executed in this code-validation lane.
