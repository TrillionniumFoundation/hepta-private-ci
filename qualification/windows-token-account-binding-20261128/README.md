# Actual setup account and current readiness

The full consumer run on 8c failed at exact mutex ACL validation after successful setup; CLI and exec-server passed. The corrected original readiness target on 791d then passed all 31 setup, six cross-process/readiness, and one original missing-artifact control without retries. Both full raw logs and artifact ZIPs are preserved.

Full and refresh setup now obtain the qualified account name from the real process token SID, with a complete LookupAccountSidW query and an independent account-to-SID readback. An empty or unrelated USERNAME cannot select Administrators or another ACL owner. Explicit ProvisionOnly still retains its named target; the same resolved SID crosses helper launch and the parent current-readiness transaction. The exact original protected mutex ACL checks, physical FILE_ID key, marker invalidation, CREATE_NEW, and original readiness predicate remain unchanged.

Two new controls cover three separate processes with absent/misleading USERNAME and the distinct explicit-target completion authority. The six original readiness methods are byte-preserved. New candidate execution is pending; old PASS results do not qualify this source.

API references: https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-lookupaccountsidw and https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-lookupaccountnamew
