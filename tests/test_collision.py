from softwatch.collision import anchor_for, name_collision_rate


def art(full, desc=None, topics=None):
    return {"full_name": full, "description": desc, "topics": topics or []}


def test_url_anchor_matches_owner_repo_string():
    a = art("someone/omarchy-nix", "NixOS port of omacom/omarchy")
    assert anchor_for("omacom", "omarchy", [], a) == "url"


def test_medusa_collision_rejected_without_anchor():
    # An unrelated project sharing the word 'medusa' and no topic overlap.
    a = art("acme/medusa-scanner", "security scanner for containers", ["security"])
    assert anchor_for("medusa-team", "medusa", ["llm", "decoding"], a) is None


def test_handy_collision_rejected():
    a = art("someone/Handy-tools", "a set of small utilities", ["cli"])
    assert anchor_for("other", "handy", ["cli-tools"], a) is None


def test_topic_anchor_needs_whole_word_and_shared_topic():
    a = art("dev/tuios-plugin", "plugin for tuios window manager", ["tui", "go"])
    assert anchor_for("Gaurav-Gosain", "tuios", ["tui", "go"], a) == "topic"


def test_short_name_needs_owner_too():
    a = art("dev/ab-tool", "ab testing tool", ["testing"])
    assert anchor_for("someone", "ab", ["testing"], a) is None


def test_collision_rate():
    assert name_collision_rate(0, 0) is None
    assert name_collision_rate(40, 0) == 1.0
    assert name_collision_rate(10, 9) == __import__('pytest').approx(0.1)
