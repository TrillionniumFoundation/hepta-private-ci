# E6: two original Prepared operation scopes

The original complete NoUpdate case at v13 stops before request 65 because the original historical read lane permits 64. This candidate keeps that bound and the original currentness, identity, deadline, cancellation and physical source fences.

The two production changes share an existing non-escaping Prepared operation across (1) pure Root profile construction and initial/scope comparison and (2) original key reads and descriptor/lifecycle/alias checks. The latter returns owned file handles only after both Result layers and the actual physical postread succeed. All five witness opens and the separate post-witness source validation remain outside that operation. The change does not create a new issuer, cache a successful observation, reconnect the lane, or change the trust owner.

The expected local read-pair reduction is four Task reads. That static reduction is not a proof that the complete NoUpdate, Adopt, C and cold D session fits within 64 reads.

## Source verification

The exact reviewed candidate has 90 relevant source tests and all 892 original protected-file rows passing, with just fmt successful. The complete RESULT.json is copied unchanged alongside this note. The two caller rows now include the actual StageFilesData consumer; the three corresponding ordering rows retain existing original key, lifecycle and witness constraints and add the new operation boundary. Negative source tests reject witness initialization before the physical postread, losing one Result layer, or removing the independent post-witness read.

A new native component regression checks that the valid original profile/scope continues to work, a different empty initial or frozen rule is rejected, and actual source withdrawal invalidates an already created profile and initial. The existing wrong-owner, withdrawal, cancellation, lifecycle, alias and signer tests remain in the native selection.

## Qualification

This is an isolated source and target based on a6f9e8064f83680134af168e0500048b6942ddfd. No original executor source, target, credentials or owner lock is modified. Native execution is governed by NATIVE_PROTOCOL.json and must bind the frozen source and original nextest output. Component tests do not constitute ordinary native owner adoption. Complete native NoUpdate, adoption, fresh C, cold fresh D, FinalUse, controller authentication and settlement remain open.
