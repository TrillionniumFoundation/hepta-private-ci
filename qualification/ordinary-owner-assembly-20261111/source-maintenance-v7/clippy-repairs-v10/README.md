# v10 compile-maintenance candidate — not qualified

This checkpoint follows the failed actual v9 maintenance result 4f1856cd679163e205fad3a11cd554e4722acc38. Its original logs and single formatter postimage remain under ../actual-v9/.

The source manifest contains 202 paths. This commit changes 19 existing source paths through 20 ordered stages and 90 exact forward/reverse-checked operations. The circuit lifecycle receiver change is applied before the six-site Root patch. The three newly manifested paths are the existing Agentd Cargo.toml, Cargo.lock, and Core session/tests.rs.

The changes remove the 19 reported invalid guard-across-await sites while retaining the same registered original JoinHandles, cancellation custody, original results and failures, single result delivery, and strict completion observations. Agentd uses the already locked workspace futures dependency; the lockfile changes only its dependency edge. No package version or checksum changes are included. Eight legacy Core component initializers explicitly lack the new original outcome side record; strict original shutdown continues to refuse missing evidence. One existing component actor literal is corrected to the parser's UUID format. These are component fixtures, not business actors or acceptance evidence.

The attached reviews and exact replay proof are static checks. New component tests have not run. The metadata semantic recipe is a proposal awaiting actual formatter postimages; it is not a replacement CALLERS file or a checker result. No lint/checker weakening, original deadline change, new business receipt, independent consumer acceptance, or actual daemon/Root restart is claimed.

The next maintenance run must bind this exact commit, tree, and manifest before fmt/fix/bins. It is separate from the unchanged original checker, seven-package/Root17 harness, and the additional Core/AppServer/MCP plus full workspace gates. Original harness bytes and budgets remain fixed. All future results require actual execution on their bound sources.

PR #6006 remains Draft at d9737937eaccccf2ed2f1f79444ddec6c10d0eea. Original staging remains cbf6ca7dd619589be3e9e98755f185d34d0f7413. Business ordinary/adopt/NoUpdate-or-rollback acceptance counts remain 0/0/0.
