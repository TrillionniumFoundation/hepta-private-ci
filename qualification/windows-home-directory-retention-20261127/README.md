# Retain the setup directory through the marker transaction

The original 2c8 Windows setup-bin run executed all 33 tests. Thirty passed,
the two existing worker cases remained intentionally ignored at collection,
and both explicitly invoked worker processes actually passed one test with
zero ignores. The retained-directory rename assertion failed.

MS-FSA 2.1.5.1.2.2 counts an existing open for sharing only when its granted
access contains a data/execute/write/append/delete bit. FILE_READ_ATTRIBUTES
alone did not retain namespace stability. The production open now requests
FILE_LIST_DIRECTORY | FILE_READ_ATTRIBUTES in the same original NtCreateFile,
with FILE_OPEN and unchanged no-reparse flags and no delete sharing.

The original assertion, access checks, CREATE_NEW marker, private DACL,
file-identity mutex, same-home and independent-home controls are unchanged.
The next actual Windows original target remains pending in this commit.

Official algorithm:
https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fsa/8c0e3f4f-0729-49f4-a14d-7f7add593819
