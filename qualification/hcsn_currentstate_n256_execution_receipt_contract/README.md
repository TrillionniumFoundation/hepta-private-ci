# N256 execution receipt contract — HOLD

The frozen admission/execution bridge binds a future provider admission, atomic
execution freeze, and three-stream manifest, but the manifest itself carries no
immutable proof that the exact key, host, and capture session completed inside
the frozen execution interval.

This source-only stage adds that missing fail-closed boundary. A future receipt
must bind the admission, freeze, canonical manifest bytes, execution key, host,
capture session, start/completion timestamps, successful exit, and preservation
of historical RED/UNKNOWN. It cannot self-grant qualification or production
adoption.

Synthetic fixtures test parser and cross-binding behavior only. They do not
supply any of the ten future originals, allocate a key, execute N256 numerics,
call the provider, or create an authentic receipt.

Status: **HOLD / NoUpdate / all_closed=false**.
