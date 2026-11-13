# Exact 5d77ecf2 originals

The source is 5d77ecf2bb107d3431147330a5258d95d11ef348, tree 8fd878b930f15c0b28ed62e6d111a4b4fb3e0c0c. This preserves the failed ordinary A run (0 passed, 1 failed) and two passing filesystem component tests. These facts do not qualify Adopt, evaluated NoUpdate, or cold recovery.

The collector v1 actually failed because native and compile snapshots used different exact key sets. That original failure is retained. The separately authorized v2 accepts only the two observed schemas, compares all common source fields, and succeeded without rerunning the business or native tests.

The original archive was downloaded in version-pinned chunks and every regular member was verified. Its manifest is inside originals.tar.xz. The separate transport archive preserves the collector scripts, launch/status/read receipts, interrupted download evidence, chunk responses, and whitelist-only generation JSON observations. No binary business record was guessed or passed through a writer API.

The readable lifecycle DATA shows starting generation 1 and running generation 2; the retained replay JSON says generation 1. This observation alone does not establish the Root Initial Cell target cut.
