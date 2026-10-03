# Real snippet-ink regression

These are unchanged, account-free native/browser screenshots from exact
58a94b59 run37114389901, with hashes and artifact IDs in identity.json.
They are test evidence only and are never application resources or UI overlays.
The original native image passes; the original browser image fails despite its
fully visible34px Html container. Its first ink row sits7px below native and its
wrapped second line is sliced. Geometry was read from the same unchanged native
fixture layout after the font-cache repair; ready-font metrics are supplied to
isolate the independent pixel failure. Fresh captures must provide their own
real Rust geometry and are checked directly, including the two-line sample.
