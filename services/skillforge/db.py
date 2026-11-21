import hashlib
import json
import secrets
import time
from contextlib import contextmanager
from threading import Lock

from neo4j import READ_ACCESS, WRITE_ACCESS, GraphDatabase

from . import config

_driver = None
_driver_lock = Lock()


def driver():
    global _driver
    with _driver_lock:
        if _driver is None:
            auth = (config.NEO4J_USERNAME, config.NEO4J_PASSWORD) if config.NEO4J_PASSWORD else None
            _driver = GraphDatabase.driver(config.NEO4J_URI, auth=auth, connection_timeout=8,
                                           connection_acquisition_timeout=12)
        return _driver


def close():
    global _driver
    with _driver_lock:
        if _driver is not None:
            _driver.close()
            _driver = None


@contextmanager
def transaction(*, write=False):
    mode = WRITE_ACCESS if write else READ_ACCESS
    with (
        driver().session(database=config.NEO4J_DATABASE, default_access_mode=mode) as session,
        session.begin_transaction(timeout=12) as tx,
    ):
        yield tx
        tx.commit()


def now():
    return int(time.time())


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def encode(payload):
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def entity(row):
    data = dict(row["node"])
    for field in ("options", "result"):
        if field in data:
            data[field] = json.loads(data[field])
    data.setdefault("result", None)
    return data


def entities(tx, query, **parameters):
    return [entity(row) for row in tx.run(query, **parameters)]


def find_scan(tx, owner, scan_id):
    row = tx.run("MATCH (s:SFScan {id: $id, owner: $owner}) RETURN s AS node",
                 id=scan_id, owner=owner).single()
    return entity(row) if row else None


def find_attempt(tx, owner, attempt_id):
    row = tx.run("MATCH (a:SFAttempt {id: $id, owner: $owner}) RETURN a AS node",
                 id=attempt_id, owner=owner).single()
    return entity(row) if row else None


def recent_attempts(tx, owner, limit, *, after=None):
    return entities(tx, """
        MATCH (a:SFAttempt {owner: $owner})
        WHERE $after IS NULL OR a.created > $after
        RETURN a AS node ORDER BY a.created DESC, a.id DESC LIMIT $limit
        """, owner=owner, after=after, limit=limit)


def provision(owner=None, github=None, previous=None):
    token = secrets.token_urlsafe(32)
    owner = owner or "guest:" + secrets.token_urlsafe(24)
    timestamp = now()
    with transaction(write=True) as tx:
        # MERGE and update the workspace before writing its new session.
        tx.run("""
            MERGE (w:SFWorkspace {owner: $owner})
            SET w.version = coalesce(w.version, 0) + 1
            CREATE (:SFSession {token: $token, owner: $owner, github: $github, expires: $expires})
            """, owner=owner, token=digest(token), github=github or "",
               expires=timestamp + (30 * 86400 if github else 7200)).consume()
        if previous and len(previous) <= 120:
            tx.run("MATCH (s:SFSession {token: $token}) SET s.expires = $now",
                   token=digest(previous), now=timestamp).consume()
    return token


def session(token):
    if not token or len(token) > 120:
        return None
    with transaction() as tx:
        row = tx.run("""
            MATCH (s:SFSession {token: $token}) WHERE s.expires > $now
            RETURN s.owner AS owner, s.github AS github, s.expires AS expires
            """, token=digest(token), now=now()).single()
        return {**row.data(), "github": row["github"] or None} if row else None


def touch(token, current):
    timestamp = now()
    if current and not current["github"] and current["expires"] < timestamp + 7000:
        with transaction(write=True) as tx:
            tx.run("""
                MATCH (s:SFSession {token: $token})
                SET s.expires = CASE WHEN s.expires > $now THEN $expires ELSE s.expires END
                """, token=digest(token), now=timestamp, expires=timestamp + 7200).consume()


def lock_workspace(tx, owner):
    # A read-dependent SET takes the write lock before dependent reads and holds it until commit.
    return tx.run("""
        MATCH (w:SFWorkspace {owner: $owner})
        SET w.version = coalesce(w.version, 0) + 1
        RETURN w.owner AS owner
        """, owner=owner).single() is not None


def active_workspace(tx, owner, token):
    if not lock_workspace(tx, owner):
        return False
    return tx.run("""
        MATCH (s:SFSession {token: $token, owner: $owner})
        SET s.expires = s.expires + 0
        WITH s WHERE s.expires > $now
        RETURN s.token AS token
        """, owner=owner, token=digest(token), now=now()).single() is not None


class WorkspaceExpired(Exception):
    pass


@contextmanager
def workspace_write(owner, token):
    with transaction(write=True) as tx:
        if not active_workspace(tx, owner, token):
            raise WorkspaceExpired
        yield tx


def erase(tx, owner):
    # This workspace is already locked. Separate indexed lookups also leave other products' labels alone.
    tx.run("""
        MATCH (s:SFScan {owner: $owner}) WITH s ORDER BY s.id
        SET s.lock = coalesce(s.lock, 0) + 1
        """, owner=owner).consume()
    tx.run("""
        MATCH (:SFScan {owner: $owner})-[:SF_HAS_EVIDENCE]->(record:SFKnowledgeRecord)
        DETACH DELETE record
        """, owner=owner).consume()
    for label in ("SFScan", "SFAttempt", "SFProfile", "SFSession", "SFWorkspace"):
        tx.run(f"MATCH (n:{label} {{owner: $owner}}) DELETE n", owner=owner).consume()


def expire_guests():
    timestamp = now()
    with transaction() as tx:
        owners = tx.run("""
            MATCH (s:SFSession)
            WHERE s.expires <= $now AND s.owner STARTS WITH 'guest:'
            RETURN DISTINCT s.owner AS owner LIMIT 100
            """, now=timestamp).value("owner")
    for owner in owners:
        with transaction(write=True) as tx:
            if lock_workspace(tx, owner):
                # Lock the expired session rows too, since sliding expiration can refresh them.
                sessions = tx.run("""
                    MATCH (s:SFSession {owner: $owner})
                    SET s.expires = s.expires + 0
                    RETURN s.expires AS expires
                    """, owner=owner).value("expires")
                if sessions and all(expiry <= timestamp for expiry in sessions):
                    erase(tx, owner)
    with transaction(write=True) as tx:
        tx.run("""
            MATCH (s:SFSession) WHERE s.expires <= $now AND NOT s.owner STARTS WITH 'guest:'
            WITH s LIMIT 100 DELETE s
            """, now=timestamp).consume()
