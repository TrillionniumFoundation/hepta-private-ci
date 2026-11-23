# Blind inventory of unused piano and guitar recordings

Dated 23 November 2026. The target is twelve previously unused production sources, six for each instrument, four physical 2.88-second windows per source, with the original frontend and price 0.30. This inventory used recording credits, source identifiers, posted licenses and original-byte timing. No candidate predictions, evaluation outputs or alternate clips were opened. The exact readout seal is 2131f343c5055eae0237d842e630f3fbc7a502ec. No original video was downloaded or redistributed in this inventory.

**The present cache cannot supply the cohort.** One unused piano recording has a first-party public-domain release, independent recording credits and all four windows. A second qualifies on the previously used publisher-license-record basis, with Commons verification of the external license pending. No cached unused guitar recording passes the four-window rule. On the two stated rights-evidence levels respectively, the deficit is five or four piano productions and six guitar productions.

| Inventory level | Piano | Guitar |
|---|---:|---:|
| Historical exclusions across both cohorts | 22 | 22 |
| Unused pages in the existing combined metadata | 24 | 37 |
| Unused pages in the 71-page lab3 catalog alone | 20 | 28 |
| Unused local originals verified against published size and SHA-1 | 4 | 2 |
| Those originals, bytes | 199,776,956 | 15,772,186 |
| Original four-window clock, PCM and frame checks pass | 4 | 0 |
| Published primary instrument and distinct credited production, including the pending license review | 2 | 0 |
| Same, with a directly verifiable creator release | 1 | 0 |

The original two rosters have 22 works each, with 19 and 22 upload accounts and 21 and 22 production groups, respectively. Their 44 distinct files, which include all of the historical gallery and partitions, exhaust the previous eligible set. There are 41 historical upload accounts. Lab2 and lab3 together have 105 unique publisher pages and 50 cached media originals. All 50 full files (1,743,895,513 bytes) were streamed to calculate SHA-1 and SHA-256. Byte length and SHA-1 match every publisher record. The other 55 unused pages have no local original in the two caches. No raw media files appeared outside them in the current workspace search for .ogv/.webm/.mkv/.mp4/.avi files. Independent production means distinct credits, uploader and work under the contemporaneous protocol. Public metadata alone cannot establish the identity of an uncredited participant or exclude uncredited overlap.

## Six unused originals

| Page ID | Bytes | Recording and disposition |
|---|---:|---|
| 9917138 | 49,447,512 | Rerumirf released their own recording of the Steinway Duo-Art playing the Saint-Saëns roll 5973-4 into the public domain. All four quarters pass. Different work, roll, instrument and recording credit from the prior Chris Strobel Weber player piano. [Publisher](https://commons.wikimedia.org/wiki/File:Steinway_piano_-_Duo-Art.ogv) |
| 121725321 | 60,427,464 | Leezy's filmed Chopin cover, posted to Commons by 冷床系. Four quarters pass. The page identifies the external release as CC BY 3.0 and explicitly flags it for outstanding administrator/reviewer confirmation. [Filed revision](https://commons.wikimedia.org/w/index.php?oldid=1033467732) |
| 66612778 | 80,183,820 | Eri and Mari Yoshizawa duet, Yamaha recital. Uploader Elisfkc, original Flickr contributor spontaneity. Four quarters pass. The upstream description names the pianist as composer, and Commons categorizes the video under pianos and violins. The metadata substantiates a distinct production and reviewed CC BY 2.0. It leaves the preregistered primary-instrument label unresolved. [Flickr original](https://www.flickr.com/photos/spontaneity/4326354048/) · [Commons revision](https://commons.wikimedia.org/w/index.php?oldid=1146831930) |
| 67928188 | 9,718,160 | Four quarters pass. Commons credits turbine1974 for production and explicitly describes the piano sound as synthetically generated in German. The English description identifies only the composition. The design excludes synthetic score demonstrations. [Publisher](https://commons.wikimedia.org/wiki/File:Franz_Schubert_-_Moments_Musicaux_opus_94-3.webm) |
| 22010132 | 2,712,554 | Tomschryer's physical guitar demonstration, CC BY-SA 3.0. Quarter one has 294 rejected starts because of source-clock discontinuities. [Filed revision](https://commons.wikimedia.org/w/index.php?oldid=1292680295) |
| 34218111 | 13,059,632 | Grimes 2014 guitar study, legato supplement S2, CC BY 4.0. Quarter two never succeeds. The receipt records 476 discontinuities and 14 seeked PCM timing rejections across the complete search up to failure. [Filed revision](https://commons.wikimedia.org/w/index.php?oldid=1223481965) |

Leezy and Rerumirf were ordered technical backups in the second catalog and never joined either selected roster. The two old-cache piano originals lacked prior four-quarter receipts. Running the frozen physical-only qualifier produced 4/4 for each, using the original code, PCM, causal frame and physical clocks. The archive holds those new receipts and copies of the four historical receipts. The search accepts the first originally permitted start in each quarter and never changes the cost, source facts or window-placement protocol.

## Why further access to this catalog alone cannot yield six new guitar sources

Among 37 unused guitar pages, 24 use one of the 41 historical upload accounts. The 13 remaining pages use only seven new accounts. Five of these seven accounts have no eligible work in this catalog. Tomschryer's cached source fails the clock gate. Both OptimusPrimeBot videos name the historically used U.S. Department of State as producer. The Anass Sedrati and Koffermejia recordings are 11.918 and 6.481 seconds respectively and cannot fit the four guarded quarters. Maximilian Schönherr describes a sampled six-button toy.

Four uncollected physical performance leads share Open Access Media Importer Bot. Two belong to the same 2014 Grimes production, and the 2009 and 2013 guitar/EEG recordings share credited investigators. The common uploader rule permits at most one. Under Lorgut, the published description identifies an illustrated lesson about guitar parts and does not document a performance. Even provisionally allowing that page pending new documentary evidence, the upper bound in this **closed 105-page catalog** is two guitar production slots, neither currently verified. A broader catalog is outside the inventory.

For piano, documented leads without local full originals include the Latsos duo (two works, one uploader/production), PoseidonSports, Darren Foreman's Musée Mécanique recording, a Kyiv pianist recorded by Сарапулов, and a PAX East recording credited to Ledundead. The counts above give these pages no credit toward a complete four-window source.

## Audit material

- `inventory_summary.json` contains the counts and hashes of the original rosters and protocol.
- `unused_works.json` lists the exact 61 unused pages, published SHA-1, byte length, attribution and disposition. All 13 guitar pages with fresh uploaders have explicit rulings. “Metadata lead” requires later original-byte, rights and physical verification.
- `historical_exclusions.json` records the 44 excluded production credits and accounts. `verified_local_originals.json` records locally recomputed SHA-256 and SHA-1 for all 50 original files.
- `physical_*.json` and `original_receipt_*.json` retain every accepted starting time and the failure-quarter diagnostics for the six unused original files.
- `probe.py` and `inventory.py` are the physical replay and the inventory builder. They run from the original workspace root with the prior media caches and sealed decoder available. `SHA256SUMS` binds the complete delivered inventory.

No statement about legal ownership or physical identity beyond the cited creator/hosting records is implied.
