// Diagnostic only: temporary token handles and in-memory security descriptors.
// This does not impersonate, launch a sandbox, or change an object's security.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <sddl.h>

#include <array>
#include <cstdio>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

struct ApiFailure : std::runtime_error {
    DWORD code;
    ApiFailure(const char* stage, DWORD value) : std::runtime_error(stage), code(value) {}
};

struct Handle {
    HANDLE value = nullptr;
    explicit Handle(HANDLE handle = nullptr) : value(handle) {}
    ~Handle() { if (value != nullptr) CloseHandle(value); }
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
    Handle(Handle&& other) noexcept : value(std::exchange(other.value, nullptr)) {}
};

struct LocalMemory {
    HLOCAL value = nullptr;
    ~LocalMemory() { if (value != nullptr) LocalFree(value); }
};

struct Sid {
    std::vector<ULONG_PTR> storage;
    PSID get() const { return const_cast<ULONG_PTR*>(storage.data()); }
    static Sid copy(PSID source) {
        if (!IsValidSid(source)) throw ApiFailure("invalid_sid", ERROR_INVALID_SID);
        const DWORD bytes = GetLengthSid(source);
        Sid result;
        result.storage.resize((bytes + sizeof(ULONG_PTR) - 1) / sizeof(ULONG_PTR));
        if (!CopySid(bytes, result.get(), source)) {
            const DWORD error = GetLastError();
            throw ApiFailure("copy_sid", error);
        }
        return result;
    }
    static Sid parse(const wchar_t* text) {
        PSID parsed = nullptr;
        if (!ConvertStringSidToSidW(text, &parsed)) {
            const DWORD error = GetLastError();
            throw ApiFailure("parse_sid", error);
        }
        LocalMemory memory{parsed};
        return copy(parsed);
    }
    std::wstring sddl() const {
        LPWSTR text = nullptr;
        if (!ConvertSidToStringSidW(get(), &text)) {
            const DWORD error = GetLastError();
            throw ApiFailure("format_sid_in_memory", error);
        }
        LocalMemory memory{text};
        return text;
    }
};

std::vector<ULONG_PTR> token_info(HANDLE token, TOKEN_INFORMATION_CLASS kind) {
    DWORD bytes = 0;
    const BOOL first = GetTokenInformation(token, kind, nullptr, 0, &bytes);
    const DWORD error = first ? ERROR_SUCCESS : GetLastError();
    if (first || error != ERROR_INSUFFICIENT_BUFFER || bytes == 0 || bytes > 65536) {
        throw ApiFailure("token_info_size", error);
    }
    std::vector<ULONG_PTR> buffer((bytes + sizeof(ULONG_PTR) - 1) / sizeof(ULONG_PTR));
    if (!GetTokenInformation(token, kind, buffer.data(), bytes, &bytes)) {
        const DWORD second_error = GetLastError();
        throw ApiFailure("token_info", second_error);
    }
    return buffer;
}

Handle impersonation_copy(HANDLE token) {
    HANDLE duplicate = nullptr;
    if (!DuplicateTokenEx(token, TOKEN_QUERY, nullptr, SecurityImpersonation,
                          TokenImpersonation, &duplicate)) {
        const DWORD error = GetLastError();
        throw ApiFailure("duplicate_for_accesscheck", error);
    }
    return Handle(duplicate);
}

Handle restricted_copy(HANDLE base, DWORD flags, const std::vector<PSID>& sids) {
    std::vector<SID_AND_ATTRIBUTES> restrictions;
    for (PSID sid : sids) restrictions.push_back({sid, 0});
    HANDLE created = nullptr;
    if (!CreateRestrictedToken(base, flags, 0, nullptr, 0, nullptr,
                               static_cast<DWORD>(restrictions.size()),
                               restrictions.empty() ? nullptr : restrictions.data(), &created)) {
        const DWORD error = GetLastError();
        throw ApiFailure("create_temporary_restricted_token", error);
    }
    Handle primary(created);
    const auto info = token_info(primary.value, TokenRestrictedSids);
    const auto* actual = reinterpret_cast<const TOKEN_GROUPS*>(info.data());
    if (actual->GroupCount != sids.size()) {
        throw ApiFailure("restricting_sid_count", ERROR_INVALID_DATA);
    }
    for (PSID sid : sids) {
        DWORD matches = 0;
        for (DWORD index = 0; index < actual->GroupCount; ++index) {
            if (EqualSid(sid, actual->Groups[index].Sid)) ++matches;
        }
        if (matches != 1) throw ApiFailure("restricting_sid_membership", ERROR_INVALID_DATA);
    }
    return impersonation_copy(primary.value);
}

void require_not_member(HANDLE token, PSID sid) {
    BOOL member = FALSE;
    if (!CheckTokenMembership(token, sid, &member)) {
        const DWORD error = GetLastError();
        throw ApiFailure("negative_identity_membership", error);
    }
    if (member) throw ApiFailure("negative_identity_collision", ERROR_INVALID_DATA);
}

struct Observation { bool allowed; DWORD granted; };

Observation check(HANDLE token, PSECURITY_DESCRIPTOR descriptor, DWORD desired) {
    GENERIC_MAPPING mapping{FILE_GENERIC_READ, FILE_GENERIC_WRITE,
                            FILE_GENERIC_EXECUTE, FILE_ALL_ACCESS};
    std::array<ULONG_PTR, 512> privileges{};
    DWORD bytes = static_cast<DWORD>(sizeof(privileges));
    DWORD granted = 0;
    BOOL allowed = FALSE;
    if (!AccessCheck(descriptor, token, desired, &mapping,
                     reinterpret_cast<PRIVILEGE_SET*>(privileges.data()),
                     &bytes, &granted, &allowed)) {
        const DWORD error = GetLastError();
        throw ApiFailure("accesscheck", error);
    }
    return {allowed != FALSE, granted};
}

std::wstring allow(DWORD rights, const Sid& sid) {
    wchar_t mask[16]{};
    if (swprintf_s(mask, L"0x%08lx", rights) < 0) {
        throw ApiFailure("format_rights", ERROR_INVALID_DATA);
    }
    return L"(A;;" + std::wstring(mask) + L";;;" + sid.sddl() + L")";
}

int main() {
    std::puts("{\"schema\":1,\"kind\":\"scope\",\"identity\":\"current_ci_account\",\"real_dedicated_account\":false,\"host_security_mutation\":false}");
    try {
        HANDLE opened = nullptr;
        if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY | TOKEN_DUPLICATE, &opened)) {
            const DWORD error = GetLastError();
            throw ApiFailure("open_current_token", error);
        }
        Handle base(opened);
        const auto restricted = token_info(base.value, TokenRestrictedSids);
        if (reinterpret_cast<const TOKEN_GROUPS*>(restricted.data())->GroupCount != 0) {
            throw ApiFailure("base_already_restricted", ERROR_INVALID_DATA);
        }
        const auto user_info = token_info(base.value, TokenUser);
        const Sid user = Sid::copy(reinterpret_cast<const TOKEN_USER*>(user_info.data())->User.Sid);
        const auto group_info = token_info(base.value, TokenGroups);
        const auto* groups = reinterpret_cast<const TOKEN_GROUPS*>(group_info.data());
        PSID logon_pointer = nullptr;
        for (DWORD index = 0; index < groups->GroupCount; ++index) {
            if ((groups->Groups[index].Attributes & SE_GROUP_LOGON_ID) == SE_GROUP_LOGON_ID) {
                if (logon_pointer != nullptr) throw ApiFailure("multiple_logon_sids", ERROR_INVALID_DATA);
                logon_pointer = groups->Groups[index].Sid;
            }
        }
        if (logon_pointer == nullptr) throw ApiFailure("missing_logon_sid", ERROR_INVALID_DATA);
        const Sid logon = Sid::copy(logon_pointer);
        const Sid world = Sid::parse(L"S-1-1-0");
        const Sid cap = Sid::parse(L"S-1-5-21-181-282-383-484");
        const Sid unrelated = Sid::parse(L"S-1-5-21-191-292-393-494");
        const Sid other_user = Sid::parse(L"S-1-5-21-201-302-403-504");
        Handle baseline = impersonation_copy(base.value);
        for (const Sid* sid : {&cap, &unrelated, &other_user}) require_not_member(baseline.value, sid->get());

        struct TokenCase { const char* label; Handle token; bool fully_cap_only; bool ordinary_control; };
        std::vector<TokenCase> tokens;
        const DWORD ordinary_flags = DISABLE_MAX_PRIVILEGE | LUA_TOKEN;
        tokens.push_back({"base", std::move(baseline), false, true});
        tokens.push_back({"privileges_disabled", restricted_copy(base.value, ordinary_flags, {}), false, true});
        tokens.push_back({"write_cap_only", restricted_copy(base.value, ordinary_flags | WRITE_RESTRICTED, {cap.get()}), false, false});
        tokens.push_back({"full_cap_only", restricted_copy(base.value, ordinary_flags, {cap.get()}), true, false});
        tokens.push_back({"full_cap_user", restricted_copy(base.value, ordinary_flags, {cap.get(), user.get()}), false, false});
        tokens.push_back({"full_cap_logon", restricted_copy(base.value, ordinary_flags, {cap.get(), logon.get()}), false, false});
        tokens.push_back({"full_cap_world", restricted_copy(base.value, ordinary_flags, {cap.get(), world.get()}), false, false});
        tokens.push_back({"write_cap_identities", restricted_copy(base.value, ordinary_flags | WRITE_RESTRICTED, {cap.get(), user.get(), logon.get(), world.get()}), false, false});
        tokens.push_back({"full_cap_identities", restricted_copy(base.value, ordinary_flags, {cap.get(), user.get(), logon.get(), world.get()}), false, false});

        constexpr DWORD all = FILE_READ_DATA | FILE_WRITE_DATA | DELETE | FILE_DELETE_CHILD;
        constexpr DWORD writes = FILE_WRITE_DATA | DELETE | FILE_DELETE_CHILD;
        struct DescriptorCase { const char* label; std::wstring aces; DWORD capability_rights; bool ordinary_allowed; };
        const std::array<DescriptorCase, 9> descriptors{{
            {"world_ambient", allow(all, world), 0, true},
            {"user_ambient", allow(all, user), 0, true},
            {"logon_ambient", allow(all, logon), 0, true},
            {"other_account_only", allow(all, other_user), 0, false},
            {"world_plus_cap_read", allow(all, world) + allow(FILE_READ_DATA, cap), FILE_READ_DATA, true},
            {"world_plus_cap_write", allow(all, world) + allow(writes, cap), writes, true},
            {"world_plus_cap_all", allow(all, world) + allow(all, cap), all, true},
            {"world_plus_unrelated_cap", allow(all, world) + allow(all, unrelated), 0, true},
            {"other_account_plus_cap", allow(all, other_user) + allow(all, cap), all, false},
        }};
        const std::array<std::pair<const char*, DWORD>, 4> rights{{
            {"read_data", FILE_READ_DATA}, {"write_data", FILE_WRITE_DATA},
            {"delete_object", DELETE}, {"delete_child", FILE_DELETE_CHILD},
        }};
        unsigned observations = 0;
        unsigned control_mismatches = 0;
        for (const auto& descriptor_case : descriptors) {
            const std::wstring sddl = L"O:SYG:SYD:P" + descriptor_case.aces;
            PSECURITY_DESCRIPTOR descriptor = nullptr;
            if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl.c_str(), SDDL_REVISION_1,
                                                                      &descriptor, nullptr)) {
                const DWORD error = GetLastError();
                throw ApiFailure("parse_memory_descriptor", error);
            }
            LocalMemory memory{descriptor};
            for (const auto& token_case : tokens) {
                for (const auto& right : rights) {
                    const auto result = check(token_case.token.value, descriptor, right.second);
                    const bool controlled = token_case.ordinary_control || token_case.fully_cap_only;
                    const bool expected = descriptor_case.ordinary_allowed &&
                        (!token_case.fully_cap_only || (descriptor_case.capability_rights & right.second) != 0);
                    if (controlled && result.allowed != expected) ++control_mismatches;
                    if (result.allowed && (result.granted & right.second) != right.second) ++control_mismatches;
                    std::printf("{\"kind\":\"access\",\"token\":\"%s\",\"descriptor\":\"%s\",\"right\":\"%s\",\"allowed\":%s,\"granted\":%lu,\"controlled\":%s,\"expected\":%s}\n",
                                token_case.label, descriptor_case.label, right.first,
                                result.allowed ? "true" : "false", result.granted,
                                controlled ? "true" : "false",
                                controlled ? (expected ? "true" : "false") : "null");
                    ++observations;
                }
            }
        }
        const bool valid = observations == 324 && control_mismatches == 0;
        std::printf("{\"kind\":\"summary\",\"observations\":%u,\"control_mismatches\":%u,\"valid\":%s,\"backend_qualified\":false}\n",
                    observations, control_mismatches, valid ? "true" : "false");
        return valid ? 0 : 1;
    } catch (const ApiFailure& failure) {
        std::printf("{\"kind\":\"api_failure\",\"stage\":\"%s\",\"win32_error\":%lu,\"valid\":false}\n", failure.what(), failure.code);
        return 2;
    } catch (...) {
        std::puts("{\"kind\":\"unexpected_failure\",\"valid\":false}");
        return 3;
    }
}
