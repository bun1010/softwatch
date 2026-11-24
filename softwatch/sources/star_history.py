"""Parse star-history.com SVG charts into dated star-count anchors.

The chart is a hand-drawn (xkcd-style) SVG. Its data series is a path (class
"xkcd-chart-xyline") whose segment endpoints are the anchors. The axes are calibrated
from the labelled ticks: y from numeric labels ("10K", "20K", ...; a blank label is 0),
x from date labels (month names with year labels, or year labels alone). Anchors are
only kept when the calibration fits its own labels. The caller must still check the
latest anchor against the live star count (see `consistent_with`).

Nothing is interpolated into a number that is not a chart anchor, and every function
returns None or an error rather than a guess.
"""
import datetime as dt
import re

MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], start=1)}
MONTH_TO_NUM = {k[:3].lower(): v for k, v in MONTHS.items()}
EPOCH = dt.date(2000, 1, 1)


class ChartError(ValueError):
    pass


def _texts(body):
    out = []
    for m in re.finditer(r'<text[^>]*?transform="translate\(([-\d.]+) ([-\d.]+)\)"[^>]*>(.*?)</text>',
                         body, flags=re.S):
        label = re.sub(r"<[^>]+>", "", m.group(3)).strip()
        out.append((label, float(m.group(1)), float(m.group(2))))
    return out


def _path_points(body):
    m = re.search(r'<path[^>]*class="xkcd-chart-xyline"[^>]*>', body)
    if not m:
        raise ChartError("no data path")
    d = re.search(r' d="([^"]*)"', m.group(0))
    if not d:
        raise ChartError("no path data")
    return _points_from_d(d.group(1))


_TOKEN = re.compile(r"[MLHVCSQTAmlhvcsqtaz]|-?\d*\.?\d+(?:e-?\d+)?")
_ARITY = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}


def _points_from_d(d):
    """Endpoints of every segment, in absolute coordinates."""
    tokens = _TOKEN.findall(d)
    pts, i, cmd, cx, cy, sx, sy = [], 0, None, 0.0, 0.0, 0.0, 0.0
    while i < len(tokens):
        t = tokens[i]
        if re.match(r"[A-Za-z]", t):
            cmd = t
            i += 1
            if cmd in "Zz":
                cx, cy = sx, sy
                continue
        elif cmd is None:
            raise ChartError("path does not start with a command")
        base = cmd.upper()
        if base not in _ARITY:
            raise ChartError(f"unsupported path command {cmd}")
        n = _ARITY[base]
        if n == 0 or i + n > len(tokens):
            raise ChartError("truncated path data")
        args = [float(x) for x in tokens[i:i + n]]
        i += n
        rel = cmd.islower()
        if base == "M":
            cx, cy = (cx + args[0], cy + args[1]) if rel else (args[0], args[1])
            sx, sy = cx, cy
            cmd = "l" if rel else "L"  # subsequent pairs are implicit line-tos
            pts.append((cx, cy))
            continue
        if base in ("L", "T"):
            cx, cy = (cx + args[0], cy + args[1]) if rel else (args[0], args[1])
        elif base == "H":
            cx = cx + args[0] if rel else args[0]
        elif base == "V":
            cy = cy + args[0] if rel else args[0]
        elif base in ("C", "S", "Q"):
            ex, ey = args[-2], args[-1]
            cx, cy = (cx + ex, cy + ey) if rel else (ex, ey)
        elif base == "A":
            ex, ey = args[5], args[6]
            cx, cy = (cx + ex, cy + ey) if rel else (ex, ey)
        pts.append((cx, cy))
    return pts


def _fit(xs, ys):
    """Least-squares line y = a*x + b. Returns (a, b, max_abs_residual)."""
    n = len(xs)
    if n < 2:
        raise ChartError("need at least two calibration labels")
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        raise ChartError("calibration labels share one position")
    a = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    b = my - a * mx
    return a, b, max(abs(a * x + b - y) for x, y in zip(xs, ys))


def _date_labels(texts):
    """Assign a date to each x label. Year labels anchor Jan 1; month labels step from them
    by the nearest matching month in the right direction. Returns [(x, date)]."""
    items = []
    for label, x, _ in texts:
        if re.fullmatch(r"\d{4}", label):
            items.append((x, "year", dt.date(int(label), 1, 1)))
        elif label.lower()[:3] in MONTH_TO_NUM and label.isalpha():
            items.append((x, "month", MONTH_TO_NUM[label.lower()[:3]]))
    items.sort()
    anchors = [i for i, it in enumerate(items) if it[1] == "year"]
    if not anchors:
        raise ChartError("no year label to anchor the date axis")
    out = {}
    a0 = anchors[0]
    out[a0] = items[a0][2]
    for i in range(a0 + 1, len(items)):  # right of the anchor
        prev = out[i - 1]
        if items[i][1] == "year":
            out[i] = items[i][2]
            continue
        m = items[i][2]
        y = prev.year + (1 if m <= prev.month else 0)
        out[i] = dt.date(y, m, 1)
    for i in range(a0 - 1, -1, -1):  # left of the anchor
        nxt = out[i + 1]
        if items[i][1] == "year":
            out[i] = items[i][2]
            continue
        m = items[i][2]
        y = nxt.year - (1 if m >= nxt.month else 0)
        out[i] = dt.date(y, m, 1)
    return [(items[i][0], out[i]) for i in range(len(items))]


def _y_ticks(texts):
    """Y-axis labels sit at translate-x 0; x-axis labels do not (they must not be read as ticks)."""
    ticks = []
    for label, x, y in texts:
        if abs(x) >= 1.0:
            continue
        if label == "":
            ticks.append((y, 0.0))  # the baseline label is blank
            continue
        m = re.fullmatch(r"(\d+(?:\.\d+)?)([KkMm]?)", label)
        if not m:
            continue
        mult = {"": 1, "k": 1e3, "K": 1e3, "m": 1e6, "M": 1e6}[m.group(2)]
        ticks.append((y, float(m.group(1)) * mult))
    return ticks


def parse(svg_text):
    """Returns {'anchors': [(date, stars)], 'x_residual_days', 'y_residual', 'ticks'}.
    Raises ChartError if the chart cannot be calibrated."""
    body = re.sub(r"<defs>.*?</defs>", "<defs/>", svg_text, flags=re.S)
    texts = _texts(body)
    pts = _path_points(body)
    if len(pts) < 2:
        raise ChartError("too few points")

    dates = _date_labels(texts)
    if len(dates) < 2:
        raise ChartError("too few date labels")
    xs = [x for x, _ in dates]
    ds = [(d - EPOCH).days for _, d in dates]
    ax, bx, rx = _fit(xs, ds)
    if rx > 6:
        raise ChartError(f"date axis does not fit its labels (max error {rx:.1f} days)")

    ticks = _y_ticks(texts)
    if len(ticks) < 3:
        raise ChartError("too few y ticks")
    ys = [y for y, _ in ticks]
    vs = [v for _, v in ticks]
    ay, by, ry = _fit(ys, vs)
    top = max(vs) or 1.0
    if ry / top > 0.02:
        raise ChartError(f"y axis does not fit its ticks (residual {ry / top:.1%})")

    anchors = []
    for x, y in pts:
        day = EPOCH + dt.timedelta(days=round(ax * x + bx))
        stars = ay * y + by
        anchors.append((day, max(stars, 0.0)))
    anchors.sort(key=lambda a: a[0])
    # Stars are cumulative: drop backward noise from the hand-drawn line.
    mono, best = [], 0.0
    for day, s in anchors:
        best = max(best, s)
        mono.append((day, best))
    return {"anchors": mono, "x_residual_days": rx, "y_residual": ry, "ticks": len(ticks)}


def consistent_with(anchors, live_stars, tolerance):
    """The chart's latest anchor must agree with today's star count from the API."""
    if not anchors or not live_stars:
        return False
    last = anchors[-1][1]
    return abs(last - live_stars) / live_stars <= tolerance
