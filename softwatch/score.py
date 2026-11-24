"""Scoring and classification. Formula and class rules follow handover pack PART B, with the
revision-2 fixes documented in docs/PLAN.md section 6. Missing inputs are NULL, never zero
masquerading as a measurement; a component that lacks data is reported in flags."""
import math


def components(m, cfg):
    W = cfg["weights"]
    flags = []

    vel7, vel28 = m.get("vel7"), m.get("vel28")
    if vel7 is None:
        vel_c = 0.0
        flags.append("velocity_unavailable")
    else:
        vel_c = math.sqrt(min(vel7, 100) / 100) * W["velocity"]

    accel_ratio, accel_c = None, 0.0
    if vel7 is not None and vel28 is not None:
        if vel7 * 7 + vel28 * 28 < 30:
            flags.append("low_volume")
        elif vel28 > 0:
            accel_ratio = vel7 / vel28
            accel_c = min(max(accel_ratio - 0.8, 0) / 0.8, 1) * W["accel"]
        else:
            flags.append("no_prior_activity")
    else:
        flags.append("acceleration_unavailable")

    if m.get("suspicious_stars"):
        vel_c *= 0.5
        flags.append("suspicious_stars")

    artifacts = m.get("artifacts_new_120d")
    if artifacts is None:
        sw_c = 0.0
        flags.append("switching_unavailable")
    else:
        sw_c = min(artifacts / 10, 1) * W["switching"]

    topics = m.get("topics") or []
    banned = set(cfg["banned"]["topics"])
    text = f"{m.get('name', '')} {m.get('description') or ''}".lower()
    if banned & set(topics) or any(b in text for b in ("awesome", "tutorial", "boilerplate",
                                                       "template", "course")):
        sub_c = 0.0
        flags.append("banned_topic")
    else:
        sub_c = {0: 0, 1: 5, 2: 10}.get(len(topics), W["substance"])

    domains = m.get("domains_90d")
    if domains is None:
        conf_c = 0.0
        flags.append("confirmation_unavailable")
    else:
        conf_c = min(len(domains) / 3, 1) * W["confirm"]

    total = round(vel_c + accel_c + sw_c + sub_c + conf_c, 1)
    return total, accel_ratio, {
        "velocity": round(vel_c, 2), "acceleration": round(accel_c, 2),
        "switching": round(sw_c, 2), "substance": round(sub_c, 2),
        "confirmation": round(conf_c, 2),
    }, flags


def surge_class(m, cfg):
    s = cfg["surge"]
    if m.get("surge_status") != "measured":
        return None
    if m["stars"] is None or not (s["min_stars"] <= m["stars"] <= s["max_stars"]):
        return None
    if (m.get("stars_last90") or 0) < s["min_growth_90d"]:
        return None
    if (m.get("share90") or 0) < s["share_90d"]:
        return None
    r = m.get("ratio90")
    if r is None:
        return None
    if r >= s["fast_ratio"]:
        return "fast"
    if s["min_ratio"] <= r < s["fast_ratio"]:
        return "climb"
    return "decelerating"


def classify(m, score, accel_ratio, cfg):
    """Apply PART B classification in order. Returns (class, reason)."""
    g, v = cfg["gates"], cfg["verdict"]
    age = m["age_days"]
    sc = surge_class(m, cfg)
    surging = sc in ("fast", "climb")

    if m.get("stars") is None:
        return "unscored", "stars unavailable"
    if age < g["min_age_days"]:
        return "rejected", "too young"
    if age > g["max_age_days"] and not surging:
        return "rejected", "older than 730 days without a measured surge"
    if (m.get("artifacts_new_120d") or 0) < g["min_ecosystem_artifacts"] and not surging:
        return "rejected", "fewer than 3 new artifacts"

    mature = age >= cfg["surge"]["class_min_age_days"]
    if mature and sc == "fast" and score >= 55:
        return "resurgent", "surge fast"
    if mature and sc == "climb" and score >= 55:
        return "climber", "surge climb"

    fresh = m.get("confirm_fresh", False)
    suspicious = "suspicious_stars" in m.get("flags", [])
    domains = m.get("domains_90d") or []
    if score >= v["inflection"] and accel_ratio is not None and accel_ratio >= v["accel_trigger"]:
        if domains and fresh and not suspicious:
            return "inflection", "score and acceleration with an independent source"
        return "emerging", "acceleration without a fresh independent source"
    if score >= v["emerging"]:
        return "emerging", "score"
    if score >= v["watch"]:
        return "watch", "score"
    return "dormant", "score below watch"


CLASS_RANK = {"watch": 1, "emerging": 2, "climber": 3, "resurgent": 4, "inflection": 5}
