# Actual matched training and frozen weights

Both separate cold-parent fits completed 32 optimizer updates and their original owner exited zero. Training execution source/admission is `78099aa6af4c70c00f26cb11888e20aa59510014`, with executable files identical to corrected source `02b3fb49ac00ccb7ad28e5d803af5675fbd28e26`.

`WEIGHTS_FROZEN.json` has SHA `2ab883c01843a4f29875f00b209ee9cc6ed7d4040fddd5ee297723bb5b276e63`, with exact creation time `1795035781626593132` nanoseconds. Native feedback remains the prospective primary; document evidence remains the control. Both started with original P parameter digest `e5da16c3256c27f06f42ecac69880ce8802a0eb3a87c05830d11c09477aa817f` and empty optimizer state. No B3 task material had been read by training before this freeze.

| Actual arm | Outer full F/B pairs | Supervised positions | Padded positions | Unpadded input positions |
| --- | ---: | ---: | ---: | ---: |
| Document evidence | 72 | 14,304 | 258,048 | 184,112 |
| Native feedback | 72 | 14,304 | 258,048 | 184,352 |

Both recorded 56,448 original forward softmax entries, 56,448 backward original entries, and 56,448 backward recompute entries. Full per-step shapes matched exactly. These outer F/B counts do not equate the physical cost to old eager runs. Each peak allocated/reserved CUDA memory was 4,805,570,048 / 5,135,925,248 bytes, within the unchanged 70% cap.

The owner measured 651.106 seconds for document evidence, 649.078 seconds for native feedback, and 29.739 seconds for the final audit. Internal training timers are nested within these windows and must not be added again. CPU-package energy is a whole-host observation; GPU/network energy and monetary cost remain unknown.

The exact 4,080,060-byte complete archive was retained on desktop and all members verified against INDEX. Its SHA is `be146f6ad22f52c0b9c9f949e57a079f40a446635a33f6dc82e1b773ef588109`; the complete binary is attached as `ACTUAL_TRAINING.tar.xz` using the existing exact-byte/path asset policy. It includes both real adapters and original training receipts; base weights remain referenced by their already frozen manifest.

This is completed training, not an observed task improvement. The original A 24-generation evaluation completed with 24 patch-admission rejections and no native child executions. Its two arms each scored 0/4 first, 0/4 final, and 0/4 on common parent prefixes. The necessary A promotion condition therefore failed. The originally prescribed B3 32-generation evaluation is running after the independently verified release; no training, A call or score is being repeated or changed. All prior failures, numerical rejection, NoUpdate decisions and unclosed research/adoption qualifications remain unchanged.
