"""Provision the shared read-only demo from Futon's live public history."""

from .db import encode, now, transaction

DEMO_REPO = "appfuton/futon"
DEMO_SCAN = "demo-futon"
DEMO_OWNER = "public-demo:futon"
DEMO_PREFERENCE_PRS = (112, 146)


def read_owner(owner, scan_id):
    return DEMO_OWNER if scan_id == DEMO_SCAN else owner


def ensure_demo():
    timestamp = now()
    with transaction(write=True) as tx:
        tx.run("""
            MERGE (s:SFScan {id: $id})
            ON CREATE SET s.owner = $owner, s.repo = $repo, s.state = 'queued',
                          s.created = $now, s.updated = $now, s.options = $options
            WITH s
            WHERE s.owner = $owner AND s.state = 'failed' AND s.knowledgeRevision IS NULL
                  AND s.updated <= $retry
            SET s.state = 'queued', s.updated = $now, s.result = null
            """, id=DEMO_SCAN, owner=DEMO_OWNER, repo=DEMO_REPO, now=timestamp, retry=timestamp - 120,
               options=encode({"ai": False})).consume()
