"""Durable majority-vote replica with no implicit empty-database recovery."""

from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3

from authority_contract import (
    ZERO,
    decode,
    digest,
    encode,
    fields,
    integer,
    name,
    validate_state,
)
from replica_fences import ReplicaFences

MAX_HISTORY = 4096


@contextmanager
def transaction(path):
    database = sqlite3.connect(path, timeout=10, isolation_level=None)
    try:
        database.execute("PRAGMA synchronous=FULL")
        database.execute("BEGIN IMMEDIATE")
        yield database
        database.commit()
    except BaseException:
        database.rollback()
        raise
    finally:
        database.close()


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class Replica:
    def __init__(
        self, root, member_id, membership, private_key, *, creation="existing"
    ):
        self.root = Path(root).absolute()
        if self.root.is_symlink() or creation not in ("existing", "genesis"):
            raise ValueError(
                "real replica directory and explicit creation mode required"
            )
        if (
            membership.member_keys.get(member_id)
            != private_key.public_key().public_bytes_raw().hex()
        ):
            raise ValueError("replica private key does not match fixed membership")
        self.root.mkdir(parents=True, exist_ok=True)
        self.database, guard = (
            self.root / "authority.sqlite",
            self.root / "identity.json",
        )
        if self.database.is_symlink() or guard.is_symlink():
            raise ValueError("replica state cannot be symlinked")
        self.member_id, self.membership, self.private_key = (
            member_id,
            membership,
            private_key,
        )
        identity = dict(member_id=member_id, membership_sha256=membership.sha256)
        if guard.exists():
            if decode(guard.read_bytes()) != identity or not self.database.is_file():
                raise ValueError(
                    "replica identity mismatch or database lost; restore required"
                )
        elif self.database.exists() or creation != "genesis":
            raise ValueError(
                "replica identity absent; explicit new deployment required"
            )
        self.fences = ReplicaFences(
            self.root, creation="existing" if guard.exists() else "genesis"
        )
        with transaction(self.database) as database:
            database.execute(
                "CREATE TABLE IF NOT EXISTS states(scope TEXT, sequence INTEGER, pin TEXT, certificate BLOB, PRIMARY KEY(scope,sequence))"
            )
            database.execute(
                "CREATE TABLE IF NOT EXISTS votes(scope TEXT, sequence INTEGER, pin TEXT, proposal BLOB, vote BLOB, PRIMARY KEY(scope,sequence))"
            )
            database.execute("CREATE TABLE IF NOT EXISTS identity(value BLOB NOT NULL)")
            row = database.execute("SELECT value FROM identity").fetchone()
            if row is None:
                if guard.exists():
                    raise ValueError("initialized replica database was replaced")
                database.execute("INSERT INTO identity VALUES(?)", (encode(identity),))
            elif decode(row[0]) != identity:
                raise ValueError("database belongs to another replica")
            for scope in self.fences.load():
                head = self._head(database, scope)
                if head is not None:
                    self.membership.verify_certificate(head)
                self.fences.check(scope, head)
        if not guard.exists():
            with guard.open("xb") as stream:
                stream.write(encode(identity))
                stream.flush()
                os.fsync(stream.fileno())
            sync_directory(self.root)
            sync_directory(self.root.parent)

    @staticmethod
    def _head(database, scope):
        row = database.execute(
            "SELECT certificate FROM states WHERE scope=? ORDER BY sequence DESC LIMIT 1",
            (scope,),
        ).fetchone()
        return decode(row[0]) if row else None

    def _admit_next(self, database, proposal):
        state = self.membership.verify_proposal(proposal)
        head = self._head(database, state["scope"])
        self.fences.check(state["scope"], head)
        prior = (
            self.membership.verify_certificate(head)
            if head
            else dict(
                authority_id=self.membership.authority_id,
                membership_sha256=self.membership.sha256,
                scope=state["scope"],
                sequence=0,
                frontier=dict(scope=state["scope"], epoch=0, revoked=[]),
                placements=[],
            )
        )
        if state["previous_sha256"] != (digest(head["proposal"]) if head else ZERO):
            raise ValueError("authority proposal does not extend local committed head")
        validate_state(state, prior)
        if state["sequence"] > MAX_HISTORY:
            raise ValueError("authority history budget exceeded")
        scopes = {
            row[0]
            for row in database.execute(
                "SELECT DISTINCT scope FROM votes UNION SELECT DISTINCT scope FROM states"
            )
        }
        if state["scope"] not in scopes and len(scopes) >= 64:
            raise ValueError("authority scope budget exceeded")
        return state

    def prepare(self, proposal):
        state = self.membership.verify_proposal(proposal)
        scope, sequence, pin = state["scope"], state["sequence"], digest(proposal)
        with transaction(self.database) as database:
            voted = database.execute(
                "SELECT pin,vote FROM votes WHERE scope=? AND sequence=?",
                (scope, sequence),
            ).fetchone()
            if voted:
                if voted[0] != pin:
                    raise ValueError(
                        "replica already voted for another state at this sequence"
                    )
                return decode(voted[1])
            self._admit_next(database, proposal)
            vote = self.membership.vote(proposal, self.member_id, self.private_key)
            database.execute(
                "INSERT INTO votes VALUES(?,?,?,?,?)",
                (scope, sequence, pin, encode(proposal), encode(vote)),
            )
        return vote

    def commit(self, certificate):
        state = self.membership.verify_certificate(certificate)
        scope, sequence, pin = (
            state["scope"],
            state["sequence"],
            digest(certificate["proposal"]),
        )
        with transaction(self.database) as database:
            row = database.execute(
                "SELECT pin FROM states WHERE scope=? AND sequence=?", (scope, sequence)
            ).fetchone()
            if row:
                if row[0] != pin:
                    raise ValueError("certificate conflicts with committed history")
            else:
                self._admit_next(database, certificate["proposal"])
                database.execute(
                    "INSERT INTO states VALUES(?,?,?,?)",
                    (scope, sequence, pin, encode(certificate)),
                )
            head = self._head(database, scope)
        self.fences.advance(head)
        return dict(
            member_id=self.member_id,
            proposal_sha256=pin,
            committed_sequence=sequence,
            head_sequence=head["proposal"]["state"]["sequence"],
        )

    def read(self, scope):
        if not name(scope):
            raise ValueError("scope required")
        with transaction(self.database) as database:
            head = self._head(database, scope)
        if head:
            self.membership.verify_certificate(head)
        self.fences.check(scope, head)
        return dict(member_id=self.member_id, certificate=head)

    def history(self, scope, after):
        if not name(scope) or not integer(after):
            raise ValueError("bounded history cursor required")
        with transaction(self.database) as database:
            rows = database.execute(
                "SELECT certificate FROM states WHERE scope=? AND sequence>? ORDER BY sequence LIMIT 8",
                (scope, after),
            ).fetchall()
        return dict(
            member_id=self.member_id, certificates=[decode(row[0]) for row in rows]
        )

    def pending(self, scope):
        if not name(scope):
            raise ValueError("scope required")
        with transaction(self.database) as database:
            head = self._head(database, scope)
            sequence = head["proposal"]["state"]["sequence"] if head else 0
            rows = database.execute(
                "SELECT proposal,vote FROM votes WHERE scope=? AND sequence>? ORDER BY sequence LIMIT 1",
                (scope, sequence),
            ).fetchall()
        return dict(
            member_id=self.member_id,
            pending=[
                dict(proposal=decode(row[0]), vote=decode(row[1])) for row in rows
            ],
        )

    def dispatch(self, request):
        operation = request.get("op") if type(request) is dict else None
        if operation == "prepare":
            fields(request, ("op", "proposal"))
            return self.prepare(request["proposal"])
        if operation == "commit":
            fields(request, ("op", "certificate"))
            return self.commit(request["certificate"])
        if operation in ("read", "pending"):
            fields(request, ("op", "scope"))
            return getattr(self, operation)(request["scope"])
        if operation == "history":
            fields(request, ("op", "scope", "after"))
            return self.history(request["scope"], request["after"])
        if operation == "status":
            fields(request, ("op",))
            return dict(
                member_id=self.member_id,
                membership_sha256=self.membership.sha256,
                pid=os.getpid(),
                leader_election=False,
            )
        raise ValueError("unknown replica operation")
