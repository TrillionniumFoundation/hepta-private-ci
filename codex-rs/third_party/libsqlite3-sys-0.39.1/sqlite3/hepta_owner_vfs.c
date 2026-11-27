/*
** Opt-in creation ownership for private SQLite files on Windows.
** Included inside the WinVFS implementation, after winVfsAppData. This is not a
** process token/default-DACL change or an override of SQLite's global syscalls.
** The stock VFS has no owner policy. Registered policies are immutable and live
** for the process lifetime: SQLite files and shared-memory nodes retain them.
*/
#include <aclapi.h>

#define HEPTA_OWNER_VFS_LIMIT 64
#define HEPTA_OWNER_ACL_BYTES \
  (sizeof(ACL) + sizeof(ACCESS_ALLOWED_ACE) + SECURITY_MAX_SID_SIZE)

struct HeptaWinOwner {
  sqlite3_vfs vfs;
  winVfsAppData app;
  HeptaWinOwner *pNext;
  char zName[32];
  DWORD sid[SECURITY_MAX_SID_SIZE/sizeof(DWORD)];
  DWORD acl[(HEPTA_OWNER_ACL_BYTES+sizeof(DWORD)-1)/sizeof(DWORD)];
  SECURITY_DESCRIPTOR descriptor;
  SECURITY_ATTRIBUTES attributes;
};

static SRWLOCK heptaOwnerLock = SRWLOCK_INIT;
static HeptaWinOwner *heptaOwners = 0;
static unsigned int heptaOwnerCount = 0;
static winVfsAppData winAppData;
static int winOpen(sqlite3_vfs*, const char*, sqlite3_file*, int, int*);

static HeptaWinOwner *heptaWinOwner(sqlite3_vfs *pVfs){
  winVfsAppData *pApp = (winVfsAppData*)pVfs->pAppData;
  return pApp ? pApp->pOwner : 0;
}

static SECURITY_ATTRIBUTES *heptaWinOwnerAttributes(HeptaWinOwner *pOwner){
  return pOwner ? &pOwner->attributes : 0;
}

/* Validate before SQLite can read, write, lock or map this exact handle.
** Accept the same two file ACL shapes as PrivateSqliteDirectory: one explicit
** protected owner ACE, or one inherited unprotected owner ACE. Neither a group
** owner, a NULL ACL, extra ACEs, reparse files nor multiple links qualify. This
** does not confer ancestor/path confinement; the storage owner retains that
** separate responsibility.
*/
static int heptaWinOwnerValidate(HeptaWinOwner *pOwner, HANDLE h){
  BY_HANDLE_FILE_INFORMATION info;
  PSECURITY_DESCRIPTOR pDescriptor = 0;
  PSID pOwnerSid = 0;
  PACL pAcl = 0;
  PACE_HEADER pHeader = 0;
  ACCESS_ALLOWED_ACE *pAce;
  SECURITY_DESCRIPTOR_CONTROL control;
  DWORD revision, sidBytes;
  BYTE *pSid;
  int valid = 0;
  if( !pOwner ) return 1;
  if( GetFileType(h)!=FILE_TYPE_DISK
   || !GetFileInformationByHandle(h, &info)
   || (info.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY|FILE_ATTRIBUTE_REPARSE_POINT))
   || info.nNumberOfLinks!=1
  ) goto invalid;
  if( GetSecurityInfo(h, SE_FILE_OBJECT,
       OWNER_SECURITY_INFORMATION|DACL_SECURITY_INFORMATION,
       &pOwnerSid, 0, &pAcl, 0, &pDescriptor)!=ERROR_SUCCESS
  ) goto invalid;
  if( !pDescriptor || !pOwnerSid || !pAcl || !IsValidSid(pOwnerSid)
   || !EqualSid(pOwnerSid, pOwner->sid) || !IsValidAcl(pAcl)
   || pAcl->AceCount!=1
   || !GetSecurityDescriptorControl(pDescriptor, &control, &revision)
   || !GetAce(pAcl, 0, (void**)&pHeader)
   || !pHeader || pHeader->AceType!=ACCESS_ALLOWED_ACE_TYPE
   || pHeader->AceSize<FIELD_OFFSET(ACCESS_ALLOWED_ACE, SidStart)+8
  ) goto invalid;
  if( !(((control & SE_DACL_PROTECTED) && pHeader->AceFlags==0)
     || (!(control & SE_DACL_PROTECTED) && pHeader->AceFlags==INHERITED_ACE))
  ) goto invalid;
  pAce = (ACCESS_ALLOWED_ACE*)pHeader;
  pSid = (BYTE*)&pAce->SidStart;
  sidBytes = 8 + 4*(DWORD)pSid[1];
  if( FIELD_OFFSET(ACCESS_ALLOWED_ACE, SidStart)+sidBytes>pHeader->AceSize
   || !IsValidSid(pSid) || !EqualSid(pSid, pOwner->sid)
   || pAce->Mask!=FILE_ALL_ACCESS
  ) goto invalid;
  valid = 1;
 invalid:
  if( pDescriptor ) LocalFree(pDescriptor);
  if( !valid ) SetLastError(ERROR_ACCESS_DENIED);
  return valid;
}

/* xDelete may run without xOpen. Validate the deletion handle before setting
** disposition, and keep it bound through the operation. No ACL is repaired. */
static BOOL heptaWinOwnerDelete(HeptaWinOwner *pOwner, LPCWSTR zFilename){
  FILE_DISPOSITION_INFO disposition = { TRUE };
  HANDLE h;
  DWORD error;
  BOOL result;
  h = CreateFileW(zFilename, DELETE|READ_CONTROL|FILE_READ_ATTRIBUTES,
                 FILE_SHARE_READ|FILE_SHARE_WRITE, 0, OPEN_EXISTING,
                 FILE_FLAG_OPEN_REPARSE_POINT, 0);
  if( h==INVALID_HANDLE_VALUE ) return FALSE;
  result = heptaWinOwnerValidate(pOwner, h)
        && SetFileInformationByHandle(h, FileDispositionInfo,
                                      &disposition, sizeof(disposition));
  error = GetLastError();
  if( !CloseHandle(h) ){
    result = FALSE;
    error = GetLastError();
  }
  if( !result ) SetLastError(error);
  return result;
}

/* Return the non-default VFS name bound to the calling thread's effective
** TokenUser. No callback or borrowed Rust allocation crosses the API. A maximum
** of 64 distinct owners is retained; repeat calls for one SID reuse its VFS.
** Failures leave *pzName NULL, close all temporary handles, and free unregistered
** contexts. The caller must propagate failure, never select the default VFS.
*/
SQLITE_API int sqlite3_hepta_win32_owner_vfs(const char **pzName){
  HANDLE token = 0;
  TOKEN_USER *pUser = 0;
  HeptaWinOwner *pNew = 0, *pOwner;
  sqlite3_vfs *pBase;
  DWORD bytes = 0, sidBytes;
  int rc;
  if( !pzName ) return SQLITE_MISUSE;
  *pzName = 0;
  rc = sqlite3_initialize();
  if( rc!=SQLITE_OK ) return rc;
  pBase = sqlite3_vfs_find("win32-longpath");
  if( !pBase || pBase->xOpen!=winOpen || pBase->pAppData!=&winAppData
   || pBase->szOsFile!=sizeof(winFile)
  ) return SQLITE_NOTFOUND;
  if( !OpenThreadToken(GetCurrentThread(), TOKEN_QUERY, TRUE, &token) ){
    if( GetLastError()!=ERROR_NO_TOKEN
     || !OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)
    ) return SQLITE_PERM;
  }
  if( GetTokenInformation(token, TokenUser, 0, 0, &bytes)
   || GetLastError()!=ERROR_INSUFFICIENT_BUFFER
   || bytes<sizeof(TOKEN_USER) || bytes>65536
  ){
    CloseHandle(token);
    return SQLITE_PERM;
  }
  pUser = (TOKEN_USER*)sqlite3_malloc64(bytes);
  if( !pUser ){
    CloseHandle(token);
    return SQLITE_NOMEM;
  }
  if( !GetTokenInformation(token, TokenUser, pUser, bytes, &bytes)
   || !pUser->User.Sid || !IsValidSid(pUser->User.Sid)
  ){
    CloseHandle(token);
    sqlite3_free(pUser);
    return SQLITE_PERM;
  }
  CloseHandle(token);
  sidBytes = GetLengthSid(pUser->User.Sid);
  if( sidBytes>SECURITY_MAX_SID_SIZE ){
    sqlite3_free(pUser);
    return SQLITE_PERM;
  }

  AcquireSRWLockExclusive(&heptaOwnerLock);
  for(pOwner=heptaOwners; pOwner; pOwner=pOwner->pNext){
    if( EqualSid(pOwner->sid, pUser->User.Sid) ){
      if( sqlite3_vfs_find(pOwner->zName)==&pOwner->vfs ){
        rc = SQLITE_OK;
      }else if( sqlite3_vfs_find(pOwner->zName)==0 ){
        /* sqlite3_shutdown followed by initialize may reset the VFS list. */
        rc = sqlite3_vfs_register(&pOwner->vfs, 0);
      }else{
        rc = SQLITE_MISUSE;
      }
      if( rc==SQLITE_OK ) *pzName = pOwner->zName;
      goto done;
    }
  }
  if( heptaOwnerCount>=HEPTA_OWNER_VFS_LIMIT ){
    rc = SQLITE_FULL;
    goto done;
  }
  /* The process heap outlives sqlite3_shutdown and custom SQLite allocators. */
  pNew = (HeptaWinOwner*)HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, sizeof(*pNew));
  if( !pNew ){
    rc = SQLITE_NOMEM;
    goto done;
  }
  if( !CopySid(sizeof(pNew->sid), pNew->sid, pUser->User.Sid)
   || !InitializeAcl((PACL)pNew->acl, sizeof(pNew->acl), ACL_REVISION)
   || !AddAccessAllowedAce((PACL)pNew->acl, ACL_REVISION, FILE_ALL_ACCESS, pNew->sid)
   || !InitializeSecurityDescriptor(&pNew->descriptor, SECURITY_DESCRIPTOR_REVISION)
   || !SetSecurityDescriptorOwner(&pNew->descriptor, pNew->sid, FALSE)
   || !SetSecurityDescriptorDacl(&pNew->descriptor, TRUE, (PACL)pNew->acl, FALSE)
   || !SetSecurityDescriptorControl(&pNew->descriptor, SE_DACL_PROTECTED, SE_DACL_PROTECTED)
  ){
    rc = SQLITE_PERM;
    goto done;
  }
  pNew->attributes.nLength = sizeof(pNew->attributes);
  pNew->attributes.lpSecurityDescriptor = &pNew->descriptor;
  pNew->attributes.bInheritHandle = FALSE;
  sqlite3_snprintf(sizeof(pNew->zName), pNew->zName,
                   "hepta-private-owner-%u", heptaOwnerCount+1);
  if( sqlite3_vfs_find(pNew->zName) ){
    rc = SQLITE_MISUSE;
    goto done;
  }
  pNew->vfs = *pBase;
  pNew->app = *(winVfsAppData*)pBase->pAppData;
  pNew->app.pOwner = pNew;
  pNew->vfs.zName = pNew->zName;
  pNew->vfs.pAppData = &pNew->app;
  pNew->vfs.pNext = 0;
  rc = sqlite3_vfs_register(&pNew->vfs, 0);
  if( rc==SQLITE_OK ){
    pNew->pNext = heptaOwners;
    heptaOwners = pNew;
    heptaOwnerCount++;
    *pzName = pNew->zName;
    pNew = 0;
  }
 done:
  if( pNew ) HeapFree(GetProcessHeap(), 0, pNew);
  ReleaseSRWLockExclusive(&heptaOwnerLock);
  sqlite3_free(pUser);
  return rc;
}
