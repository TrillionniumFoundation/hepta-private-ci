// Explicit no-effect V2 writer launcher for the frozen original authority CLI/client.
// This is qualification setup, never a production authority/current-cut loader.
#define _GNU_SOURCE
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <grp.h>
#include <linux/capability.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#include <time.h>

static const char *owner = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
static const char *resources = "{\"max_concurrent_turns\":2,\"memory_limit_mib\":4096,\"max_tool_processes\":16,\"turn_queue_capacity\":256}";
static void require(int ok, const char *operation)
{
    if (!ok) { fprintf(stderr, "NATIVE_AUTHORITY_SETUP_FAILED operation=%s errno=%d\n", operation, errno); exit(1); }
}
static void make_path(char *out, size_t capacity, const char *format, ...)
{
    va_list args; va_start(args, format);
    int size = vsnprintf(out, capacity, format, args); va_end(args);
    require(size >= 0 && (size_t)size < capacity, "bounded_path");
}
static void private_json(const char *path, const char *format, ...)
{
    int fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    require(fd >= 0, "create_private_json");
    FILE *stream = fdopen(fd, "w"); require(stream != NULL, "fdopen_json");
    va_list args; va_start(args, format);
    require(vfprintf(stream, format, args) > 0, "write_json"); va_end(args);
    require(fflush(stream) == 0 && fsync(fd) == 0 && fclose(stream) == 0, "durable_json");
}
static int wait_exit_code(pid_t pid)
{
    int status;
    do { errno = 0; } while (waitpid(pid, &status, 0) < 0 && errno == EINTR);
    return errno == 0 && WIFEXITED(status) ? WEXITSTATUS(status) : -1;
}
static size_t read_text(const char *path, char *out, size_t capacity)
{
    int fd = open(path, O_RDONLY | O_CLOEXEC); require(fd >= 0, "open_text");
    size_t total = 0;
    for (;;) {
        ssize_t count = read(fd, out + total, capacity - total - 1);
        if (count < 0 && errno == EINTR) continue;
        require(count >= 0, "read_text");
        if (count == 0) break;
        total += (size_t)count; require(total < capacity - 1, "bounded_text");
    }
    close(fd); out[total] = 0; return total;
}
static unsigned long long start_ticks(pid_t pid)
{
    char path[128], text[8192]; make_path(path, sizeof path, "/proc/%ld/stat", (long)pid);
    read_text(path, text, sizeof text); char *cursor = strrchr(text, ')');
    require(cursor && cursor[1] == ' ', "stat_format"); cursor += 2;
    for (unsigned index = 0; index < 19; index++) {
        cursor = strchr(cursor, ' '); require(cursor != NULL, "stat_fields"); cursor++;
    }
    char *end; unsigned long long ticks = strtoull(cursor, &end, 10);
    require(ticks && end != cursor && *end == ' ', "stat_ticks"); return ticks;
}
static void drop_identity(void)
{
    require(setgroups(0, NULL) == 0, "clear_groups");
    require(prctl(PR_CAP_AMBIENT, PR_CAP_AMBIENT_CLEAR_ALL, 0, 0, 0) == 0, "clear_ambient");
    for (int cap = 0; cap <= CAP_LAST_CAP; cap++)
        require(prctl(PR_CAPBSET_DROP, cap, 0, 0, 0) == 0, "clear_bounding");
    require(setresgid(60001, 60001, 60001) == 0 && setresuid(60001, 60001, 60001) == 0, "dedicated_identity");
    struct __user_cap_header_struct header = {.version = _LINUX_CAPABILITY_VERSION_3, .pid = 0};
    struct __user_cap_data_struct data[2] = {{0}, {0}};
    require(syscall(SYS_capset, &header, data) == 0, "clear_capsets");
    require(prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) == 0, "no_new_privileges");
}

int main(int argc, char **argv)
{
    // root, actual mountpoint, actual bind source, frozen server, frozen client,
    // public Objective scope array generated from the recorded original codec.
    require(argc == 7 && geteuid() == 0, "explicit_root_arguments");
    for (int i = 1; i <= 5; i++) {
        require(argv[i][0] == '/', "absolute_input");
        for (const char *p = argv[i]; *p; p++)
            require(isalnum((unsigned char)*p) || strchr("/._-", *p), "safe_fixture_path");
    }
    umask(0077);
    require(mkdir(argv[1], 0700) == 0, "fresh_exclusive_fixture");
    char state[512], workspace[512], fleet[512], bootstrap[512], initialized[512], config[512], registration[512];
    make_path(state, sizeof state, "%s/authority", argv[1]);
    make_path(workspace, sizeof workspace, "%s/workspace", argv[1]);
    make_path(fleet, sizeof fleet, "%s/fleet", argv[1]);
    make_path(bootstrap, sizeof bootstrap, "%s/bootstrap.json", argv[1]);
    make_path(initialized, sizeof initialized, "%s/initialized.json", argv[1]);
    make_path(config, sizeof config, "%s/service.json", argv[1]);
    make_path(registration, sizeof registration, "%s/registered-spawn.json", argv[1]);
    require(mkdir(workspace, 0700) == 0 && mkdir(fleet, 0700) == 0, "identity_directories");
    struct stat actual, source;
    require(stat(argv[2], &actual) == 0 && stat(argv[3], &source) == 0 && actual.st_dev == source.st_dev && actual.st_ino == source.st_ino, "actual_bind_identity");
    char bind[2048];
    make_path(bind, sizeof bind, "{\"mountpoint\":\"%s\",\"source_path\":\"%s\",\"device\":%llu,\"inode\":%llu}", argv[2], argv[3], (unsigned long long)actual.st_dev, (unsigned long long)actual.st_ino);
    const char *two = "[2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2]";
    const char *three = "[3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3]";
    private_json(bootstrap, "{\"schema_version\":1,\"required_bind\":%s,\"signer_id\":\"root-service-qualification\",\"policies\":[{\"subject_id\":\"%s\",\"destination_id\":\"qualification.no-effect\",\"scope_sha256\":%s,\"lifetime_ms\":30000},{\"subject_id\":\"%s\",\"destination_id\":\"hepta.authbus.objective\",\"scope_sha256\":%s,\"lifetime_ms\":300000}],\"lease_id\":\"root-service-qualification\",\"lease_binding\":{\"principal_id\":\"%s\",\"operation_class\":\"runtime.agentd.production_operation\",\"destination_id\":\"qualification.no-effect\",\"scope_sha256\":%s,\"payload_sha256\":%s},\"lease_lifetime_ms\":60000}", bind, owner, two, owner, argv[6], owner, two, three);
    pid_t initialize = fork(); require(initialize >= 0, "fork_initialize");
    if (!initialize) {
        int fd = open(initialized, O_WRONLY | O_CREAT | O_EXCL, 0600);
        require(fd >= 0 && dup2(fd, STDOUT_FILENO) == STDOUT_FILENO, "capture_public_initialized"); close(fd);
        execl(argv[4], argv[4], "initialize", "--state", state, "--bootstrap", bootstrap, (char *)NULL); _exit(127);
    }
    require(wait_exit_code(initialize) == 0, "original_initialize");
    char public[8192]; read_text(initialized, public, sizeof public);
    char *key = strstr(public, "\"verifying_key\":["); require(key != NULL, "initialized_public_key");
    key = strchr(key, '['); char *key_end = strchr(key, ']'); require(key_end && key_end - key < 160, "bounded_public_key"); key_end[1] = 0;
    char runtime[128]; make_path(runtime, sizeof runtime, "/run/hepta-native-q-%ld", (long)getpid());
    require(mkdir(runtime, 0700) == 0 && chown(runtime, 0, 60001) == 0 && chmod(runtime, 02710) == 0, "private_socket_directory");
    char identity[2048]; make_path(identity, sizeof identity, "{\"agent_id\":\"%s\",\"spawn_generation\":1,\"fleet_root\":\"%s\",\"workspace\":\"%s\",\"resources\":%s}", owner, fleet, workspace, resources);
    int ready[2], release[2]; require(pipe2(ready, O_CLOEXEC) == 0 && pipe2(release, O_CLOEXEC) == 0, "private_startup_channels");
    pid_t client = fork(); require(client >= 0, "fork_dedicated_client");
    if (!client) {
        close(ready[0]); close(release[1]); drop_identity();
        require(write(ready[1], "1", 1) == 1, "announce_dropped_identity"); close(ready[1]);
        char pid[32]; ssize_t size = read(release[0], pid, sizeof pid - 1); require(size > 0, "receive_root_service_pid"); pid[size] = 0; close(release[0]);
        require(setenv("HEPTA_SERVICE_WRITER_PROOF", "1", 1) == 0 && setenv("HEPTA_SERVICE_PID", pid, 1) == 0 && setenv("HEPTA_SERVICE_STATE", state, 1) == 0 && setenv("HEPTA_SERVICE_RUNTIME", runtime, 1) == 0 && setenv("HEPTA_SERVICE_IDENTITY", identity, 1) == 0 && setenv("HEPTA_SERVICE_PUBLIC_KEY", key, 1) == 0, "public_qualification_environment");
        execl(argv[5], argv[5], (char *)NULL); _exit(127);
    }
    close(ready[1]); close(release[0]); char ready_byte;
    require(read(ready[0], &ready_byte, 1) == 1 && ready_byte == '1', "actual_dedicated_child_ready"); close(ready[0]);
    int pidfd = (int)syscall(SYS_pidfd_open, client, 0); require(pidfd >= 0, "preheld_actual_client_pidfd");
    char boot[128]; read_text("/proc/sys/kernel/random/boot_id", boot, sizeof boot); boot[strcspn(boot, "\r\n")] = 0;
    private_json(registration, "{\"schema_version\":1,\"peer_pid\":%ld,\"boot_id\":\"%s\",\"process_start_ticks\":%llu,\"registered_identity\":%s,\"checkpoint_owner_agent_id\":\"%s\",\"publisher_epoch\":1}", (long)client, boot, start_ticks(client), identity, owner);
    struct timespec wall;
    require(clock_gettime(CLOCK_REALTIME, &wall) == 0 && wall.tv_sec > 0, "actual_writer_wall_clock");
    unsigned long long now_ms = (unsigned long long)wall.tv_sec * 1000 + wall.tv_nsec / 1000000;
    const char *six = "[6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6]";
    const char *seven = "[7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7]";
    char writer[2048];
    make_path(writer, sizeof writer, "{\"registered_agent_id\":\"%s\",\"spawn_generation\":1,\"owner_epoch\":1,\"local_lease_id\":\"original-local-writer-qualification\",\"local_lease_generation\":1,\"authority_lease\":{\"schema_version\":1,\"lease_id\":\"root-writer-qualification\",\"revision\":1,\"authority_epoch\":1,\"binding\":{\"principal_id\":\"%s\",\"operation_class\":\"runtime.agentd.production_writer\",\"destination_id\":\"qualification.no-effect.cognitive-owner\",\"scope_sha256\":%s,\"payload_sha256\":%s},\"issued_at_unix_ms\":%llu,\"expires_at_unix_ms\":%llu}}", owner, owner, six, seven, now_ms, now_ms + 60000);
    private_json(config, "{\"schema_version\":1,\"state_dir\":\"%s\",\"required_bind\":%s,\"signer_id\":\"root-service-qualification\",\"expected_verifying_key\":%s,\"lease_id\":\"root-service-qualification\",\"lease_revision\":1,\"writer\":%s,\"sockets\":{\"observation\":\"%s/observation.sock\",\"issuer\":\"%s/issuer.sock\",\"checkpoint\":\"%s/checkpoint.sock\"},\"peer_uid\":60001,\"peer_gid\":60001,\"timeout_ms\":10000,\"lifetime_ms\":20000}", state, bind, key, writer, runtime, runtime, runtime);
    char writer_proof[512];
    make_path(writer_proof, sizeof writer_proof, "%s/public-writer-proof.json", argv[1]);
    pid_t register_writer = fork(); require(register_writer >= 0, "fork_register_writer");
    if (!register_writer) {
        close(release[1]); close(pidfd);
        int fd = open(writer_proof, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
        require(fd >= 0 && dup2(fd, STDOUT_FILENO) == STDOUT_FILENO, "capture_public_writer_proof"); close(fd);
        execl(argv[4], argv[4], "register-writer", "--config", config, (char *)NULL); _exit(127);
    }
    require(wait_exit_code(register_writer) == 0, "original_register_writer");
    pid_t server = fork(); require(server >= 0, "fork_root_service");
    if (!server) {
        close(release[1]); require(dup2(pidfd, STDIN_FILENO) == STDIN_FILENO, "original_owner_pidfd_stdin"); close(pidfd);
        execl(argv[4], argv[4], "serve-session", "--config", config, "--registration", registration, "--owner-pidfd-stdin", (char *)NULL); _exit(127);
    }
    close(pidfd); char server_pid[32]; make_path(server_pid, sizeof server_pid, "%ld", (long)server);
    require(write(release[1], server_pid, strlen(server_pid)) == (ssize_t)strlen(server_pid), "release_exact_pid_client"); close(release[1]);
    int client_code = wait_exit_code(client), server_code = wait_exit_code(server);
    int client_ok = client_code == 0, server_ok = server_code == 1;
    printf("NATIVE_AUTHORITY_EXITS client=%d server=%d checkpoint_ack_expected=0\n", client_code, server_code);
    printf("NATIVE_AUTHORITY_ORIGINAL_CLIENT pass=%d\n", client_ok);
    printf("NATIVE_AUTHORITY_SERVER_EXPECTED_NO_ACK_EXIT pass=%d\n", server_ok);
    printf("NATIVE_AUTHORITY_COMPLETE pass=%d production_ready=0 g2_complete=0\n", client_ok && server_ok);
    return client_ok && server_ok ? 0 : 1;
}
