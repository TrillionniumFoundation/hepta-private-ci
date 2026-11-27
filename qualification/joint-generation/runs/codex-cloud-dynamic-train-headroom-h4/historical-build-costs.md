# T11 historical build costs for H4

Saved cost/identity metadata only. No dataset/model construction, tensor reads, training, inference, evaluation or rerun. No validation outcome metrics are copied. Historical expenses are retained in full and are not new H4 model credit.

Archive SHA256: `369afeca8c5e79e7e1c835f224c4683ad0d298e832e4250c578f529b61044702`
Selection SHA256: `43667a768d2b951b2bf6965c32683a5e9114fb6832a33af924ae161581b5c157`
Source `d45f99d572f13668e79d93b3a7158efa39c597c8`; execution `50be6fa39057596c9f2eff3b3796d805aff6ba9f`.
Freeze SHA256 `1fd8848ceedbb52e9606d3195d236e4980e466a60e792ef212b53e899972094e`; plan SHA256 `df041a749c9f757a6c432cd013603f8eece441014505839398ff079e73d1d085`.
Machine-readable complete ledger: `historical-build-costs.json` (SHA256 `ec7680ce9d289a60dc9e5e6f8d6c93245236785f6808b4ba709eeb3f21c64fa2`).

| Actual cost | N | NC |
| --- | ---: | ---: |
| Complete build CPU seconds | 8.307966292000007 | 8.537556029000005 |
| Consumed declared units | 11958840147 | 11901341862 |
| CPU headroom seconds | 1.6920337079999932 | 1.4624439709999955 |
| Unit headroom | 41159853 | 98658138 |

Each system includes full shared CPU `2.502427883` seconds and `3609293817` shared units. Native compilation `0.38633550400000005` seconds is inside shared CPU and is not added again. Caps remain 10 CPU seconds and 12,000,000,000 declared units. Per-selected-seed build attribution is the complete system total divided by three.

| Actual nonoverlapping CPU component, seconds | N | NC |
| --- | ---: | ---: |
| common_cpu_seconds | 2.502427883 | 2.502427883 |
| active_candidate_cpu_seconds | 5.417421278999996 | 4.98954969499999 |
| shared_scheduler_cpu_seconds | 0.0005181299999996725 | 0.0005181299999996725 |
| refinement_cpu_seconds | 0.00016120200000102614 | 0.003889745999998695 |
| refinement_scheduler_cpu_seconds | 0.012302920000006878 | 0.012302920000006878 |
| critic_cpu_seconds | 0.0 | 0.2697568720000021 |
| selection_validation_cpu_seconds | 0.37389933900000116 | 0.7578752440000045 |
| final_selection_cpu_seconds | 0.0012355390000031719 | 0.0012355390000031719 |

Components reconcile to each original total within 1e-12 seconds. All nine search candidates per arm are included. Nested preparation, validation, controller helper and serialization timings are retained but overlap enclosing phases and must not be added again.

| Actual ledger stage units | N | NC |
| --- | ---: | ---: |
| base_calibration | 35852544 | 35852544 |
| base_compile | 0 | 0 |
| base_data | 0 | 0 |
| base_decoder | 112848849 | 112848849 |
| base_export | 0 | 0 |
| base_pretrain | 3372429000 | 3372429000 |
| base_validation | 88163424 | 88163424 |
| controller_calibration | 0 | 23751864 |
| critic_export | 0 | 0 |
| critic_fit | 0 | 37042218 |
| critic_targets | 0 | 202857987 |
| search_export | 0 | 0 |
| search_setup | 1483308 | 1483308 |
| search_train | 8009792334 | 7610366448 |
| search_validation | 264490272 | 264490272 |
| selection_validation | 73780416 | 152055948 |

The JSON retains every original N/NC stage counter, kernel entry, public price, total, shared receipt and byte counter, including zero-unit compilation/export stages. Declared inventory is not measured hardware FLOPs or CPU time.

| Model | Updates (search + residual) | Digest | File SHA256 |
| --- | ---: | --- | --- |
| ndu-11-0.01.npz | 513 (513 + 0) | `682eb122dc91857d68b902a018f3964c2a6389f9e4501e38b514a1020787871c` | `bb0c6c6afc37b7bc570e18c5689ef953500b2f15daf8e5c86e56d232e3ade201` |
| ndu-23-0.01.npz | 514 (514 + 0) | `398c13eed3c20b578e02d598681d59128108d1df321fed5f62fd9ec930ea1710` | `81ed8b4fb23cf42c819865315b39f2e40931c60e8b8a636e120c47f39ce6ad84` |
| ndu-47-0.01.npz | 514 (514 + 0) | `5e707f4df572f4e13e71d5c85ea7532f84071370efde5560215ef3b283e16804` | `e01f666df8ccb280af8b1552904ded7960eaadfccd599c1d47d3b1b6c95ce597` |
| ndu_control-11-0.01.npz | 488 (488 + 0) | `a710a356825664824bace9aaccc3467ab76214ac4dc3888218e23a62bb791f38` | `e52eec96a9c8a0f0c7584a3b5f1ceb51296aefecb5f35f2c1fd17985d2d3e734` |
| ndu_control-23-0.01.npz | 488 (488 + 0) | `0143471f2cdc19655f9743e165d931da7556f526d742f90f28607d10196777df` | `15022326fd66116b31f5601fbeda3c143079672369ab3ca2bec4646a873b09b7` |
| ndu_control-47-0.01.npz | 488 (488 + 0) | `bb4c4900a4f58fb9ce1c0c70cbe60e25bf4fc70d733bc0f14955bbfd24a3d7df` | `1e15a7d787cb0c0d386a3dcb1dd8f0c4850879da433b0e3edb54172db98f401a` |

All six identities/updates match H4/T11-binding.json exactly. N selected updates are 513/514/514 and NC 488/488/488; both saved refinements completed zero rounds. NC controller identities and complete cost/probe receipts are retained without raw target summaries.

Actual charges versus forecasts: original `system_cost` is retained verbatim. Separate `forecast_classification` identifies service/preparation/arithmetic estimates, unit inventories, observed training-rate inputs, safety factors and tail floors as reservations, not additional charges. Saved N/NC tail forecasts are 0.307938296928005 / 1.3 seconds; they do not replace actual complete costs.

Metadata administration is separate external R&D. Measured preliminary inspection CPU is 5419106183 ns; current extraction CPU is 170457767 ns. JSON states exact boundaries. One preliminary console meter was not retrieved, and an initial metadata-only guard exited 1 before any write due to a legitimate cost-kernel name matching its outcome filter. Their costs are not claimed zero; final serialization/I/O and interpreter/tool overhead are outside the in-file extraction subtotal. Final tool receipt reports this publication process through both writes. None is deducted from historical or H4 actual costs.

Only these two new publication files were written. Original archive, binding, worker manifest, plans, frozen results and prior protected files remain unchanged. No git commit was made.
