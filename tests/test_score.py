from softwatch.config import load
from softwatch.score import classify, components, surge_class

CFG = load()


def base(**kw):
    m = {"name": "demo", "description": "", "topics": ["a", "b", "c"], "stars": 5000,
         "age_days": 400, "vel7": 30.0, "vel28": 10.0, "artifacts_new_120d": 12,
         "domains_90d": ["lwn.net", "theregister.com", "example.org"], "confirm_fresh": True,
         "surge_status": "unmeasurable_no_prior", "flags": []}
    m.update(kw)
    return m


def test_components_match_pi_formula():
    total, ratio, comps, flags = components(base(), CFG)
    # velocity: sqrt(min(30,100)/100)*25 = sqrt(0.3)*25
    assert comps["velocity"] == round((0.3 ** 0.5) * 25, 2)
    # accel: vel7/vel28 = 3.0 -> full 20
    assert ratio == 3.0 and comps["acceleration"] == 20.0
    assert comps["switching"] == 25.0 and comps["confirmation"] == 15.0
    assert comps["substance"] == 15.0
    assert total == round(comps["velocity"] + 20 + 25 + 15 + 15, 1)


def test_missing_switching_is_zero_and_flagged():
    _, _, comps, flags = components(base(artifacts_new_120d=None), CFG)
    assert comps["switching"] == 0.0 and "switching_unavailable" in flags


def test_low_volume_disables_acceleration():
    _, ratio, _, flags = components(base(vel7=0.1, vel28=0.1), CFG)
    assert ratio is None and "low_volume" in flags


def test_inflection_needs_independent_domain():
    m = base(domains_90d=[])
    score, ratio, _, _ = components(m, CFG)
    cls, _ = classify(m, 90, ratio, CFG)
    assert cls == "emerging"


def test_inflection_when_all_conditions_hold():
    m = base()
    score, ratio, _, _ = components(m, CFG)
    cls, _ = classify(m, 90, ratio, CFG)
    assert cls == "inflection"


def test_unmeasured_surge_cannot_become_resurgent():
    m = base(age_days=1000, surge_status="unmeasurable_truncated")
    cls, _ = classify(m, 95, 1.0, CFG)
    assert cls not in ("resurgent", "climber")


def test_measured_fast_surge_on_old_repo_is_resurgent():
    m = base(age_days=1000, surge_status="measured", ratio90=3.0, share90=0.3,
             stars_last90=1500, stars=5000)
    assert surge_class(m, CFG) == "fast"
    cls, _ = classify(m, 60, 1.0, CFG)
    assert cls == "resurgent"


def test_decelerating_surge_is_excluded():
    m = base(age_days=1000, surge_status="measured", ratio90=0.5, share90=0.18,
             stars_last90=900, stars=5000)
    assert surge_class(m, CFG) == "decelerating"


def test_ratio_074_follows_numeric_climb_rule():
    # Handover pack calls RapidRAW (0.74x) decelerating in prose, but its numeric rule
    # (0.7 <= ratio90 < 1.5 -> climb) places it in the climb band. The rule is implemented
    # as written and the conflict is flagged in the PR.
    m = base(age_days=1000, surge_status="measured", ratio90=0.74, share90=0.18,
             stars_last90=900, stars=5000)
    assert surge_class(m, CFG) == "climb"


def test_suspicious_stars_block_inflection():
    m = base(flags=["suspicious_stars"], suspicious_stars=True)
    _, ratio, _, _ = components(m, CFG)
    cls, _ = classify(m, 90, ratio, CFG)
    assert cls == "emerging"


def test_banned_topic_zeroes_substance():
    _, _, comps, flags = components(base(topics=["awesome"], description="awesome list"), CFG)
    assert comps["substance"] == 0.0 and "banned_topic" in flags
