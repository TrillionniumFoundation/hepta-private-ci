# Complete NoUpdate: first actual failure and next execution

The first isolated complete original parent actually ran and failed with `Permission denied (os error 13)`. The original nextest execution contains one failed case, zero passed cases and no skips. This attempt does not establish whether the original 64-read limit is sufficient. The original owner completed in 831.029797027 seconds; its source inventory, compiler inputs and mount cleanup remained unchanged/complete. Preparation and parent time are nested in that owner interval.

The readback found that this run's newly installed public executable root and product bin directory had mode 0700 under the inherited umask, and its pinned helper had mode 0500. The original dedicated children use UIDs 60001 and 60002. The next run explicitly installs only its own fresh public executable directories as 0755 and the exact immutable copies as 0555, verifies their original manifest digests, then repeats the original helper verification. Actual dropped-UID read/execute checks must reject the previous private copies and accept the new public copies before the parent can start.

The source remains `ab12b8bc1e6761efc16ea8c64e839721739cef5f`, with the original read budget, deadline, native parent, protected data and source modes. The previous attempt is retained. Its directories and files are not changed, global umask is not changed, and no other executor source, target or lock is used. The second protocol and owner are committed prospectively; this publication contains no second-run result.

Native adoption, independent human/controller authentication, cold recovery with a new D, FinalUse, settlement and complete physical costs remain open.
