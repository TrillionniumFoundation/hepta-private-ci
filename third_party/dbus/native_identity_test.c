/* Exercise the linked library and Linux credentials, without a host bus. */
#include <config.h>
#include <dbus/dbus.h>
#include <dbus/dbus-credentials.h>
#include <dbus/dbus-sysdeps.h>
#include <dbus/dbus-sysdeps-unix.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/resource.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

#define CHECK(condition)                                                \
  do {                                                                  \
    if (!(condition)) {                                                 \
      fprintf(stderr, "line %d: %s failed\n", __LINE__, #condition);      \
      return 1;                                                         \
    }                                                                   \
  } while (0)

int main(void) {
  int major, minor, micro;
  dbus_get_version(&major, &minor, &micro);
  CHECK(major == 1 && minor == 16 && micro == 2);
  CHECK(dbus_threads_init_default());

  DBusError error = DBUS_ERROR_INIT;
  DBusMessage *message = dbus_message_new_signal(
      "/org/hepta/Test", "org.hepta.Test", "RoundTrip");
  CHECK(message != NULL);
  const char *text = "hermetic libdbus";
  dbus_int64_t number = -DBUS_INT64_CONSTANT(4294967297);
  CHECK(dbus_message_append_args(message, DBUS_TYPE_STRING, &text,
                                DBUS_TYPE_INT64, &number, DBUS_TYPE_INVALID));
  dbus_message_set_serial(message, 1);
  char *wire = NULL;
  int wire_len = 0;
  CHECK(dbus_message_marshal(message, &wire, &wire_len));
  DBusMessage *decoded = dbus_message_demarshal(wire, wire_len, &error);
  CHECK(decoded != NULL);
  const char *decoded_text = NULL;
  dbus_int64_t decoded_number = 0;
  CHECK(dbus_message_get_args(decoded, &error, DBUS_TYPE_STRING, &decoded_text,
                             DBUS_TYPE_INT64, &decoded_number, DBUS_TYPE_INVALID));
  CHECK(strcmp(text, decoded_text) == 0 && number == decoded_number);
  dbus_message_unref(decoded);
  dbus_message_unref(message);
  dbus_free(wire);

  /* procfs reports fdinfo size zero. The configured library must still read it.
   * A real pidfd must take precedence over a stale numeric PID. */
  int pid_fd = (int)syscall(SYS_pidfd_open, getpid(), 0);
  CHECK(pid_fd >= 0);
  CHECK(_dbus_resolve_pid_fd(pid_fd) == (dbus_pid_t)getpid());
  DBusCredentials *credentials = _dbus_credentials_new();
  CHECK(credentials != NULL);
  CHECK(_dbus_credentials_add_pid(credentials, (dbus_pid_t)getpid() + 1));
  _dbus_credentials_take_pid_fd(credentials, pid_fd);
  CHECK(_dbus_credentials_get_pid(credentials) == (dbus_pid_t)getpid());
  _dbus_credentials_unref(credentials);

  /* An ordinary file descriptor must not resolve as a process descriptor. */
  int ordinary_fd = open("/dev/null", O_RDONLY | O_CLOEXEC);
  CHECK(ordinary_fd >= 0);
  CHECK(_dbus_resolve_pid_fd(ordinary_fd) == DBUS_PID_UNSET);
  close(ordinary_fd);

  int sockets[2];
  CHECK(socketpair(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0, sockets) == 0);
  DBusSocket sender = {sockets[0]};
  DBusSocket receiver = {sockets[1]};
  credentials = _dbus_credentials_new();
  CHECK(credentials != NULL);
  CHECK(_dbus_send_credentials_socket(sender, &error));
  CHECK(_dbus_read_credentials_socket(receiver, credentials, &error));
  CHECK(_dbus_credentials_get_unix_uid(credentials) == (dbus_uid_t)geteuid());
  CHECK(_dbus_credentials_get_pid(credentials) == (dbus_pid_t)getpid());
  _dbus_credentials_unref(credentials);
  close(sockets[0]);
  close(sockets[1]);

  /* The child owns its descriptor table. Lowering RLIMIT must not leave an
   * inherited descriptor above that limit open across a helper exec. */
  pid_t child = fork();
  CHECK(child >= 0);
  if (child == 0) {
    int low = open("/dev/null", O_RDONLY);
    int high = fcntl(low, F_DUPFD, 256);
    struct rlimit limit;
    if (low < 0 || high < 256 || getrlimit(RLIMIT_NOFILE, &limit) != 0)
      _exit(1);
    limit.rlim_cur = 64;
    if (setrlimit(RLIMIT_NOFILE, &limit) != 0)
      _exit(1);
    _dbus_fd_set_all_close_on_exec();
    int flags = fcntl(high, F_GETFD);
    if (flags < 0 || (flags & FD_CLOEXEC) == 0)
      _exit(1);
    _dbus_close_all();
    if (fcntl(high, F_GETFD) != -1 || errno != EBADF)
      _exit(1);
    _exit(0);
  }
  int status;
  CHECK(waitpid(child, &status, 0) == child);
  CHECK(WIFEXITED(status) && WEXITSTATUS(status) == 0);
  dbus_error_free(&error);
  dbus_shutdown();
  puts("PASS: D-Bus 1.16.2, wire ABI, pidfd identity, non-pidfd rejection, peer UID/PID, high-fd closure");
  return 0;
}
