/* Owned-fixture diagnostic only. No CRT or production sandbox admission. */
#define WIN32_LEAN_AND_MEAN
#define _WIN32_WINNT 0x0A00
#include <windows.h>
#include <aclapi.h>
#include <sddl.h>

static HANDLE output;
static union {
    ULONGLONG alignment;
    BYTE bytes[8192];
} token_buffer;

static void text(const char *value) {
    DWORD length = 0, written = 0;
    while (value[length] != '\0') ++length;
    if (!WriteFile(output, value, length, &written, NULL) || written != length)
        ExitProcess(71);
}

static void number(DWORD value) {
    char digits[11];
    DWORD count = 0, written = 0;
    do {
        digits[count++] = (char)('0' + value % 10);
        value /= 10;
    } while (value != 0);
    while (count != 0) {
        if (!WriteFile(output, &digits[--count], 1, &written, NULL) || written != 1)
            ExitProcess(71);
    }
}

static void wide_string(LPCWSTR value) {
    static const char hex[] = "0123456789abcdef";
    DWORD count = 0;
    text("\"");
    while (value != NULL && *value != 0 && count++ < 16384) {
        WCHAR code = *value++;
        if (code >= 0x20 && code <= 0x7e && code != L'\\' && code != L'\"') {
            char one[2] = {(char)code, 0};
            text(one);
        } else {
            char escaped[7] = {'\\', 'u', '0', '0', '0', '0', 0};
            escaped[2] = hex[(code >> 12) & 15];
            escaped[3] = hex[(code >> 8) & 15];
            escaped[4] = hex[(code >> 4) & 15];
            escaped[5] = hex[code & 15];
            text(escaped);
        }
    }
    text("\"");
}

static void result(const char *operation, LPCWSTR path, BOOL success, DWORD error) {
    text("{\"kind\":\"operation\",\"operation\":\"");
    text(operation);
    text("\",\"path\":");
    wide_string(path);
    text(",\"success\":");
    text(success ? "true" : "false");
    text(",\"winerror\":");
    number(error);
    text("}\n");
}

static void token_information(HANDLE token, TOKEN_INFORMATION_CLASS kind, const char *name) {
    DWORD size = 0;
    BOOL ok = GetTokenInformation(token, kind, token_buffer.bytes, (DWORD)sizeof(token_buffer.bytes), &size);
    DWORD error = ok ? ERROR_SUCCESS : GetLastError();
    text("{\"kind\":\"token\",\"field\":\"");
    text(name);
    text("\",\"winerror\":");
    number(error);
    text(",\"returned_bytes\":");
    number(size);
    if (ok && size <= sizeof(token_buffer.bytes)) {
        PSID sid = NULL;
        if (kind == TokenIntegrityLevel)
            sid = ((TOKEN_MANDATORY_LABEL *)token_buffer.bytes)->Label.Sid;
        else if (kind == TokenUser)
            sid = ((TOKEN_USER *)token_buffer.bytes)->User.Sid;
        else if (kind == TokenAppContainerSid)
            sid = ((TOKEN_APPCONTAINER_INFORMATION *)token_buffer.bytes)->TokenAppContainer;
        if (sid != NULL) {
            LPWSTR printable = NULL;
            BOOL converted = ConvertSidToStringSidW(sid, &printable);
            DWORD conversion_error = converted ? ERROR_SUCCESS : GetLastError();
            text(",\"sid\":");
            wide_string(printable);
            text(",\"sid_conversion_error\":");
            number(conversion_error);
            if (printable != NULL) LocalFree(printable);
        } else if (size >= sizeof(DWORD)) {
            text(",\"value\":");
            number(*(DWORD *)token_buffer.bytes);
        }
    }
    text("}\n");
}

static void security(LPCWSTR path) {
    PSECURITY_DESCRIPTOR descriptor = NULL;
    LPWSTR printable = NULL;
    DWORD information = OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION | LABEL_SECURITY_INFORMATION;
    DWORD error = GetNamedSecurityInfoW((LPWSTR)path, SE_FILE_OBJECT, information,
                                      NULL, NULL, NULL, NULL, &descriptor);
    DWORD attributes = GetFileAttributesW(path);
    DWORD attribute_error = attributes == INVALID_FILE_ATTRIBUTES ? GetLastError() : ERROR_SUCCESS;
    text("{\"kind\":\"security\",\"path\":");
    wide_string(path);
    text(",\"winerror\":");
    number(error);
    text(",\"file_attributes\":");
    number(attributes);
    text(",\"file_attributes_error\":");
    number(attribute_error);
    if (error == ERROR_SUCCESS) {
        BOOL present = FALSE, defaulted = FALSE;
        PACL sacl = NULL;
        BOOL observed = GetSecurityDescriptorSacl(descriptor, &present, &sacl, &defaulted);
        DWORD sacl_error = observed ? ERROR_SUCCESS : GetLastError();
        text(",\"sacl_observed\":");
        text(observed ? "true" : "false");
        text(",\"sacl_error\":");
        number(sacl_error);
        text(",\"sacl_present\":");
        text(present ? "true" : "false");
        text(",\"sacl_ace_count\":");
        number(sacl == NULL ? 0 : sacl->AceCount);
        BOOL converted = ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor, SDDL_REVISION_1, information, &printable, NULL);
        DWORD conversion_error = converted ? ERROR_SUCCESS : GetLastError();
        text(",\"sddl\":");
        wide_string(printable);
        text(",\"sddl_conversion_error\":");
        number(conversion_error);
    }
    text("}\n");
    if (printable != NULL) LocalFree(printable);
    if (descriptor != NULL) LocalFree(descriptor);
}

static void delete_file(LPCWSTR path) {
    HANDLE file = CreateFileW(path, DELETE, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                              NULL, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, NULL);
    DWORD error = file == INVALID_HANDLE_VALUE ? GetLastError() : ERROR_SUCCESS;
    result("CreateFileW_DELETE", path, file != INVALID_HANDLE_VALUE, error);
    if (file != INVALID_HANDLE_VALUE) CloseHandle(file);
    BOOL deleted = DeleteFileW(path);
    error = deleted ? ERROR_SUCCESS : GetLastError();
    result("DeleteFileW", path, deleted, error);
}

static void enumerate_path(LPCWSTR path) {
    WIN32_FIND_DATAW found;
    HANDLE search = FindFirstFileW(path, &found);
    DWORD error = search == INVALID_HANDLE_VALUE ? GetLastError() : ERROR_SUCCESS;
    result("FindFirstFileW", path, search != INVALID_HANDLE_VALUE, error);
    if (search != INVALID_HANDLE_VALUE) {
        BOOL closed = FindClose(search);
        error = closed ? ERROR_SUCCESS : GetLastError();
        result("FindClose", path, closed, error);
    }
}

static void read_directory(LPCWSTR path) {
    HANDLE directory = CreateFileW(
        path, FILE_LIST_DIRECTORY, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        NULL, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, NULL);
    DWORD error = directory == INVALID_HANDLE_VALUE ? GetLastError() : ERROR_SUCCESS;
    result("CreateFileW_FILE_LIST_DIRECTORY", path, directory != INVALID_HANDLE_VALUE, error);
    if (directory != INVALID_HANDLE_VALUE) CloseHandle(directory);
}

void WINAPI entry(void) {
    static const WCHAR *paths[] = {
        L".", L"child-delete.txt", L"child-delete-dir", L"child-probe.cmd", L".git",
        L"trace-inherited-medium.txt", L"trace-inherited-low.txt",
        L"trace-explicit-medium.txt", L"trace-explicit-low.txt",
        L"..\\outside\\child-null-ME.txt", L"..\\outside\\child-null-LW.txt"
    };
    static const WCHAR *enumerations[] = {L"child-delete.txt", L"child-probe.cmd", L"*"};
    static WCHAR absolute[1024];
    HANDLE token = NULL;
    output = GetStdHandle(STD_OUTPUT_HANDLE);
    text("{\"kind\":\"start\",\"diagnostic_only\":true,\"production_qualification\":false}\n");
    BOOL opened = OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token);
    DWORD error = opened ? ERROR_SUCCESS : GetLastError();
    result("OpenProcessToken", L"self", opened, error);
    if (opened) {
        token_information(token, TokenIsAppContainer, "is_appcontainer");
        token_information(token, TokenIntegrityLevel, "integrity");
        token_information(token, TokenMandatoryPolicy, "mandatory_policy");
        token_information(token, TokenUser, "user");
        token_information(token, TokenAppContainerSid, "package");
        CloseHandle(token);
    }
    for (DWORD index = 0; index < (DWORD)(sizeof(paths) / sizeof(paths[0])); ++index)
        security(paths[index]);
    // Observe cmd's possible lookup prerequisites before the existing targets
    // are deleted. These calls neither grant rights nor qualify cmd behavior.
    for (DWORD index = 0; index < (DWORD)(sizeof(enumerations) / sizeof(enumerations[0])); ++index) {
        LPCWSTR path = enumerations[index];
        enumerate_path(path);
        DWORD capacity = (DWORD)(sizeof(absolute) / sizeof(absolute[0]));
        DWORD length = GetFullPathNameW(path, capacity, absolute, NULL);
        BOOL bounded = length != 0 && length < capacity;
        error = length == 0 ? GetLastError() : (bounded ? ERROR_SUCCESS : ERROR_INSUFFICIENT_BUFFER);
        result("GetFullPathNameW", path, bounded, error);
        if (bounded) {
            enumerate_path(absolute);
            if (index == 0) {
                HANDLE file = CreateFileW(
                    absolute, DELETE, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                    NULL, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, NULL);
                error = file == INVALID_HANDLE_VALUE ? GetLastError() : ERROR_SUCCESS;
                result("CreateFileW_DELETE", absolute, file != INVALID_HANDLE_VALUE, error);
                if (file != INVALID_HANDLE_VALUE) CloseHandle(file);
            }
        }
    }
    read_directory(L".");
    DWORD capacity = (DWORD)(sizeof(absolute) / sizeof(absolute[0]));
    DWORD length = GetFullPathNameW(L".", capacity, absolute, NULL);
    BOOL bounded = length != 0 && length < capacity;
    error = length == 0 ? GetLastError() : (bounded ? ERROR_SUCCESS : ERROR_INSUFFICIENT_BUFFER);
    result("GetFullPathNameW", L".", bounded, error);
    if (bounded) read_directory(absolute);
    delete_file(L"child-delete.txt");
    delete_file(L"trace-inherited-medium.txt");
    delete_file(L"trace-inherited-low.txt");
    delete_file(L"trace-explicit-medium.txt");
    delete_file(L"trace-explicit-low.txt");
    delete_file(L"..\\outside\\child-null-ME.txt");
    delete_file(L"..\\outside\\child-null-LW.txt");
    BOOL removed = RemoveDirectoryW(L"child-delete-dir");
    error = removed ? ERROR_SUCCESS : GetLastError();
    result("RemoveDirectoryW", L"child-delete-dir", removed, error);
    removed = RemoveDirectoryW(L".git");
    error = removed ? ERROR_SUCCESS : GetLastError();
    result("RemoveDirectoryW", L".git", removed, error);
    text("{\"kind\":\"complete\",\"diagnostic_only\":true}\n");
    ExitProcess(0);
}
