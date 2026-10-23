# Actual-source reintegration snapshots

The round-three Agentd audit starts from integrated main `997e7beef8151160065df36b024bc8da5c989e93` and preserves the previous audit at `64e38ca5786027fcc789aad36131875e581175ac`. Its new Git parent is the actual integrated main commit; the earlier audit remains a separate historical branch.

The index preserves complete maps from both actual Git objects for 27 source anchors outside the integrated ancestry. Each snapshot records its real commit/tree, map blob and full original fields. Current maps use the real integrated main as a provenance anchor, then require the official clean-source migration and exact qualification verification. The snapshots establish source navigation only: they do not prove current test execution, grant authority or raise qualification flags. Existing older origin snapshots remain intact. No Git parent was fabricated and no ancestry check was weakened.
