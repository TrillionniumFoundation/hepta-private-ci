# V45 original text-record archive

The original V45 qualification failed. This archive preserves the complete reached text records; it neither reruns nor reclassifies the qualification.

Decode each of the five base64 part files separately and concatenate the decoded bytes in offset order. Verify the 274,164-byte tar.xz SHA256 `1bf6b602bdb711e38bb4799ecf164c5d79f8602a4b64e38040e7ef273ec8ac22` against TRANSFER_MANIFEST.json. The archive has 122 entries: 121 original text records and ARCHIVE_INDEX.json. Three binary copies are excluded from this text archive; they remain in the original complete ZIP and tar.xz archives on the operator host, as recorded in text-pack-v2-index.json and text-pack-v2-receipt.json. This checkpoint does not claim that those binary copies were transferred to Git.

Every part was independently read with the same fixed file version and checked against its chunk SHA256. The concatenated decoded bytes were checked against the archive SHA256. Original record files and the failed result were not changed.
