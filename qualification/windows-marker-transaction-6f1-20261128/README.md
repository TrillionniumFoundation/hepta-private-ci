# Exact setup-marker transaction diagnosis

The original Windows run 46086738399 / job 140797955764 failed naturally. CLI passed in 6.1 s and exec-server passed in 14.7 s; Core had six failed attempts out of twenty, including two marker consumers and the subagent stop case. The original no-FLAKY gate remains failed.

SBX_DEBUG identified an empty setup marker: JSON parsing reached EOF at line 1 column 0. The two source changes add bounded, opt-in diagnostic phase records (process, fixed phase, mode, refresh-only flag and marker length) and read them only when the original completion check fails. They do not accept an incomplete marker, change its DACL, replace CREATE_NEW, extend a timeout, or alter provisioning success. This is a diagnostic candidate; the marker defect is still OPEN.

Independent Mac comparison retained the exact original subagent case. The original d8 waiting code failed with the same 10 s event timeout. A temporary event-only probe observed a child completion notification on the selected parent queue. The separately owned request-selection patch then passed the complete original case in 0.675 s, preserving request/event/hook budgets and every old assertion. Its actual before/after source and patch are included; that patch is not introduced by this diagnostic commit. All temporary source modifications were restored.

The archive contains complete original raw logs, the complete original GitHub artifact ZIP, metadata, source preparations, all three Mac attempts, and their exact drivers. Every member was independently read back with matching bytes and mode before commit. Historical failures are not relabeled as successful Windows qualification.
