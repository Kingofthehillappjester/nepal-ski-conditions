#!/usr/bin/env python3
"""Nepal Ski Conditions: fetches Open-Meteo forecasts for Nepal's ski zones and
renders a static site into dist/. Standard library only.

  python build.py                    fetch live data and build
  python build.py --raw FILE.json    build from a saved API response (no network)

Environment:
  OPEN_METEO_API_KEY   use the commercial API (customer-api.open-meteo.com)
  SITE_URL             public base URL, no trailing slash
  CUSTOM_DOMAIN        e.g. nepalskiing.com, writes a CNAME file for GitHub Pages
  ALLOW_INDEXING=1     let search engines index the site (default: noindex)
"""
import datetime as dt
import html
import json
import math
import os
import pathlib
import shutil
import sys
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
DIST = ROOT / "dist"
HISTORY = ROOT / "data" / "history"
ZONES = json.loads((ROOT / "zones.json").read_text())
SPONSOR = json.loads((ROOT / "trips.json").read_text())
TRIPS = {t["key"]: t for t in SPONSOR["trips"]}
OUTLINE = json.loads((ROOT / "nepal-outline.json").read_text())["coords"]

API_KEY = os.environ.get("OPEN_METEO_API_KEY", "").strip()
SITE_URL = (os.environ.get("SITE_URL") or "https://kingofthehillappjester.github.io/nepal-ski-conditions").rstrip("/")
CUSTOM_DOMAIN = os.environ.get("CUSTOM_DOMAIN", "").strip()
ALLOW_INDEXING = os.environ.get("ALLOW_INDEXING") == "1"
SITE_NAME = "Nepal Ski Conditions"
UTM = "utm_source=nepalskiing&utm_medium=sponsored&utm_campaign=conditions"

DAILY_VARS = "weather_code,temperature_2m_max,temperature_2m_min,snowfall_sum,precipitation_sum,wind_speed_10m_max,wind_gusts_10m_max,sunrise,sunset"
HOURLY_VARS = "temperature_2m,snowfall,precipitation,freezing_level_height,wind_speed_10m,wind_gusts_10m,cloud_cover,weather_code,wind_speed_500hPa,wind_speed_400hPa"
CURRENT_VARS = "temperature_2m,weather_code,wind_speed_10m,wind_gusts_10m,snowfall,freezing_level_height,cloud_cover,is_day"

# Outlook categories. Colours validated for the dark surface (dataviz validator, all pairs).
OUTLOOK = {
    "fresh": ("Fresh snow", "#338ced"),
    "coming": ("Snow on the way", "#e24d8b"),
    "wind": ("Strong winds up high", "#d28e05"),
    "settled": ("Settled", "#8a97ab"),
}

# ---------------------------------------------------------------- data fetch

def fetch():
    host = "https://customer-api.open-meteo.com" if API_KEY else "https://api.open-meteo.com"
    lat, lon, elev = [], [], []
    for z in ZONES:
        for level in ("base", "top"):
            lat.append(z["lat"]); lon.append(z["lon"]); elev.append(z[level]["elev"])
    common = {"latitude": ",".join(map(str, lat)), "longitude": ",".join(map(str, lon)),
              "elevation": ",".join(map(str, elev)), "timezone": "Asia/Kathmandu", "wind_speed_unit": "kmh"}
    if API_KEY:
        common["apikey"] = API_KEY
    daily_q = dict(common, daily=DAILY_VARS, past_days=92, forecast_days=10)
    hourly_q = dict(common, hourly=HOURLY_VARS, current=CURRENT_VARS, past_hours=72, forecast_hours=240)
    out = {}
    for key, q in (("daily", daily_q), ("hourly", hourly_q)):
        url = host + "/v1/forecast?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(url, headers={"User-Agent": "nepal-ski-conditions (github.com/Kingofthehillappjester/nepal-ski-conditions)"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    out[key] = json.loads(r.read())
                break
            except Exception as e:  # retry transient errors
                if attempt == 2:
                    raise
                print("retrying", key, e)
    return out

# ---------------------------------------------------------------- helpers

def t(s):
    return dt.datetime.fromisoformat(s)

def r1(x):
    return None if x is None else round(x, 1)

def nsum(vals):
    return round(sum(v for v in vals if v is not None), 1)

def nmax(vals):
    vals = [v for v in vals if v is not None]
    return max(vals) if vals else None

def nmean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None

def esc(s):
    return html.escape(str(s), quote=True)

WMO = {
    0: ("Clear", "clear"), 1: ("Mostly clear", "clear"), 2: ("Partly cloudy", "partly"), 3: ("Overcast", "cloud"),
    45: ("Fog", "fog"), 48: ("Freezing fog", "fog"),
    51: ("Light drizzle", "rain"), 53: ("Drizzle", "rain"), 55: ("Heavy drizzle", "rain"), 56: ("Freezing drizzle", "rain"), 57: ("Freezing drizzle", "rain"),
    61: ("Light rain", "rain"), 63: ("Rain", "rain"), 65: ("Heavy rain", "rain"), 66: ("Freezing rain", "rain"), 67: ("Freezing rain", "rain"),
    71: ("Light snow", "snow"), 73: ("Snow", "snow"), 75: ("Heavy snow", "snow"), 77: ("Snow grains", "snow"),
    80: ("Showers", "rain"), 81: ("Showers", "rain"), 82: ("Heavy showers", "rain"),
    85: ("Snow showers", "snow"), 86: ("Heavy snow showers", "snow"),
    95: ("Thunderstorm", "storm"), 96: ("Thunderstorm, hail", "storm"), 99: ("Thunderstorm, hail", "storm"),
}

def wmo(code, is_day=True):
    label, icon = WMO.get(int(code) if code is not None else 0, ("Unknown", "cloud"))
    if icon == "clear" and not is_day:
        icon = "moon"
    return label, icon

ICON_PATHS = {
    "clear": '<circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6"/>',
    "moon": '<path d="M19.5 14.5A8 8 0 0 1 9.5 4.5a8 8 0 1 0 10 10z"/>',
    "partly": '<path d="M8.5 5.2V3.5M3.8 9.5H2.2M4.8 5.8 3.7 4.7M13.2 5.8l1.1-1.1"/><path d="M5.6 11.3a3.4 3.4 0 1 1 6.2-2.6"/><path d="M8 19.5h10a3.5 3.5 0 0 0 .4-7 5 5 0 0 0-9.6 1.2A2.9 2.9 0 0 0 8 19.5z"/>',
    "cloud": '<path d="M7 19h11a4 4 0 0 0 .5-8 6 6 0 0 0-11.5 1.5A3.3 3.3 0 0 0 7 19z"/>',
    "fog": '<path d="M7 13h11a4 4 0 0 0 .5-8 6 6 0 0 0-11.5 1.5"/><path d="M4 16.5h16M6 20h12"/>',
    "rain": '<path d="M7 15h11a4 4 0 0 0 .5-8 6 6 0 0 0-11.5 1.5A3.3 3.3 0 0 0 7 15z"/><path d="M9 18l-1 2.5M13 18l-1 2.5M17 18l-1 2.5"/>',
    "snow": '<path d="M7 14h11a4 4 0 0 0 .5-8 6 6 0 0 0-11.5 1.5A3.3 3.3 0 0 0 7 14z"/><path d="M8.5 17.5v4M6.8 18.5l3.4 2M6.8 20.5l3.4-2M15.5 17.5v4M13.8 18.5l3.4 2M13.8 20.5l3.4-2"/>',
    "storm": '<path d="M7 14h11a4 4 0 0 0 .5-8 6 6 0 0 0-11.5 1.5A3.3 3.3 0 0 0 7 14z"/><path d="M12.5 15.5 10 19.5h3l-2 3.5"/>',
}

def icon(name, cls="wx", title=None):
    t_ = f"<title>{esc(title)}</title>" if title else ""
    return (f'<svg class="{cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" '
            f'stroke-linecap="round" stroke-linejoin="round" role="img" aria-label="{esc(title or name)}">{t_}{ICON_PATHS[name]}</svg>')

# Unit-aware number. JS swaps between metric and imperial; metric is rendered server-side.
def u(kind, v, dp=0):
    if v is None:
        return '<span class="na">–</span>'
    if kind == "t":
        txt = f"{round(v):d}°" if dp == 0 else f"{v:.1f}°"
        txt = txt.replace("-", "−")
    elif kind == "s":
        txt = f"{v:.0f}" if v >= 10 or dp == 0 and v.is_integer() else f"{v:.1f}"
        txt += "<small>cm</small>"
    elif kind == "e":
        txt = f"{v:,.0f}<small>m</small>"
    elif kind == "w":
        txt = f"{v:.0f}<small>km/h</small>"
    else:
        txt = str(v)
    return f'<span class="u" data-k="{kind}" data-v="{v}">{txt}</span>'

# ---------------------------------------------------------------- analysis

def summarise(raw):
    now_s = raw["hourly"][0]["current"]["time"]
    now = t(now_s)
    today = now.date()
    season_start = dt.date(today.year if today.month >= 10 else today.year - 1, 10, 1)
    history = load_history()
    zones = []
    for i, z in enumerate(ZONES):
        bd, td = raw["daily"][2 * i]["daily"], raw["daily"][2 * i + 1]["daily"]
        bh, th = raw["hourly"][2 * i], raw["hourly"][2 * i + 1]
        hb, ht = bh["hourly"], th["hourly"]
        htimes = [t(x) for x in hb["time"]]
        dates = [dt.date.fromisoformat(x) for x in bd["time"]]
        ti = dates.index(today)

        def hsum(arr, start, end):
            return nsum(v for tt, v in zip(htimes, arr) if start < tt <= end)

        past24 = hsum(hb["snowfall"], now - dt.timedelta(hours=24), now)
        past72 = hsum(hb["snowfall"], now - dt.timedelta(hours=72), now)
        next24 = hsum(hb["snowfall"], now, now + dt.timedelta(hours=24))
        next72 = hsum(hb["snowfall"], now, now + dt.timedelta(hours=72))
        next7 = hsum(hb["snowfall"], now, now + dt.timedelta(days=7))
        top_next7 = hsum(ht["snowfall"], now, now + dt.timedelta(days=7))
        past7 = nsum(bd["snowfall_sum"][ti - 7:ti])
        past30 = nsum(bd["snowfall_sum"][ti - 30:ti])
        top_past7 = nsum(td["snowfall_sum"][ti - 7:ti])

        # season total: model days in window + stored history for older days
        first = dates[0]
        season = nsum(v for d, v in zip(dates[:ti], bd["snowfall_sum"][:ti]) if d >= season_start)
        season_from = max(first, season_start)
        if first > season_start:
            older = [h for d, h in history.items() if season_start <= d < first]
            season = round(season + sum(h.get(z["slug"], {}).get("base_snow", 0) or 0 for h in older), 1)
            dated = sorted(d for d, h in history.items() if season_start <= d < first and z["slug"] in h)
            season_from = dated[0] if dated else first

        # summit wind from the pressure level nearest the summit (500 hPa ~ 5,600m, 400 hPa ~ 7,200m)
        lvl = "400" if abs(z["top"]["elev"] - 7200) < abs(z["top"]["elev"] - 5600) else "500"
        summit = hb[f"wind_speed_{lvl}hPa"]
        ni = min(range(len(htimes)), key=lambda k: abs((htimes[k] - now).total_seconds()))
        summit_now = summit[ni]
        summit_48 = nmax(v for tt, v in zip(htimes, summit) if now < tt <= now + dt.timedelta(hours=48))

        cur_b, cur_t = bh["current"], th["current"]
        # forecast days (today + 9), aggregated from hourly where daily has no field
        fdays = []
        for k in range(ti, len(dates)):
            d = dates[k]
            hrs = [j for j, tt in enumerate(htimes) if tt.date() == d]
            day_hrs = [j for j in hrs if 7 <= htimes[j].hour <= 17]
            fdays.append({
                "date": d.isoformat(),
                "code": bd["weather_code"][k],
                "base_max": r1(bd["temperature_2m_max"][k]), "base_min": r1(bd["temperature_2m_min"][k]),
                "top_max": r1(td["temperature_2m_max"][k]), "top_min": r1(td["temperature_2m_min"][k]),
                "snow": r1(bd["snowfall_sum"][k]), "top_snow": r1(td["snowfall_sum"][k]),
                "gust": r1(bd["wind_gusts_10m_max"][k]),
                "freezing": r1(nmean(hb["freezing_level_height"][j] for j in hrs)) if hrs else None,
                "cloud_day": r1(nmean(hb["cloud_cover"][j] for j in day_hrs)) if day_hrs else None,
                "summit_wind": r1(nmax(summit[j] for j in hrs)) if hrs else None,
            })
        past = [{"date": dates[k].isoformat(), "snow": r1(bd["snowfall_sum"][k]), "top_snow": r1(td["snowfall_sum"][k]),
                 "base_max": r1(bd["temperature_2m_max"][k]), "base_min": r1(bd["temperature_2m_min"][k]),
                 "top_max": r1(td["temperature_2m_max"][k]), "top_min": r1(td["temperature_2m_min"][k])}
                for k in range(ti - 14, ti)]

        # next 72 hours, every 3 hours
        hours = []
        for j, tt in enumerate(htimes):
            if now <= tt <= now + dt.timedelta(hours=72) and tt.hour % 3 == 0:
                hours.append({"time": tt.isoformat(timespec="minutes"), "code": hb["weather_code"][j],
                              "base_t": r1(hb["temperature_2m"][j]), "top_t": r1(ht["temperature_2m"][j]),
                              "snow": round(sum((hb["snowfall"][m] or 0) for m in range(max(0, j - 2), j + 1)), 1),
                              "gust": r1(hb["wind_gusts_10m"][j]), "freezing": r1(hb["freezing_level_height"][j]),
                              "summit_wind": r1(summit[j]), "is_day": 1 if 6 <= tt.hour <= 17 else 0})

        # outlook
        if (cur_b.get("snowfall") or 0) > 0.05 or past72 >= 10 or past24 >= 5:
            outlook = "fresh"
        elif next72 >= 10:
            outlook = "coming"
        elif (summit_48 or 0) >= 70:
            outlook = "wind"
        else:
            outlook = "settled"
        snowing_now = (cur_b.get("snowfall") or 0) > 0.05

        # best-looking day in the next 7: light wind, clear sky, not snowing
        best = None
        for fd in fdays[1:8]:
            if fd["gust"] is None or fd["cloud_day"] is None:
                continue
            score = fd["gust"] + 0.5 * fd["cloud_day"] + 8 * (fd["snow"] or 0)
            if best is None or score < best[0]:
                best = (score, fd)
        best_day = None
        if best:
            fd = best[1]
            best_day = {"date": fd["date"], "gust": fd["gust"], "cloud": fd["cloud_day"], "snow": fd["snow"]}

        zones.append({
            **{k: z[k] for k in ("slug", "name", "region", "lat", "lon", "base", "top", "season", "about", "level", "trip", "guide")},
            "now": {"time": now_s, "base_t": r1(cur_b["temperature_2m"]), "top_t": r1(cur_t["temperature_2m"]),
                    "code": cur_b["weather_code"], "is_day": cur_b.get("is_day", 1), "gust": r1(cur_b["wind_gusts_10m"]),
                    "wind": r1(cur_b["wind_speed_10m"]), "freezing": r1(cur_b["freezing_level_height"]),
                    "cloud": cur_b.get("cloud_cover"), "summit_wind": r1(summit_now), "summit_level": lvl},
            "snow": {"past24": past24, "past72": past72, "past7": past7, "past30": past30, "next24": next24,
                     "next72": next72, "next7": next7, "season": season, "season_from": season_from.isoformat(),
                     "top_past7": top_past7, "top_next7": top_next7},
            "outlook": outlook, "snowing_now": snowing_now, "summit_48": r1(summit_48),
            "tonight_top_min": fdays[0]["top_min"] if fdays else None,
            "best_day": best_day, "days": fdays, "past": past, "hours": hours,
            "yesterday": {"date": dates[ti - 1].isoformat(), "base_snow": r1(bd["snowfall_sum"][ti - 1]),
                          "top_snow": r1(td["snowfall_sum"][ti - 1]),
                          "base_min": r1(bd["temperature_2m_min"][ti - 1]), "base_max": r1(bd["temperature_2m_max"][ti - 1]),
                          "top_min": r1(td["temperature_2m_min"][ti - 1]), "top_max": r1(td["temperature_2m_max"][ti - 1])},
        })
    return {"updated": now_s, "updated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
            "zones": zones, "season_start": season_start.isoformat()}

def load_history():
    out = {}
    if HISTORY.exists():
        for f in HISTORY.glob("*.json"):
            try:
                out[dt.date.fromisoformat(f.stem)] = json.loads(f.read_text())
            except Exception:
                pass
    return out

def save_history(data):
    """One file per complete day, keyed by zone. Written once, never rewritten."""
    HISTORY.mkdir(parents=True, exist_ok=True)
    day = data["zones"][0]["yesterday"]["date"]
    f = HISTORY / f"{day}.json"
    if f.exists():
        return None
    f.write_text(json.dumps({z["slug"]: z["yesterday"] for z in data["zones"]}, indent=1) + "\n")
    return f

# ---------------------------------------------------------------- charts (SVG)

class Frame:
    """Plot area for one chart size. Text stays legible because each size gets its own viewBox."""
    def __init__(self, w, h, pl=40, pr=14, pt=20, pb=30):
        self.w, self.h, self.pl, self.pr, self.pt, self.pb = w, h, pl, pr, pt, pb
        self.iw, self.ih = w - pl - pr, h - pt - pb

    def y(self, v, lo, hi):
        return self.h - self.pb - self.ih * (v - lo) / (hi - lo)

def nice_scale(lo, hi, ticks=4):
    span = max(hi - lo, 1e-9)
    raw = span / ticks
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        step = m * mag
        if step >= raw:
            break
    lo2 = math.floor(lo / step) * step
    hi2 = math.ceil(hi / step) * step
    n = max(1, round((hi2 - lo2) / step))
    return lo2, hi2, n, step

def x_axis(f, n, labels, every, split=None):
    cw = f.iw / n
    out = []
    for i, lab in enumerate(labels):
        if i % every == 0:
            x = f.pl + cw * (i + 0.5)
            out.append(f'<text class="ax" x="{x:.1f}" y="{f.h - 10}" text-anchor="middle">{esc(lab)}</text>')
    if split is not None:
        x = f.pl + cw * split
        out.append(f'<line class="split" x1="{x:.1f}" x2="{x:.1f}" y1="{f.pt - 6}" y2="{f.h - f.pb}"/>'
                   f'<text class="ax now" x="{x + 5:.1f}" y="{f.pt - 6}">Today</text>')
    return "".join(out)

def y_grid(f, lo, hi, n, fmt):
    out = []
    for k in range(n + 1):
        v = lo + (hi - lo) * k / n
        y = f.y(v, lo, hi)
        out.append(f'<line class="grid" x1="{f.pl}" x2="{f.w - f.pr}" y1="{y:.1f}" y2="{y:.1f}"/>'
                   f'<text class="ax" x="{f.pl - 7}" y="{y + 3.5:.1f}" text-anchor="end">{fmt(v)}</text>')
    return "".join(out)

def hover_cols(f, n, tips):
    cw = f.iw / n
    return "".join(f'<rect class="hit" x="{f.pl + cw * i:.1f}" y="{f.pt}" width="{cw:.1f}" height="{f.ih}"><title>{esc(tip)}</title></rect>'
                   for i, tip in enumerate(tips) if tip)

def svg(f, body, label, cls=""):
    return (f'<svg class="{cls}" viewBox="0 0 {f.w} {f.h}" role="img" aria-label="{esc(label)}">{body}</svg>')

def snow_svg(z, f, every, cls):
    rows = z["past"] + z["days"]
    vals = [r["snow"] or 0 for r in rows]
    n, split = len(rows), len(z["past"])
    lo, hi, nt, _ = nice_scale(0, max(max(vals), 4), 4)
    labels = [dt.date.fromisoformat(r["date"]).strftime("%-d %b") if i % every == 0 else "" for i, r in enumerate(rows)]
    cw = f.iw / n
    bars = []
    for i, v in enumerate(vals):
        if v <= 0:
            continue
        y = f.y(v, lo, hi)
        bh = f.h - f.pb - y
        x = f.pl + cw * i + 1
        bw = max(2, cw - 2)
        r = min(4, bh, bw / 2)
        cls_ = "bar" if i < split else "bar fc"
        bars.append(f'<path class="{cls_}" d="M{x:.1f},{f.h - f.pb} V{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} '
                    f'H{x + bw - r:.1f} Q{x + bw:.1f},{y:.1f} {x + bw:.1f},{y + r:.1f} V{f.h - f.pb} Z"/>')
        if v >= 1:
            bars.append(f'<text class="val" x="{x + bw / 2:.1f}" y="{y - 5:.1f}" text-anchor="middle">{v:.0f}</text>')
    tips = [f'{dt.date.fromisoformat(r["date"]).strftime("%a %-d %b")}: {r["snow"] or 0:.1f} cm new snow at {z["base"]["name"]}'
            + (" (forecast)" if i >= split else "") for i, r in enumerate(rows)]
    body = (y_grid(f, lo, hi, nt, lambda v: f"{v:.0f}") + "".join(bars) + x_axis(f, n, labels, 1, split) + hover_cols(f, n, tips)
            + f'<text class="ax unit" x="{f.pl - 7}" y="{f.pt - 8}" text-anchor="end">cm</text>')
    return svg(f, body, f"Daily new snow at {z['base']['name']}, last 14 days and next 10", cls)

def chart_snow(z):
    wide = snow_svg(z, Frame(1100, 250, pl=44), 2, "wide")
    narrow = snow_svg(z, Frame(360, 230, pl=34, pr=8), 6, "narrow")
    legend = ('<figcaption class="legend"><span><i class="sw bar"></i>Last 14 days</span>'
              '<span><i class="sw bar fc"></i>Forecast</span></figcaption>')
    return f'<figure class="chart">{wide}{narrow}{legend}</figure>'

def line_chart(series, labels, lo, hi, nt, fmt, refs, label, tips, unit):
    f = Frame(360, 220, pl=42, pr=10, pt=22)
    n = len(labels)
    cw = f.iw / n
    body = y_grid(f, lo, hi, nt, fmt)
    for ref_v, ref_label in refs:
        if lo <= ref_v <= hi:
            y = f.y(ref_v, lo, hi)
            body += (f'<line class="ref" x1="{f.pl}" x2="{f.w - f.pr}" y1="{y:.1f}" y2="{y:.1f}"/>'
                     f'<text class="ax ref-l" x="{f.w - f.pr - 2}" y="{y - 5:.1f}" text-anchor="end">{esc(ref_label)}</text>')
    legend = '<figcaption class="legend">'
    for s_ in series:
        pts = [(f.pl + cw * (i + 0.5), f.y(v, lo, hi)) for i, v in enumerate(s_["values"]) if v is not None]
        if not pts:
            continue
        d = " ".join(("M" if k == 0 else "L") + f"{x:.1f},{y:.1f}" for k, (x, y) in enumerate(pts))
        body += f'<path class="ln" d="{d}" stroke="{s_["color"]}"/>'
        x, y = pts[0]
        body += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{s_["color"]}" stroke="var(--surface)" stroke-width="2"/>'
        legend += f'<span><i class="sw" style="background:{s_["color"]}"></i>{esc(s_["name"])}</span>'
    legend += "</figcaption>"
    body += x_axis(f, n, labels, 2) + hover_cols(f, n, tips)
    body += f'<text class="ax unit" x="{f.pl - 7}" y="{f.pt - 9}" text-anchor="end">{unit}</text>'
    return f'<figure class="chart">{svg(f, body, label)}{legend if len(series) > 1 else ""}</figure>'

def chart_temps(z):
    days = z["days"]
    labels = [dt.date.fromisoformat(d["date"]).strftime("%a") for d in days]
    vals = [v for d in days for v in (d["base_max"], d["top_min"]) if v is not None] + [0]
    lo, hi, nt, _ = nice_scale(min(vals), max(vals), 4)
    series = [{"name": f"Daytime high, {z['base']['name']}", "color": "#e76624", "values": [d["base_max"] for d in days]},
              {"name": f"Overnight low, {z['top']['name']}", "color": "#00a888", "values": [d["top_min"] for d in days]}]
    tips = [f'{dt.date.fromisoformat(d["date"]).strftime("%a %-d %b")}: {z["base"]["name"]} {d["base_min"]:.0f} to {d["base_max"]:.0f}°C; '
            f'{z["top"]["name"]} {d["top_min"]:.0f} to {d["top_max"]:.0f}°C' for d in days]
    return line_chart(series, labels, lo, hi, nt, lambda v: f"{v:.0f}°".replace("-", "−"), [(0, "0°C")],
                      f"Daily temperatures at {z['base']['name']} and {z['top']['name']}, next 10 days", tips, "°C")

def chart_freezing(z):
    days = z["days"]
    labels = [dt.date.fromisoformat(d["date"]).strftime("%a") for d in days]
    vals = [d["freezing"] for d in days if d["freezing"] is not None] + [z["base"]["elev"], z["top"]["elev"]]
    lo, hi, nt, _ = nice_scale(min(vals) - 200, max(vals) + 200, 4)
    series = [{"name": "Freezing level", "color": "#cfe3ff", "values": [d["freezing"] for d in days]}]
    tips = [f'{dt.date.fromisoformat(d["date"]).strftime("%a %-d %b")}: freezing level about {d["freezing"]:,.0f} m' if d["freezing"] else "" for d in days]
    refs = [(z["base"]["elev"], f'{z["base"]["name"]}'), (z["top"]["elev"], f'{z["top"]["name"]}')]
    return line_chart(series, labels, lo, hi, nt, lambda v: f"{v / 1000:.1f}k", refs,
                      "Average daily freezing level, next 10 days", tips, "m")

def chart_wind(z):
    days = z["days"]
    labels = [dt.date.fromisoformat(d["date"]).strftime("%a") for d in days]
    vals = [d["summit_wind"] for d in days if d["summit_wind"] is not None] or [50]
    lo, hi, nt, _ = nice_scale(0, max(vals), 4)
    level = z["now"]["summit_level"]
    series = [{"name": f"Wind at {level} hPa", "color": "#d28e05", "values": [d["summit_wind"] for d in days]}]
    tips = [f'{dt.date.fromisoformat(d["date"]).strftime("%a %-d %b")}: up to {d["summit_wind"]:.0f} km/h near summit height' if d["summit_wind"] is not None else "" for d in days]
    return line_chart(series, labels, lo, hi, nt, lambda v: f"{v:.0f}", [],
                      "Maximum daily wind near summit height, next 10 days", tips, "km/h")

def sparkline(z):
    rows = z["past"][-7:] + z["days"][:7]
    vals = [r["snow"] or 0 for r in rows]
    hi = max(5, max(vals))
    w, h, n = 300, 34, len(rows)
    cw = w / n
    out = []
    for i, v in enumerate(vals):
        bh = max(1.5, h * v / hi) if v > 0 else 1.5
        cls = "sp" if i < 7 else "sp fc"
        out.append(f'<rect class="{cls}{" zero" if v <= 0 else ""}" x="{i * cw + 1:.1f}" y="{h - bh:.1f}" width="{cw - 2:.1f}" height="{bh:.1f}" rx="1.5"/>')
    out.append(f'<line class="sp-split" x1="{7 * cw:.1f}" x2="{7 * cw:.1f}" y1="0" y2="{h}"/>')
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" role="img" aria-label="New snow, last 7 days and next 7">'
            + "".join(out) + "</svg>")

# ---------------------------------------------------------------- map

LABELS = {  # map label offsets: dx, dy, anchor
    "putha-hiunchuli": (-13, 4, "end"), "thorong-la": (-6, -14, "end"), "himlung-himal": (13, 0, "start"),
    "annapurna-sanctuary": (-13, 16, "end"), "langtang": (-13, -6, "end"), "kalinchowk": (0, 26, "middle"),
    "island-peak": (10, -12, "start"), "mera-peak": (13, 14, "start"),
}

LABELS_NARROW = {
    "putha-hiunchuli": (0, 30, "middle"), "thorong-la": (0, -18, "middle"), "himlung-himal": (14, 7, "start"),
    "annapurna-sanctuary": (0, 42, "middle"), "langtang": (14, 7, "start"), "kalinchowk": (0, 34, "middle"),
    "island-peak": (14, -6, "start"), "mera-peak": (14, 18, "start"),
}

def map_svg(zones, rel):
    lon0, lon1, lat0, lat1 = 79.9, 88.3, 26.2, 30.6
    k = 100
    sx = math.cos(math.radians(28.3))
    w = (lon1 - lon0) * k * sx
    h = (lat1 - lat0) * k

    def p(lon, lat):
        return ((lon - lon0) * k * sx, (lat1 - lat) * k)
    d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in (p(a, b) for a, b in OUTLINE)) + " Z"

    def marks(labels):
        out = []
        for z in zones:
            x, y = p(z["lon"], z["lat"])
            label, colour = OUTLOOK[z["outlook"]]
            dx, dy, anchor = labels.get(z["slug"], (12, 4, "start"))
            out.append(
                f'<a href="{rel}{z["slug"]}/" class="mk"><title>{esc(z["name"])}: {label}</title>'
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="11" fill="{colour}" opacity=".22"/>'
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5.5" fill="{colour}" stroke="var(--surface)" stroke-width="2"/>'
                f'<text x="{x + dx:.1f}" y="{y + dy:.1f}" text-anchor="{anchor}">{esc(z["name"])}</text></a>')
        return "".join(out)
    cities = [("Kathmandu", 85.324, 27.717, -6, -6, "end"), ("Pokhara", 83.986, 28.209, 8, 4, "start")]
    city = "".join(f'<circle cx="{p(lo, la)[0]:.1f}" cy="{p(lo, la)[1]:.1f}" r="2.5" class="city"/>'
                   f'<text class="city-l" x="{p(lo, la)[0] + dx:.1f}" y="{p(lo, la)[1] + dy:.1f}" text-anchor="{an}">{n}</text>'
                   for n, lo, la, dx, dy, an in cities)
    x0, y0 = p(82.05, 29.3)
    x1, y1 = p(88.5, 27.2)
    return (f'<svg class="nmap wide" viewBox="0 0 {w:.0f} {h:.0f}" role="img" aria-label="Map of Nepal showing ski zones">'
            f'<path class="np" d="{d}"/>{city}{marks(LABELS)}</svg>'
            f'<svg class="nmap narrow" viewBox="{x0:.0f} {y0:.0f} {x1 - x0:.0f} {y1 - y0:.0f}" role="img" aria-label="Map of Nepal showing ski zones">'
            f'<path class="np" d="{d}"/>{city}{marks(LABELS_NARROW)}</svg>')

# ---------------------------------------------------------------- page parts

def page(title, desc, path, body, rel, schema=None):
    url = f"{SITE_URL}/{path}"
    robots = "index,follow,max-image-preview:large" if ALLOW_INDEXING else "noindex,follow"
    ld = f'<script type="application/ld+json">{json.dumps(schema, ensure_ascii=False)}</script>' if schema else ""
    return f"""<!DOCTYPE html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<meta name="robots" content="{robots}">
<link rel="canonical" href="{esc(url)}">
<meta name="theme-color" content="#0b1220">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{SITE_NAME}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{esc(url)}">
<meta name="twitter:card" content="summary">
<link rel="icon" href="{rel}assets/favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{rel}assets/style.css">
{ld}
</head>
<body>
<header class="top">
  <a class="brand" href="{rel}"><svg viewBox="0 0 32 32" aria-hidden="true"><path d="M3 25 13 9l5 8 3-4 8 12z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M11 12.2 13 9l2.1 3.4-1.1.9-1-.8z" fill="currentColor"/></svg><span>Nepal Ski <b>Conditions</b></span></a>
  <nav><a href="{rel}#zones">Zones</a><a href="{rel}about/">How it works</a></nav>
  <div class="units" role="group" aria-label="Units"><button type="button" data-units="metric" aria-pressed="true">°C</button><button type="button" data-units="imperial" aria-pressed="false">°F</button></div>
</header>
<main>
{body}
</main>
<footer class="foot">
  <div class="foot-in">
    <p class="fb"><b>Nepal Ski Conditions</b> is a free tool for skiers heading to Nepal, built and sponsored by <a href="{SPONSOR['sponsor']['url']}?{UTM}_footer" rel="sponsored noopener">King of the Hill</a>, guided ski expeditions in Nepal.</p>
    <p>Weather data: <a href="https://open-meteo.com/" rel="noopener">Open-Meteo.com</a> (CC BY 4.0), from national weather service models. Figures are model forecasts for the stated elevations, not observations, and are processed into daily and three-hourly summaries. Not an avalanche forecast.</p>
    <p><a href="{rel}about/">How it works</a> · <a href="{rel}data/conditions.json">Open data (JSON)</a> · <a href="https://github.com/Kingofthehillappjester/nepal-ski-conditions" rel="noopener">Source</a></p>
  </div>
</footer>
<script src="{rel}assets/app.js" defer></script>
</body>
</html>
"""

def outlook_chip(z):
    label, colour = OUTLOOK[z["outlook"]]
    if z["outlook"] == "fresh" and z["snowing_now"]:
        label = "Snowing now"
    ic = {"fresh": "snow", "coming": "snow", "wind": "fog", "settled": "clear"}[z["outlook"]]
    return f'<span class="chip" style="--c:{colour}">{icon(ic, "ci")}{esc(label)}</span>'

def trip_card(trip, zone_slug=""):
    url = f'{trip["url"]}?{UTM}_{zone_slug or "home"}'
    return (f'<a class="trip" href="{esc(url)}" rel="sponsored noopener" target="_blank">'
            f'<img src="{esc(trip["image"])}" alt="" loading="lazy" decoding="async">'
            f'<div><span class="tag">Sponsored · King of the Hill</span><b>{esc(trip["name"])}</b>'
            f'<span class="meta">{esc(trip["meta"])}</span><p>{esc(trip["blurb"])}</p><span class="go">See the trip →</span></div></a>')

def sponsored(zone=None):
    keys = [t["key"] for t in SPONSOR["trips"]]
    if zone and zone.get("trip") in TRIPS:
        keys.remove(zone["trip"])
        keys.insert(0, zone["trip"])
    keys = keys[:3]
    cards = "".join(trip_card(TRIPS[k], zone["slug"] if zone else "") for k in keys)
    return f"""<section class="sec sponsored" aria-labelledby="sp-h">
  <div class="sec-head"><p class="eyebrow">Sponsored</p><h2 id="sp-h">Ski Nepal with a guide</h2>
  <p class="muted">These trips are run by King of the Hill, who build and pay for this site. Every trip is led by licensed Nepali guides from HST Adventures.</p></div>
  <div class="trips">{cards}</div>
</section>"""

def kit_tips(zones):
    """Packing notes driven by this week's numbers."""
    tips = []
    lows = [(d["top_min"], z) for z in zones for d in z["days"][:7] if d["top_min"] is not None]
    cmin, cz = min(lows, key=lambda x: x[0]) if lows else (None, None)
    low = str(round(cmin)).replace("-", "−") if cmin is not None else ""
    if cmin is not None and cmin <= -20:
        tips.append(("Expedition down and mitts", f'Lows reach {low}°C at {cz["top"]["name"]} this week. Pack a down jacket rated well below that, down mitts and a liner-glove system.'))
    elif cmin is not None:
        tips.append(("A proper down jacket", f'The coldest summit low this week is about {low}°C. Bring an insulated jacket and warm gloves for the evenings at camp.'))
    fresh = [z for z in zones if z["snow"]["past72"] >= 10 or z["snow"]["next72"] >= 10]
    if fresh:
        names = ", ".join(z["name"] for z in fresh[:3])
        tips.append(("Avalanche kit, and the training to use it", f"New snow at {names} this week. Carry a transceiver, shovel and probe, travel with a guide and check local advice before skiing steep slopes."))
    windy = [z for z in zones if (z["summit_48"] or 0) >= 70]
    if windy:
        top = max(windy, key=lambda z: z["summit_48"])
        tips.append(("Wind-proof everything", f'Winds near summit height reach {top["summit_48"]:.0f} km/h at {top["name"]} in the next 48 hours. A hard shell, face protection and goggles matter more than usual.'))
    tips.append(("Category 4 glacier glasses", "Snow glare above 4,000m is fierce, even on cloudy days. Bring glacier glasses and goggles, and SPF 50 for your face and lips."))
    tips.append(("Insulated water bottles", "Bottles freeze overnight at high camps. Use insulated covers and keep a bottle in your sleeping bag."))
    return tips[:4]

def kit_section(zones):
    items = "".join(f'<li><b>{esc(h)}</b><span>{esc(p)}</span></li>' for h, p in kit_tips(zones))
    return f"""<section class="sec kit" aria-labelledby="kit-h">
  <div class="sec-head"><p class="eyebrow">Gear</p><h2 id="kit-h">What to pack for this week's conditions</h2>
  <p class="muted">Updated with the forecast. For the full list, see the <a href="{esc(SPONSOR['kit_list_url'])}?{UTM}_kit" rel="sponsored noopener">Nepal ski touring kit list</a> from King of the Hill.</p></div>
  <ul class="kit-list">{items}</ul>
</section>"""

# ---------------------------------------------------------------- pages

def zone_card(z, rel):
    n = z["now"]
    label, ic = wmo(n["code"], n["is_day"])
    s = z["snow"]
    return f"""<a class="zc" href="{rel}{z['slug']}/">
  <div class="zc-top"><div><h3>{esc(z['name'])}</h3><p class="muted">{esc(z['region'])} · {z['top']['elev']:,}m</p></div>{outlook_chip(z)}</div>
  <div class="zc-now">{icon(ic, 'wx big', label)}<div><span class="big-t">{u('t', n['base_t'])}</span><span class="muted sm">at {esc(z['base']['name'])} {z['base']['elev']:,}m</span></div>
  <div class="zc-top-t"><span class="muted sm">Top</span>{u('t', n['top_t'])}</div></div>
  <dl class="zc-stats">
    <div><dt>Snow 24h</dt><dd>{u('s', s['past24'])}</dd></div>
    <div><dt>Snow 7d</dt><dd>{u('s', s['past7'])}</dd></div>
    <div><dt>Next 72h</dt><dd>{u('s', s['next72'])}</dd></div>
    <div><dt>Freezing</dt><dd>{u('e', n['freezing'])}</dd></div>
  </dl>
  <div class="zc-spark">{sparkline(z)}<div class="sp-cap"><span>Snow, last 7 days</span><span>Next 7</span></div></div>
</a>"""

def fmt_time(s):
    d = t(s)
    return d.strftime("%-d %b, %H:%M")

def snow_tile(k, z, v, none_text):
    if v < 0.5:
        return f'<div class="tile"><span class="k">{k}</span><span class="v">Dry</span><span class="n">{none_text}</span></div>'
    return f'<a class="tile" href="{z["slug"]}/"><span class="k">{k}</span><span class="v">{u("s", v)}</span><span class="n">{esc(z["name"])}</span></a>'

def render_home(data):
    zones = data["zones"]
    rel = ""
    most7 = max(zones, key=lambda z: z["snow"]["past7"])
    coming = max(zones, key=lambda z: z["snow"]["next7"])
    coldest = min(zones, key=lambda z: z["tonight_top_min"] if z["tonight_top_min"] is not None else 99)
    fls = [z["now"]["freezing"] for z in zones if z["now"]["freezing"] is not None]
    legend = "".join(f'<span><i style="background:{c}"></i>{esc(l)}</span>' for l, c in OUTLOOK.values())
    cards = "".join(zone_card(z, rel) for z in zones)
    body = f"""
<section class="hero">
  <p class="eyebrow live"><span class="dot"></span>Updated <time datetime="{data['updated']}:00+05:45" data-ago>{fmt_time(data['updated'])} Nepal time</time></p>
  <h1>Snow and weather for Nepal's <em>ski zones</em></h1>
  <p class="lede">Live forecasts for {len(zones)} places you can ski in Nepal, from the beginner slope at Kalinchowk to 7,000m peaks. New snow, freezing level, summit winds and a 10-day outlook, updated every three hours.</p>
  <div class="tiles">
    {snow_tile("Most snow, last 7 days", most7, most7["snow"]["past7"], "No new snow in any zone")}
    {snow_tile("Most snow, next 7 days", coming, coming["snow"]["next7"], "None forecast in any zone")}
    <a class="tile" href="{coldest['slug']}/"><span class="k">Coldest summit low today</span><span class="v">{u('t', coldest['tonight_top_min'])}</span><span class="n">{esc(coldest['top']['name'])}</span></a>
    <div class="tile"><span class="k">Freezing level now</span><span class="v">{u('e', min(fls))}<i>to</i>{u('e', max(fls))}</span><span class="n">across all zones</span></div>
  </div>
</section>
<section class="sec map-sec" aria-labelledby="map-h">
  <div class="map-card">
    <div class="sec-head"><h2 id="map-h">Where the snow is</h2><p class="muted">Tap a zone for its full forecast.</p></div>
    {map_svg(zones, rel)}
    <div class="map-legend">{legend}</div>
  </div>
</section>
<section class="sec" id="zones" aria-labelledby="z-h">
  <div class="sec-head"><h2 id="z-h">All zones</h2><p class="muted">Temperatures now. Snow figures are model totals at each zone's lower elevation.</p></div>
  <div class="zgrid">{cards}</div>
</section>
{kit_section(zones)}
{sponsored()}
<section class="sec note"><p class="muted">Mountain weather in Nepal changes fast, and forecast models struggle with high, steep terrain. Use this as a guide to the big picture, not a safety tool. Always check conditions with local guides and Nepal's <a href="https://www.dhm.gov.np/" rel="noopener">Department of Hydrology and Meteorology</a> before you go.</p></section>
"""
    schema = {"@context": "https://schema.org", "@type": "WebSite", "name": SITE_NAME, "url": SITE_URL + "/",
              "description": "Live snow and weather forecasts for Nepal's ski zones.",
              "publisher": {"@type": "Organization", "name": "King of the Hill", "url": SPONSOR["sponsor"]["url"]}}
    return page("Nepal Ski Conditions: live snow and weather for Nepal's ski zones",
                "Live snow and weather for Nepal's ski zones: Annapurna, Thorong La, Langtang, Mera Peak, Island Peak, Himlung, Putha Hiunchuli and Kalinchowk. New snow, freezing level, summit winds and a 10-day forecast.",
                "", body, rel, schema)

def render_zone(z, data):
    rel = "../"
    n, s = z["now"], z["snow"]
    label, ic = wmo(n["code"], n["is_day"])
    level_h = "about 7,200m" if n["summit_level"] == "400" else "about 5,600m"
    best = ""
    if z["best_day"]:
        b = z["best_day"]
        bd = dt.date.fromisoformat(b["date"])
        best = (f'<p class="best">{icon("clear", "ci")}<span><b>Looks best: {bd.strftime("%A %-d %b")}.</b> '
                f'Lightest wind and clearest sky in the next week (gusts to {b["gust"]:.0f} km/h, {b["cloud"]:.0f}% cloud by day).</span></p>')
    days = "".join(
        f'<li><span class="d">{dt.date.fromisoformat(d["date"]).strftime("%a")}<small>{dt.date.fromisoformat(d["date"]).strftime("%-d %b")}</small></span>'
        f'{icon(wmo(d["code"])[1], "wx", wmo(d["code"])[0])}'
        f'<span class="hl">{u("t", d["base_max"])}<i>/</i>{u("t", d["base_min"])}</span>'
        f'<span class="sn">{u("s", d["snow"]) if (d["snow"] or 0) > 0 else "<span class=na>–</span>"}</span>'
        f'<span class="gw">{u("w", d["gust"])}</span></li>' for d in z["days"])
    rows = "".join(
        f'<tr><th scope="row">{t(h["time"]).strftime("%a %H:%M")}</th><td>{icon(wmo(h["code"], h["is_day"])[1], "wx sm", wmo(h["code"], h["is_day"])[0])}</td>'
        f'<td>{u("t", h["base_t"])}</td><td>{u("t", h["top_t"])}</td><td>{u("s", h["snow"]) if h["snow"] > 0 else "<span class=na>–</span>"}</td>'
        f'<td>{u("w", h["gust"])}</td><td>{u("e", h["freezing"])}</td><td>{u("w", h["summit_wind"])}</td></tr>' for h in z["hours"])
    season_lbl = "Season so far" + ("" if s["season_from"] <= data["season_start"] else f' (since {dt.date.fromisoformat(s["season_from"]).strftime("%-d %b")})')
    others = "".join(f'<a href="../{o["slug"]}/">{esc(o["name"])}{outlook_chip(o)}</a>' for o in data["zones"] if o["slug"] != z["slug"])
    body = f"""
<nav class="crumbs"><a href="../">All zones</a><span>/</span>{esc(z['name'])}</nav>
<section class="zhero">
  <div>
    <p class="eyebrow live"><span class="dot"></span>Updated <time datetime="{data['updated']}:00+05:45" data-ago>{fmt_time(data['updated'])} Nepal time</time></p>
    <h1>{esc(z['name'])} <em>snow and weather</em></h1>
    <p class="lede">{esc(z['region'])} · {esc(z['base']['name'])} {z['base']['elev']:,}m · {esc(z['top']['name'])} {z['top']['elev']:,}m</p>
    <div class="zh-chips">{outlook_chip(z)}<span class="chip plain">{esc(z['level'])}</span></div>
    {best}
  </div>
  <div class="now-card">
    <div class="now-main">{icon(ic, 'wx huge', label)}<div><span class="huge-t">{u('t', n['base_t'])}</span><span class="muted">{esc(label)} at {esc(z['base']['name'])}</span></div></div>
    <dl class="now-grid">
      <div><dt>{esc(z['top']['name'])}</dt><dd>{u('t', n['top_t'])}</dd></div>
      <div><dt>Freezing level</dt><dd>{u('e', n['freezing'])}</dd></div>
      <div><dt>Gusts at {esc(z['base']['name'])}</dt><dd>{u('w', n['gust'])}</dd></div>
      <div><dt>Wind near summit height</dt><dd>{u('w', n['summit_wind'])}</dd></div>
    </dl>
  </div>
</section>
<section class="sec">
  <div class="sec-head"><h2>New snow</h2><p class="muted">Model totals at {esc(z['base']['name'])} ({z['base']['elev']:,}m). Higher up, at {esc(z['top']['name'])}, the model has {u('s', s['top_past7'])} over the last 7 days and {u('s', s['top_next7'])} in the next 7.</p></div>
  <dl class="snow-row">
    <div><dt>Last 24h</dt><dd>{u('s', s['past24'])}</dd></div>
    <div><dt>Last 72h</dt><dd>{u('s', s['past72'])}</dd></div>
    <div><dt>Last 7 days</dt><dd>{u('s', s['past7'])}</dd></div>
    <div><dt>Last 30 days</dt><dd>{u('s', s['past30'])}</dd></div>
    <div><dt>{esc(season_lbl)}</dt><dd>{u('s', s['season'])}</dd></div>
    <div class="fut"><dt>Next 24h</dt><dd>{u('s', s['next24'])}</dd></div>
    <div class="fut"><dt>Next 72h</dt><dd>{u('s', s['next72'])}</dd></div>
    <div class="fut"><dt>Next 7 days</dt><dd>{u('s', s['next7'])}</dd></div>
  </dl>
  {chart_snow(z)}
</section>
<section class="sec">
  <div class="sec-head"><h2>Next 10 days</h2><p class="muted">Highs and lows at {esc(z['base']['name'])}, new snow and maximum gusts.</p></div>
  <ol class="days">{days}</ol>
  <div class="charts2">
    <div><h3>Temperature</h3>{chart_temps(z)}</div>
    <div><h3>Freezing level</h3>{chart_freezing(z)}</div>
    <div><h3>Wind near summit height</h3><p class="muted xs">Model wind at {n['summit_level']} hPa, {level_h}. Ridge and summit winds can be much stronger than in the valleys.</p>{chart_wind(z)}</div>
  </div>
</section>
<section class="sec">
  <div class="sec-head"><h2>Next 72 hours</h2><p class="muted">Every three hours, Nepal time. Snow is the total for the preceding three hours.</p></div>
  <div class="tbl"><table class="hours"><thead><tr><th scope="col">Time</th><th scope="col"><span class="sr">Weather</span></th><th scope="col">{esc(z['base']['name'])}</th><th scope="col">{esc(z['top']['name'])}</th><th scope="col">Snow</th><th scope="col">Gusts</th><th scope="col">Freezing level</th><th scope="col">Summit wind</th></tr></thead><tbody>{rows}</tbody></table></div>
</section>
<section class="sec about-zone">
  <div class="sec-head"><h2>About {esc(z['name'])}</h2></div>
  <p>{esc(z['about'])}</p>
  <p class="muted"><b>Best season:</b> {esc(z['season'])}.</p>
  <p><a class="more" href="{esc(z['guide'][1])}?{UTM}_{z['slug']}_guide" rel="noopener">{esc(z['guide'][0])} →</a> <span class="muted xs">from King of the Hill</span></p>
</section>
{kit_section([z])}
{sponsored(z)}
<section class="sec others"><div class="sec-head"><h2>Other zones</h2></div><div class="other-list">{others}</div></section>
<section class="sec note"><p class="muted">Model forecasts for the stated elevations, not observations. Not an avalanche forecast. Check conditions with local guides and Nepal's <a href="https://www.dhm.gov.np/" rel="noopener">Department of Hydrology and Meteorology</a>.</p></section>
"""
    title = f"{z['name']} snow and weather forecast | {SITE_NAME}"
    desc = (f"Live snow and weather for {z['name']}, Nepal: new snow, freezing level, summit winds and a 10-day forecast "
            f"for {z['base']['name']} ({z['base']['elev']:,}m) and {z['top']['name']} ({z['top']['elev']:,}m). Updated every 3 hours.")
    schema = {"@context": "https://schema.org", "@type": "WebPage", "name": title, "description": desc,
              "url": f"{SITE_URL}/{z['slug']}/", "dateModified": data["updated_utc"],
              "about": {"@type": "Place", "name": z["name"], "geo": {"@type": "GeoCoordinates", "latitude": z["lat"], "longitude": z["lon"], "elevation": z["top"]["elev"]},
                        "containedInPlace": {"@type": "Country", "name": "Nepal"}}}
    return page(title, desc, f"{z['slug']}/", body, rel, schema)

def render_about(data):
    rel = "../"
    zl = "".join(f'<li><b>{esc(z["name"])}</b>: {esc(z["base"]["name"])} {z["base"]["elev"]:,}m and {esc(z["top"]["name"])} {z["top"]["elev"]:,}m</li>' for z in data["zones"])
    body = f"""
<nav class="crumbs"><a href="../">All zones</a><span>/</span>How it works</nav>
<section class="prose">
  <h1>How it works</h1>
  <p>Nepal has no network of mountain weather stations or snow reports like the Alps. So this site does the next best thing: every three hours it asks global weather models for a forecast at two heights in each ski zone, the place you sleep and the place you ski to, and turns the numbers into something you can read at a glance.</p>
  <h2>Where the data comes from</h2>
  <p>Forecasts come from <a href="https://open-meteo.com/" rel="noopener">Open-Meteo</a>, which combines models from national weather services, including ECMWF and NOAA's GFS, and adjusts temperature to the exact elevation we ask for. The data is licensed under <a href="https://creativecommons.org/licenses/by/4.0/" rel="noopener">CC BY 4.0</a>. We summarise it into daily and three-hourly figures; we don't change the underlying values.</p>
  <h2>The zones</h2>
  <ul>{zl}</ul>
  <h2>What the numbers mean</h2>
  <ul>
    <li><b>New snow</b> is the model's snowfall at the zone's lower elevation. Models smooth out mountains, so real totals on high slopes can be much bigger or smaller.</li>
    <li><b>Freezing level</b> is the height where the air is at 0°C. Above it, precipitation falls as snow.</li>
    <li><b>Wind near summit height</b> is the model wind at a standard pressure level: 500 hPa (about 5,600m) or 400 hPa (about 7,200m), whichever is closer to the summit.</li>
    <li><b>Outlook</b>: <i>Fresh snow</i> means at least 10cm in the last 72 hours (or 5cm in 24 hours, or snowing now). <i>Snow on the way</i> means at least 10cm forecast in the next 72 hours. <i>Strong winds up high</i> means summit-height winds of 70 km/h or more in the next 48 hours. Otherwise <i>Settled</i>.</li>
    <li><b>Looks best</b> picks the day in the next week with the lightest gusts and clearest daytime sky, and no heavy snow. It's a pointer, not a promise.</li>
  </ul>
  <h2>What it isn't</h2>
  <p>This is not an avalanche forecast and it is not a safety tool. Weather in the Himalaya changes fast, and models struggle with steep, high terrain. Always check with local guides and Nepal's <a href="https://www.dhm.gov.np/" rel="noopener">Department of Hydrology and Meteorology</a> before you go.</p>
  <h2>Who built it</h2>
  <p>This site is built and paid for by <a href="{SPONSOR['sponsor']['url']}?{UTM}_about" rel="sponsored noopener">King of the Hill</a>, who run guided ski expeditions in Nepal. Their trips appear as clearly marked sponsored placements. The forecasts are the same whoever you ski with.</p>
  <h2>Open data</h2>
  <p>Everything on the site is available as <a href="../data/conditions.json">JSON</a>, and the code is <a href="https://github.com/Kingofthehillappjester/nepal-ski-conditions" rel="noopener">on GitHub</a>. A daily snapshot is kept in the repository, so the season's history builds up over time.</p>
</section>
"""
    return page(f"How it works | {SITE_NAME}", "How Nepal Ski Conditions builds its forecasts for Nepal's ski zones, what the numbers mean, and where the data comes from.", "about/", body, rel)

def render_404():
    home = SITE_URL + "/"
    body = f'<section class="prose"><h1>Page not found</h1><p><a href="{home}">See all ski zones →</a></p></section>'
    return page(f"Not found | {SITE_NAME}", "Page not found.", "404.html", body, home)

# ---------------------------------------------------------------- build

def build(raw):
    data = summarise(raw)
    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "data").mkdir(parents=True)
    shutil.copytree(ROOT / "assets", DIST / "assets")
    (DIST / "index.html").write_text(render_home(data))
    for z in data["zones"]:
        (DIST / z["slug"]).mkdir()
        (DIST / z["slug"] / "index.html").write_text(render_zone(z, data))
    (DIST / "about").mkdir()
    (DIST / "about" / "index.html").write_text(render_about(data))
    (DIST / "404.html").write_text(render_404())
    public = {"updated": data["updated"] + "+05:45", "source": "Open-Meteo.com (CC BY 4.0)", "site": SITE_URL,
              "zones": [{k: z[k] for k in ("slug", "name", "region", "lat", "lon", "base", "top", "now", "snow", "outlook", "days")} for z in data["zones"]]}
    (DIST / "data" / "conditions.json").write_text(json.dumps(public, ensure_ascii=False))
    urls = [""] + [f"{z['slug']}/" for z in data["zones"]] + ["about/"]
    lastmod = data["updated"][:10]
    (DIST / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                      + "".join(f"  <url><loc>{SITE_URL}/{p}</loc><lastmod>{lastmod}</lastmod><changefreq>hourly</changefreq></url>\n" for p in urls)
                                      + "</urlset>\n")
    (DIST / "robots.txt").write_text(("User-agent: *\nAllow: /\n" if ALLOW_INDEXING else "User-agent: *\nDisallow: /\n") + f"\nSitemap: {SITE_URL}/sitemap.xml\n")
    (DIST / "llms.txt").write_text(f"# {SITE_NAME}\n\n> Live snow and weather forecasts for Nepal's ski zones, from Open-Meteo models, updated every 3 hours. Built by King of the Hill (kingofthehill.co.uk).\n\n"
                                   + "".join(f"- [{z['name']}]({SITE_URL}/{z['slug']}/): {z['region']}, {z['base']['name']} {z['base']['elev']}m to {z['top']['name']} {z['top']['elev']}m.\n" for z in data["zones"])
                                   + f"\nMachine-readable data: {SITE_URL}/data/conditions.json\n")
    (DIST / ".nojekyll").write_text("")
    if CUSTOM_DOMAIN:
        (DIST / "CNAME").write_text(CUSTOM_DOMAIN + "\n")
    return data

def main():
    if "--raw" in sys.argv:
        raw = json.loads(pathlib.Path(sys.argv[sys.argv.index("--raw") + 1]).read_text())
    else:
        raw = fetch()
    data = build(raw)
    saved = save_history(data) if "--no-history" not in sys.argv else None
    z0 = data["zones"]
    print(f"Built {len(z0)} zones, data time {data['updated']} (Nepal).", "History:", saved or "unchanged")
    for z in z0:
        print(f"  {z['slug']:20s} {z['outlook']:8s} now {z['now']['base_t']}°/{z['now']['top_t']}°  7d {z['snow']['past7']}cm  next7 {z['snow']['next7']}cm  FL {z['now']['freezing']}m")

if __name__ == "__main__":
    main()
