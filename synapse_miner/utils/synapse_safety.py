"""
Snapshot Synapse tables before and after every automated write.

Same policy as nf-research-tools-schema's scripts/synapse_safety.py: each
table write is bracketed by snapshot versions, independent of Synapse's
trash can, so any automated change can be rolled back by pointing a query at
the "before" version. This package never deletes table rows.

Snapshot comments carry the date, what was written and, in GitHub Actions,
the workflow run link, e.g.
  "2026-11-10 before: classify adds 3 rows https://github.com/.../runs/123"
"""

import logging
import os
from contextlib import contextmanager
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

# Synapse limits snapshot comments to 256 characters
_MAX_COMMENT = 256


def run_url() -> str:
    """The GitHub Actions run URL, or '' when running locally."""
    server = os.getenv("GITHUB_SERVER_URL", "").rstrip("/")
    repo = os.getenv("GITHUB_REPOSITORY", "")
    run_id = os.getenv("GITHUB_RUN_ID", "")
    return f"{server}/{repo}/actions/runs/{run_id}" if (server and repo and run_id) else ""


def snapshot_comment(when: str, action: str) -> str:
    """'<date> <when>: <action> <run url>', trimmed to Synapse's length limit."""
    url = run_url() or "local run"
    prefix = f"{date.today().isoformat()} {when}: "
    room = _MAX_COMMENT - len(prefix) - len(url) - 1
    return f"{prefix}{action[:max(room, 0)]} {url}"


def snapshot_table(syn, table_id: str, when: str, action: str) -> Optional[int]:
    """
    Create a snapshot version of a table and return its version number.

    Raises on failure: a write must not go ahead without its "before"
    snapshot.
    """
    comment = snapshot_comment(when, action)
    result = syn.create_snapshot_version(table_id, comment=comment)
    version = result.get("snapshotVersionNumber", result) if isinstance(result, dict) else result
    logger.info(f"Snapshotted {table_id} as version {version} ({comment})")
    return version


@contextmanager
def snapshots_around(syn, table_id: str, action: str):
    """
    Snapshot a table before the block runs and after it finishes.

    The "before" snapshot must succeed or the block is skipped (the error
    propagates). The "after" snapshot is taken even if the block fails part
    way, so a partial write is captured too; a failure there is logged, not
    raised, so it cannot hide the block's own error.
    """
    snapshot_table(syn, table_id, "before", action)
    try:
        yield
    finally:
        try:
            snapshot_table(syn, table_id, "after", action)
        except Exception as e:
            logger.warning(f"Could not take the after-write snapshot of {table_id}: {e}")
