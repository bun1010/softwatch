"""Name-collision filter (handover pack D6.2). A name-only hit is not evidence.

An artifact counts for repo R only when one anchor holds:
  url:    the artifact text contains R's owner/repo string or GitHub URL
  topic:  the artifact's whole-word name matches R's name AND they share a GitHub topic,
          and, for short or dictionary-like names (<= 4 chars), the owner also appears.
"""
import re


def _text(artifact):
    return " ".join(filter(None, [artifact.get("full_name"), artifact.get("description")])).lower()


def anchor_for(repo_owner, repo_name, repo_topics, artifact):
    """Returns 'url', 'topic' or None."""
    text = _text(artifact)
    owner_repo = f"{repo_owner}/{repo_name}".lower()
    if owner_repo in text or f"github.com/{owner_repo}" in text:
        return "url"
    name = repo_name.lower()
    if not re.search(rf"\b{re.escape(name)}\b", text):
        return None
    shared = set(repo_topics or []) & set(artifact.get("topics") or [])
    if not shared:
        return None
    if len(name) <= 4 and repo_owner.lower() not in text:
        return None
    return "topic"


def name_collision_rate(name_hits, matched):
    """1 - matched/name_hits; None when there were no hits to judge."""
    if not name_hits:
        return None
    return 1 - matched / name_hits
