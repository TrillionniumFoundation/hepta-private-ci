# Frozen source exclusions and remaining catalog capacity

## Result and scope

The inspected evidence establishes a **minimum hard exclusion union of 69 source groups**. The exact released catalog contains **178 groups: 97 train, 54 development and 27 retention_validation**. Of its 81 development/retention_validation groups, 65 are in the known exclusion union. **Sixteen remain outside that known union: 7 development and 9 retention_validation. This is an upper bound, not 16 certified unseen groups.** Current complete exposure coverage is not authenticated, so verified unseen capacity remains **UNKNOWN**.

This is a metadata audit. The single original-host inventory observed at **2026-11-11T05:32:15.447672+00:00** opened three pinned metadata files and emitted source/split/exposure fields. It executed **0 models, 0 actor episodes and opened 0 reference-content files**. It did not create source identities, change roles, lower a gate, modify qualified source, move a branch or authenticate an original memory owner.

## 1. Exact exclusion union

| Evidence category | Groups | Counting boundary |
| --- | ---: | --- |
| Frozen model training | 2 | Exact MODEL training groups, corroborated by selected-sources |
| Tuning | 1 | Exact selected-sources tuning group |
| Public quarantine | 2 | Exact pinned historical exposure ledger |
| Original working-state retention PLAN | 14 | Original PLAN hash verified on the retained host; independently listed in MEM5 PLAN |
| MEM5 selector PLAN | 14 | Original ZIP member bytes and PLAN hash verified |
| MEM6 working-state PLAN | 20 | Exact jointly frozen prepare receipt, matched to the previously extracted CAS PLAN |
| MEM6 selector PLAN | 14 | Exact jointly frozen prepare receipt, matched to the previously extracted CAS PLAN |
| Earlier cell-causal pilot | 4 | Published selected-sources/PILOT_PLAN and aggregate evaluation record; two overlap the MEM union |

The first seven categories form the MEM lineage union of **67**. The four earlier pilot groups add two further exclusions:

- `merchant-2cb679f1d8580a2031d3b615`
- `merchant-8e19a10d6e734747ce3246eb`

Both are retention_validation in the pinned catalog. The other pilot members already occur in the MEM union: `merchant-29033083587ed7b9e3842425` is in original retention, and `merchant-1e4ef8758b5cbae31ea96ae7` is in MEM6 retention. Thus a claim of globally new sources cannot be inferred from disjointness against only the old MEM exclusion union.

The earlier aggregate reports 960 planned and 960 dispatched pilot episodes. This audit does not independently reopen their per-source raw outcomes. Prior planned/reserved membership is sufficient for conservative exclusion; those counts are not new executions or a new efficacy result. Historical MEM denominators and scores remain unchanged.

Every one of the 69 IDs has exact evidence paths, JSON fields, SHA256 pins and all overlapping categories in **EXCLUSIONS.json**. Of these, 68 occur in the released catalog: 3 train, 47 development and 18 retention_validation. The remaining quarantine ID, `merchant-d93e19ca396d00036f1a51d5`, is outside this released catalog; its role is left null. No sealed-role identity is invented.

The 97 catalog train-role groups are outside the existing released-role protocol. This does **not** mean all 97 were trained on. Only the two model-training IDs and one tuning ID are established here. The older collection design mentions other model-fitting/tuning counts without providing their full identities in the inspected manifest; this audit does not invent those IDs or treat the omission as proof of nonexposure.

## 2. Capacity calculation

| Calculation | Count |
| --- | ---: |
| Released development + retention_validation catalog groups | 81 |
| Excluded by MEM lineage alone | 63 |
| Additional excluded prior-pilot groups | 2 |
| Excluded by full known union in candidate roles | 65 |
| Remaining upper bound | 16 |
| Remaining development | 7 |
| Remaining retention_validation | 9 |

All 16 have at least one complete episode under the **existing working-state** family rule: five required families for development and text_image_complementary for retention_validation. This does not establish the predecessor/successor sequences or coverage required by a new episodic experiment.

| Source group | Original released role | Complete legacy episodes |
| --- | --- | ---: |
| `merchant-202f6f74f9fec567cfbae596` | `retention_validation` | 1 |
| `merchant-21115e1df794f9b2c1e28d63` | `development` | 1 |
| `merchant-24ad6a0e21bba91ff8e6c41d` | `retention_validation` | 1 |
| `merchant-4dbbcc32865a7921af181694` | `development` | 1 |
| `merchant-4e8ef8d74282af470042df7a` | `retention_validation` | 1 |
| `merchant-61e249d2d82805d7885bef63` | `development` | 1 |
| `merchant-62305f149a91fd62b9194b6a` | `retention_validation` | 1 |
| `merchant-78b0a327e7fd947acb7f2ac5` | `retention_validation` | 1 |
| `merchant-83e3cd2399f8af4d0dadda2f` | `development` | 1 |
| `merchant-85cb99d0cfd415fd6340fbd0` | `development` | 1 |
| `merchant-973a6ea29a979e60d77163d3` | `retention_validation` | 1 |
| `merchant-ac3d668a213b7a560b39fa8f` | `retention_validation` | 6 |
| `merchant-ac7dff025170a6ee898d500b` | `development` | 1 |
| `merchant-c50192ce31401f599190eac2` | `retention_validation` | 1 |
| `merchant-ca151eda1f416e786fbaf2d1` | `development` | 1 |
| `merchant-ca8421c835a4380f2fcb609f` | `retention_validation` | 1 |

All rows have current exposure status UNKNOWN and are **not admitted** to a new study. Remaining outside the inspected exclusion union is necessary but insufficient evidence of being unseen. The catalog and source-group hashes also do not prove independent grouping or authenticated source custody.

## 3. Keep the working-state and episodic thresholds separate

| Requirement | Exact source and field | Applicable experiment |
| --- | --- | --- |
| Minimum 20 groups; at least 4 per role | `qualification/memory-cell-mem6/ACCEPTANCE.json`, `/prospective_benefit_gate/minimum_source_groups` and `minimum_groups_each_role`; SHA256 `d77624e729b02213eec9bc808b94ee27c839a66883d63ede3455a3ca4f6f14ea` | Working-state primary contrast `bounded_minus_current_only`; explicitly an engineering target, not a power calculation |
| 16 development + 4 retention_validation | Original CAS `retention-request.json`, `/groups_per_role`; SHA256 `93ceb3d22077f4c7b10dc8d8850b868d8a70c8b226346a919287cd7c85bfc107`; confirmed by PLAN `a8618ffa21985c8e9267d8fd50663bd9737568a14d05904ce05d5c6efea92e53` and exact launcher `35a5906b50e1371d82272468fbc184b06cb24d46e87b15cb81266fe36e1850de` | That already frozen MEM6 retention campaign; not a universal allocation rule |
| Separate pre-execution protocol, new sources/sessions, four baseline contrasts | The same ACCEPTANCE file, `/real_successor_task_gate` | Episodic E successor study; no numeric source minimum or role allocation is specified in this inspected gate |

Even under the optimistic assumption that all 16 residual groups are unseen, the existing W 20-group gate cannot be met from this catalog remainder. At least four additional eligible groups would be needed for the total minimum; retaining the actual historical 16/4 allocation would require **at least nine additional development groups**. The five surplus retention_validation groups cannot be relabelled development.

Those are W comparisons only. **E capacity adequacy remains UNKNOWN until its separately required protocol fixes a justified independent unit, numerical roster and allocation before reference/outcome access.** This audit does not transfer W's minimum to E or select a smaller E gate to fit the remaining stock.

[Exact acceptance](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/66f570a77c60aac8d33e6cbeac8dfd120ef1d867/qualification/memory-cell-mem6/ACCEPTANCE.json) · [Protocol](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/66f570a77c60aac8d33e6cbeac8dfd120ef1d867/qualification/memory-cell-mem6/PROTOCOL.md) · [Actual launcher](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/66f570a77c60aac8d33e6cbeac8dfd120ef1d867/qualification/memory-cell-mem6/run-001/launch.py)

## 4. Evidence and reproducibility

The MEM6 CAS archive is 61,412,948 bytes, SHA256 `f77acd9feb27fda3f8000b0d089dbdbe258a4adfb7acedcb2e0cd590cc4f361e`, archive commit `b66d74d4a61b15f3d9e1eb3b5ddfa251777ee4c1`. Before the local execution environment became unavailable, its full SHA and selected PLAN/REQUEST/MODEL objects were verified. It is a content-addressed archive; logical paths map through MANIFEST to `objects/<sha256>`. External runtime inputs are explicitly not included.

The one later authorized host job is `1a1c917a98a-135c4-3d9`, request key `mem-next-source-inventory-ed353817-20261111-v1`, request digest `d8723bd0bd549e07fe14157310fb3c3bff82826df6a2cc07e16e3711ae49826f`. It completed once with exit 0, no retry, no truncation and empty stderr. Four contiguous offset ranges reconstruct exactly 58,248 bytes of stdout, SHA256 `e7c0e282168dc4ad02b3f4ed49b8d25393cf98b285039d8b3daf19d83d9a6ae5`. That exact output is Git blob `e7c94c3558d3a17bc9c8fbb42cf955de3ce0b207`, already fully read back.

The reader hashes and reads only the known catalog, exposure ledger and original baseline PLAN. It checks original size/hash and stable file identity, then emits bounded metadata. The catalog pin is `8433d0c026b0818f8e60ee2f0ae7e7b57c57ae35cbb72cf212b89895b97d0904`; registry is `09d5f57c5c4c5f421f16c51febd048b7746d5d52723d825240f8655bf7fbdd07`; historical exposure pin is `6722edfc88e1089bcaf0fba9727c233416830fdc6682b461422d26bdfd4cb6af`.

After environment loss, the retained tool outputs were independently reconstructed in JavaScript. The MEM5 ZIP's complete fetched bytes were rehashed; only its PLAN and REQUEST were inflated, and both matched the original pins. The frozen MODEL was recovered byte-for-byte with its original SHA. Public PREPARE and protocol files were reread at immutable commit `66f570a77c60aac8d33e6cbeac8dfd120ef1d867`. The category union and capacity were recomputed from those verified bytes, without another host job.

`audit_source_exclusions.py` is a standard-library, offline audit: it validates all retained input hashes, the host byte ranges, source membership/roles, per-group provenance and the W/E distinction. With `--mem6-archive /path/to/mem6-cas-001.tar.xz` it additionally rechecks the full CAS and selected original objects. After the environment recovered, the full Python audit **actually completed with exit 0**: all 17 retained input files, all 69 per-group provenance pointers, the entire 61 MB CAS hash with seven selected metadata members, and the MEM5 ZIP's two selected members passed. The output in `OFFLINE_AUDIT.json` still leaves global exposure UNKNOWN. The earlier executed JavaScript replay and full Git readbacks are separate corroboration, not additional actor executions.

## 5. Concrete inputs still needed

1. A complete, pinned source exposure event ledger through an explicit cutoff, covering relevant hosts/consumers, training, tuning, collection, prior actor access, failed or abandoned requests, pilots, reservations and later runs. It must bind source IDs and revisions to this registry and state its coverage; old ledger bytes cannot attest current completeness.
2. If W continues, additional authorized released source inventory sufficient for its unchanged registered allocation/gate. If E proceeds, its separately registered real-actor sequence roster and statistical plan must first fix the source requirement. No additional pinned stock was established in this bounded inspection.
3. The actual original source verifier custody, retained production writer identity/current cut, final-use authority and effect-owner state. This source ledger supplies none of those capabilities and does not close original-owner, independent-trust-domain or actual-effect cold recovery.

Scientific state remains **HOLD / NOT_EVALUATED for new successor benefit**. Archive restoration, metadata inventory, software qualification and real actor benefit remain separate evidence.
