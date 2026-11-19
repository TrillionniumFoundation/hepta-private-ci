# Original MEM8 V5 Bazel lock CI evidence

Both original hosted runs are retained with their entire artifact ZIP and full
decoded job log. Initial 8ead / run 43020198388 failed before the lock phase:
the version preflight compared a successful cold-download stderr banner plus
stdout version to the exact expected string. It executed zero lock commands,
native project tests and model calls. Its RESULT has clean-before but no
source-after field; this archive does not invent one.

The independent revision-2 harness d03 / run 43020939762 tested the same pure
source 9bd2f589debdba4a93baa363817c3669cb103721 /
c77785ecb368c44ea699769001a47402c9f50591. Only that probe's evidence streams
were separated. It retained strict stdout equality and the original 30-second
probe and 1200-second lock-command budgets. The original exact-source wrapper
ran just bazel-lock-update once, completed in 26.462319 seconds, and observed
unchanged clean source, identical two lockfiles, unchanged actual tools and
Bazel binary. No project-native tests or model calls occurred. The original
warnings remain unmodified.

The initial ZIP has 36 members with its complete 29-member records tar;
revision 2 has 52 members with its complete 44-member records tar. The tars
include hidden repository configuration paths omitted from scattered artifact
uploads. All original bytes are preserved. Run python3 verify_bundle.py with
the unpacked package path to verify every byte, both original API identities,
all raw/receipt bindings, the complete recorded Git Merkle trees and the exact
two-outcome distinction. The verifier executes no host, Bazel, compiler or model.

The numbered raw pieces are an immutable storage transport. Concatenate them
in index order, verify the complete archive SHA256, then unpack. Computed
object IDs in an unuploaded manifest must not be mistaken for actual creation;
actual publication receipts are recorded separately.
