from neo4j.exceptions import DriverError, Neo4jError

from . import config
from .db import close, driver, transaction

REVISION = 1
CONSTRAINTS = {
    "sf_workspace_owner": ("SFWorkspace", "owner"),
    "sf_session_token": ("SFSession", "token"),
    "sf_scan_id": ("SFScan", "id"),
    "sf_attempt_id": ("SFAttempt", "id"),
    "sf_profile_owner": ("SFProfile", "owner"),
    "sf_store_id": ("SFStore", "id"),
}
INDEXES = {
    "sf_session_owner": ("SFSession", "owner"),
    "sf_session_expiry": ("SFSession", "expires"),
    "sf_scan_owner_created": ("SFScan", "owner, n.created"),
    "sf_knowledge_scan_record": ("SFKnowledgeRecord", "scan, n.id"),
    "sf_knowledge_scan": ("SFKnowledgeRecord", "scan"),
    "sf_scan_queue": ("SFScan", "state, n.updated"),
    "sf_attempt_owner_created": ("SFAttempt", "owner, n.created"),
}


def migrate():
    try:
        with driver().session(database=config.NEO4J_DATABASE) as session:
            for name, (label, prop) in CONSTRAINTS.items():
                session.run(f"CREATE CONSTRAINT {name} IF NOT EXISTS FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
                            ).consume()
            for name, (label, properties) in INDEXES.items():
                session.run(f"CREATE INDEX {name} IF NOT EXISTS FOR (n:{label}) ON (n.{properties})").consume()
            session.run("""
                MERGE (s:SFStore {id: 'skillforge'})
                ON CREATE SET s.revision = $revision, s.queueVersion = 0
                """, revision=REVISION).consume()
        require_current_schema()
    except (DriverError, Neo4jError) as exc:
        raise RuntimeError(f"Neo4j schema initialization failed ({type(exc).__name__}).") from None


def require_current_schema():
    try:
        with transaction() as tx:
            row = tx.run("MATCH (s:SFStore {id: 'skillforge'}) RETURN s.revision AS revision").single()
    except (DriverError, Neo4jError) as exc:
        raise RuntimeError(f"Neo4j startup check failed ({type(exc).__name__}).") from None
    if not row or row["revision"] != REVISION:
        raise RuntimeError("Apply the required Neo4j migration with python -m skillforge.migrate.")


if __name__ == "__main__":
    try:
        migrate()
    finally:
        close()
