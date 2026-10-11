# Explicit memory namespaces for source-written knowledge

The controlled source writer shares one adapter across multiple admitted scopes.
Identical entity names can have different attributes in different scopes. Earlier
write/read prompts carried question text and observation time but omitted scope;
timestamps cannot serve as entity namespaces. A counterexample uses the same
entity, relation and time with two distinct values in two admitted scopes. This
is a real input ambiguity, not evidence that every earlier incorrect answer was
caused by that ambiguity.

`experience_memory.render` now includes exact bounded UTF-8 `memory_scope` in
both source-writing prompts and parameter/evidence read prompts. Question IDs,
family IDs, final task labels and gold answers do not become prompt features.
Existing scope/source/withdrawal admission remains responsible for authorization.
A namespace in a prompt is NOT isolation against arbitrary cross-tenant extraction;
this remains a controlled, jointly admitted research corpus, not private-tenant
model deployment.

The writer profile is now `hepta.controlled-source-knowledge-write.v2`. Existing
snapshot reader-profile validation rejects v1 scope-blind snapshots under v2
semantics. Do not relabel or reuse old model answers as v2 execution. The pending
v1 run remains separate; no running job is intentionally cancelled by this fix.
A new scoped writer must train and reload its own artifact to test task effects.
Neither correct input binding nor unit tests establish a model accuracy gain.

The independent read-policy experiment uses EventPresentationReader and does not
change with this scoped ExperienceReader fix. Its actual generating commit must
still be recorded rather than relabelled as the latest repository HEAD.

Four regression methods cover colliding source questions, exact UTF-8 namespaces,
exclusion of task IDs and invalid/unadmitted scopes. The full locked regression
and actual source-writing workflow remain required. Model weights, sources,
reader capacity, production trust, independent human review and real future
observation requirements are not changed. Original source storage and unmeasured
lifecycle costs must remain visible in reports.
