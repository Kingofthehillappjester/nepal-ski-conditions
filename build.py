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
HOURLY_VARS = ("temperature_2m,apparent_temperature,snowfall,rain,precipitation,freezing_level_height,wind_speed_10m,wind_direction_10m,"
               "wind_gusts_10m,cloud_cover,weather_code,wind_speed_500hPa,wind_direction_500hPa,wind_speed_400hPa,wind_direction_400hPa")
CURRENT_VARS = "temperature_2m,weather_code,wind_speed_10m,wind_gusts_10m,snowfall,freezing_level_height,cloud_cover,is_day"

# Outlook categories. The three active states pass the dataviz validator on white (all pairs);
# "settled" is a deliberate neutral and is drawn hollow on the map, always with a text label.
OUTLOOK = {
    "fresh": ("Fresh snow", "#257de0"),
    "coming": ("Snow on the way", "#d03d7d"),
    "wind": ("Strong winds up high", "#b97a00"),
    "settled": ("Settled", "#7b8698"),
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


def nmin(vals):
    vals = [v for v in vals if v is not None]
    return min(vals) if vals else None

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

# Filled, coloured weather icons in the style of classic forecast tables.
_CLOUD = '<path d="M6.5 {y}h12a4 4 0 0 0 .4-8 6 6 0 0 0-11.6 1.6A3.3 3.3 0 0 0 6.5 {y}z" fill="{f}" stroke="{s}" stroke-width="1"/>'
ICON_PATHS = {
    "clear": ('<g stroke="#f2a900" stroke-width="2" stroke-linecap="round"><path d="M12 2.5v2.4M12 19.1v2.4M2.5 12h2.4M19.1 12h2.4M5.3 5.3l1.7 1.7M17 17l1.7 1.7M5.3 18.7 7 17M17 7l1.7-1.7"/></g>'
              '<circle cx="12" cy="12" r="4.8" fill="#ffc21a" stroke="#e09a00" stroke-width="1"/>'),
    "moon": '<path d="M18.5 15.2A7.6 7.6 0 0 1 9.3 4.4a8 8 0 1 0 9.2 10.8z" fill="#f4e6a6" stroke="#c4aa4c" stroke-width="1"/>',
    "partly": ('<g stroke="#f2a900" stroke-width="1.8" stroke-linecap="round"><path d="M9 1.8v1.7M1.8 9h1.7M3.9 3.9 5 5M14.1 3.9 13 5"/></g>'
               '<circle cx="9" cy="9" r="4" fill="#ffc21a" stroke="#e09a00" stroke-width="1"/>'
               '<path d="M8 20.5h10.5a3.6 3.6 0 0 0 .3-7.2 5 5 0 0 0-9.6 1.4A2.9 2.9 0 0 0 8 20.5z" fill="#e6eaef" stroke="#8792a1" stroke-width="1"/>'),
    "cloud": _CLOUD.format(y=19, f="#cdd4dd", s="#7a8697"),
    "fog": _CLOUD.format(y=13, f="#dfe3e9", s="#8792a1") + '<path d="M4 16.5h16M6 20h12" stroke="#8792a1" stroke-width="1.8" stroke-linecap="round"/>',
    "rain": _CLOUD.format(y=14, f="#b8c1cd", s="#6c7889") + '<path d="M8.5 16.8 7.5 19.5M12.5 16.8l-1 2.7M16.5 16.8l-1 2.7" stroke="#1f6fd1" stroke-width="1.8" stroke-linecap="round"/>',
    "snow": _CLOUD.format(y=14, f="#c3cbd6", s="#6c7889") + '<g fill="#1f6fd1"><circle cx="8" cy="17.6" r="1.4"/><circle cx="12" cy="17.6" r="1.4"/><circle cx="16" cy="17.6" r="1.4"/><circle cx="10" cy="21" r="1.4"/><circle cx="14" cy="21" r="1.4"/></g>',
    "storm": _CLOUD.format(y=14, f="#98a3b1", s="#5c6878") + '<path d="M12.8 15 10.3 19h3l-2 4" fill="none" stroke="#f2a900" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>',
}

def icon(name, cls="wi", title=None):
    t_ = f"<title>{esc(title)}</title>" if title else ""
    return (f'<svg class="{cls}" viewBox="0 0 24 24" role="img" aria-label="{esc(title or name)}">{t_}{ICON_PATHS[name]}</svg>')

# Unit-aware number. JS swaps between metric and imperial; metric is rendered server-side.
# bare=True drops the unit suffix (used in tables, where the row label carries the unit).
UNIT_LABEL = {"t": "°C", "s": "cm", "e": "m", "w": "km/h"}

def u(kind, v, bare=False):
    if v is None:
        return '<span class="na">–</span>'
    if kind == "t":
        txt = f"{round(v):d}".replace("-", "−") + ("" if bare else "°")
    elif kind == "s":
        txt = f"{v:.0f}" if v >= 10 or float(v).is_integer() else f"{v:.1f}"
        txt += "" if bare else "<small>cm</small>"
    elif kind == "e":
        txt = f"{v:.0f}" if bare else f"{v:,.0f}<small>m</small>"
    elif kind == "w":
        txt = f"{v:.0f}" + ("" if bare else "<small>km/h</small>")
    else:
        txt = str(v)
    b = ' data-b="1"' if bare else ""
    return f'<span class="u" data-k="{kind}" data-v="{v}"{b}>{txt}</span>'

def ul(kind):
    return f'<span class="ul" data-k="{kind}">{UNIT_LABEL[kind]}</span>'

COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
ARROWS = ["↓", "↙", "←", "↖", "↑", "↗", "→", "↘"]  # indexed by where the wind comes FROM; arrow shows where it blows

def wind_dir(deg):
    if deg is None:
        return "", ""
    k = int((deg % 360) / 45 + 0.5) % 8
    return ARROWS[k], COMPASS[k]

# Cell colours. Snow: one-hue blue ramp. Temperature: blue/red diverging around 0°C with a grey
# midpoint. Wind: one-hue orange ramp from 40 km/h. Text colour is picked for contrast.
SNOW_STEPS = ((1, "#cce3fd"), (3, "#9dc8f7"), (6, "#6aabf1"), (10, "#338ced"), (20, "#2370cd"), (math.inf, "#0f4a96"))
TEMP_STEPS = ((-25, "#0f4a96"), (-15, "#2370cd"), (-7, "#6aabf1"), (-2, "#b6d5f8"), (2, "#efefef"),
              (7, "#fbd0cf"), (15, "#f5a3a2"), (25, "#ee7172"), (math.inf, "#d63b3c"))
WIND_STEPS = ((40, None), (60, "#fde0c8"), (80, "#f9b98d"), (math.inf, "#f47230"))

def _step(v, steps):
    if v is None:
        return None
    for lim, c in steps:
        if v < lim:
            return c
    return None

def snow_bg(v):
    return None if v is None or v < 0.05 else _step(v, SNOW_STEPS)

def temp_bg(v):
    return _step(v, TEMP_STEPS)

def wind_bg(v):
    return _step(v, WIND_STEPS)

def _lum(c):
    r, g, b = (int(c[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda x: x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)

def ink(bg):
    lum = _lum(bg)
    return "#ffffff" if 1.05 / (lum + 0.05) >= (lum + 0.05) / 0.05 else "#111111"

def td(content, bg=None, cls="", title=None):
    st = f' style="background:{bg};color:{ink(bg)}"' if bg else ""
    c = f' class="{cls}"' if cls else ""
    tt = f' title="{esc(title)}"' if title else ""
    return f"<td{c}{st}{tt}>{content}</td>"

# ---------------------------------------------------------------- analysis

def col(hh, key):
    v = hh.get(key)
    return v if v is not None else [None] * len(hh["time"])

def snow_stats(hh, dd, htimes, dates, ti, now, season_start, history, slug, key):
    def hsum(start, end):
        return nsum(v for tt, v in zip(htimes, hh["snowfall"]) if start < tt <= end)
    hr = dt.timedelta(hours=1)
    s = {"past24": hsum(now - 24 * hr, now), "past72": hsum(now - 72 * hr, now),
         "past7": nsum(dd["snowfall_sum"][ti - 7:ti]), "past30": nsum(dd["snowfall_sum"][ti - 30:ti]),
         "next24": hsum(now, now + 24 * hr), "next72": hsum(now, now + 72 * hr), "next7": hsum(now, now + 168 * hr)}
    # season total: model days in the 92-day window, plus stored daily history for older days
    first = dates[0]
    season = nsum(v for d, v in zip(dates[:ti], dd["snowfall_sum"][:ti]) if d >= season_start)
    season_from = max(first, season_start)
    if first > season_start:
        older = [h for d, h in history.items() if season_start <= d < first]
        season = round(season + sum(h.get(slug, {}).get(key, 0) or 0 for h in older), 1)
        dated = sorted(d for d, h in history.items() if season_start <= d < first and slug in h)
        season_from = dated[0] if dated else first
    s["season"], s["season_from"] = season, season_from.isoformat()
    return s

def make_periods(hh, htimes, now, lvl, count=18):
    """AM (06-12), PM (12-18) and night (18-06) blocks from the current one onwards."""
    T, ap, sn, rn = col(hh, "temperature_2m"), col(hh, "apparent_temperature"), col(hh, "snowfall"), col(hh, "rain")
    ws, wd, gu = col(hh, "wind_speed_10m"), col(hh, "wind_direction_10m"), col(hh, "wind_gusts_10m")
    fl, cc, wc = col(hh, "freezing_level_height"), col(hh, "cloud_cover"), col(hh, "weather_code")
    sw, sd = col(hh, f"wind_speed_{lvl}hPa"), col(hh, f"wind_direction_{lvl}hPa")

    def at_max(speeds, dirs, idx):
        best = None
        for j in idx:
            if speeds[j] is not None and (best is None or speeds[j] > speeds[best]):
                best = j
        return (r1(speeds[best]), dirs[best]) if best is not None else (None, None)

    out = []
    for di in range(-1, 9):
        d = now.date() + dt.timedelta(days=di)
        midnight = dt.datetime.combine(d, dt.time())
        for name, h0, h1 in (("AM", 6, 12), ("PM", 12, 18), ("Night", 18, 30)):
            start, end = midnight + dt.timedelta(hours=h0), midnight + dt.timedelta(hours=h1)
            if end <= now:
                continue
            idx = [j for j, tt in enumerate(htimes) if start <= tt < end]
            if len(idx) < h1 - h0 - 1:
                continue
            codes = [wc[j] for j in idx if wc[j] is not None]
            wind, wdir = at_max(ws, wd, idx)
            summit, sdir = at_max(sw, sd, idx)
            out.append({"day": d.isoformat(), "name": name, "code": max(codes) if codes else None,
                        "snow": nsum(sn[j] for j in idx), "rain": nsum(rn[j] for j in idx),
                        "tmax": r1(nmax(T[j] for j in idx)), "tmin": r1(nmin(T[j] for j in idx)),
                        "feels": r1(nmin(ap[j] for j in idx)),
                        "wind": wind, "wdir": wdir, "gust": r1(nmax(gu[j] for j in idx)),
                        "summit": summit, "sdir": sdir,
                        "freezing": r1(nmean(fl[j] for j in idx)), "cloud": r1(nmean(cc[j] for j in idx))})
            if len(out) == count:
                return out
    return out

def summarise(raw):
    now_s = raw["hourly"][0]["current"]["time"]
    now = t(now_s)
    today = now.date()
    season_start = dt.date(today.year if today.month >= 10 else today.year - 1, 10, 1)
    history = load_history()
    zones = []
    for i, z in enumerate(ZONES):
        bd, td_ = raw["daily"][2 * i]["daily"], raw["daily"][2 * i + 1]["daily"]
        bh, th = raw["hourly"][2 * i], raw["hourly"][2 * i + 1]
        hb, ht = bh["hourly"], th["hourly"]
        htimes = [t(x) for x in hb["time"]]
        dates = [dt.date.fromisoformat(x) for x in bd["time"]]
        ti = dates.index(today)

        snow = snow_stats(hb, bd, htimes, dates, ti, now, season_start, history, z["slug"], "base_snow")
        snow_top = snow_stats(ht, td_, htimes, dates, ti, now, season_start, history, z["slug"], "top_snow")

        # summit wind from the pressure level nearest the summit (500 hPa ~ 5,600m, 400 hPa ~ 7,200m)
        lvl = "400" if abs(z["top"]["elev"] - 7200) < abs(z["top"]["elev"] - 5600) else "500"
        summit, sdir = col(ht, f"wind_speed_{lvl}hPa"), col(ht, f"wind_direction_{lvl}hPa")
        ni = min(range(len(htimes)), key=lambda k: abs((htimes[k] - now).total_seconds()))
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
                "top_max": r1(td_["temperature_2m_max"][k]), "top_min": r1(td_["temperature_2m_min"][k]),
                "snow": r1(bd["snowfall_sum"][k]), "top_snow": r1(td_["snowfall_sum"][k]),
                "gust": r1(bd["wind_gusts_10m_max"][k]),
                "freezing": r1(nmean(hb["freezing_level_height"][j] for j in hrs)) if hrs else None,
                "cloud_day": r1(nmean(hb["cloud_cover"][j] for j in day_hrs)) if day_hrs else None,
                "summit_wind": r1(nmax(summit[j] for j in hrs)) if hrs else None,
            })
        past = [{"date": dates[k].isoformat(), "snow": r1(bd["snowfall_sum"][k]), "top_snow": r1(td_["snowfall_sum"][k]),
                 "base_max": r1(bd["temperature_2m_max"][k]), "base_min": r1(bd["temperature_2m_min"][k]),
                 "top_max": r1(td_["temperature_2m_max"][k]), "top_min": r1(td_["temperature_2m_min"][k])}
                for k in range(ti - 14, ti)]

        # outlook
        snowing_now = (cur_b.get("snowfall") or 0) > 0.05
        if snowing_now or snow["past72"] >= 10 or snow["past24"] >= 5:
            outlook = "fresh"
        elif snow["next72"] >= 10:
            outlook = "coming"
        elif (summit_48 or 0) >= 70:
            outlook = "wind"
        else:
            outlook = "settled"

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

        sunrise, sunset = (bd.get("sunrise") or [None] * len(dates))[ti], (bd.get("sunset") or [None] * len(dates))[ti]
        zones.append({
            **{k: z[k] for k in ("slug", "name", "region", "lat", "lon", "base", "top", "season", "about", "level", "trip", "guide")},
            "now": {"time": now_s, "base_t": r1(cur_b["temperature_2m"]), "top_t": r1(cur_t["temperature_2m"]),
                    "code": cur_b["weather_code"], "is_day": cur_b.get("is_day", 1), "gust": r1(cur_b["wind_gusts_10m"]),
                    "wind": r1(cur_b["wind_speed_10m"]), "wind_dir": col(hb, "wind_direction_10m")[ni],
                    "feels_top": r1(col(ht, "apparent_temperature")[ni]),
                    "freezing": r1(cur_b["freezing_level_height"]), "cloud": cur_b.get("cloud_cover"),
                    "summit_wind": r1(summit[ni]), "summit_dir": sdir[ni], "summit_level": lvl,
                    "sunrise": sunrise[-5:] if sunrise else None, "sunset": sunset[-5:] if sunset else None},
            "snow": snow, "snow_top": snow_top,
            "outlook": outlook, "snowing_now": snowing_now, "summit_48": r1(summit_48),
            "tonight_top_min": fdays[0]["top_min"] if fdays else None,
            "best_day": best_day, "days": fdays, "past": past,
            "periods": {"base": make_periods(hb, htimes, now, lvl), "top": make_periods(ht, htimes, now, lvl)},
            "yesterday": {"date": dates[ti - 1].isoformat(), "base_snow": r1(bd["snowfall_sum"][ti - 1]),
                          "top_snow": r1(td_["snowfall_sum"][ti - 1]),
                          "base_min": r1(bd["temperature_2m_min"][ti - 1]), "base_max": r1(bd["temperature_2m_max"][ti - 1]),
                          "top_min": r1(td_["temperature_2m_min"][ti - 1]), "top_max": r1(td_["temperature_2m_max"][ti - 1])},
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
    wide = snow_svg(z, Frame(600, 230, pl=36, pr=8), 3, "wide")
    narrow = snow_svg(z, Frame(360, 230, pl=34, pr=8), 6, "narrow")
    legend = ('<figcaption class="legend"><span><i class="sw bar"></i>Last 14 days</span>'
              '<span><i class="sw bar fc"></i>Forecast</span></figcaption>')
    return f'<figure class="chart">{wide}{narrow}{legend}</figure>'

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
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6.5" fill="{"#ffffff" if z["outlook"] == "settled" else colour}" stroke="{colour}" stroke-width="2.5"/>'
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

LOGO = ('<svg viewBox="0 0 40 40" aria-hidden="true"><rect width="40" height="40" rx="3" fill="#ffffff"/>'
        '<path d="M3 33 15 13l6 9 4-5 12 16z" fill="#2c5d93"/><path d="M12.2 17.6 15 13l3 4.6-1.5 1.2-1.4-1.1z" fill="#ffffff"/></svg>')

def page(title, desc, path, body, rel, schema=None, current=""):
    url = f"{SITE_URL}/{path}"
    robots = "index,follow,max-image-preview:large" if ALLOW_INDEXING else "noindex,follow"
    ld = f'<script type="application/ld+json">{json.dumps(schema, ensure_ascii=False)}</script>' if schema else ""
    nav = [("", "Home")] + [(f'{z["slug"]}/', z["name"]) for z in ZONES] + [("about/", "How it works")]
    links = "".join(f'<a href="{rel}{p}"{" class=on aria-current=page" if p == current else ""}>{esc(n)}</a>' for p, n in nav)
    return f"""<!DOCTYPE html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<meta name="robots" content="{robots}">
<link rel="canonical" href="{esc(url)}">
<meta name="theme-color" content="#1b3d6d">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{SITE_NAME}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{esc(url)}">
<meta name="twitter:card" content="summary">
<link rel="icon" href="{rel}assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{rel}assets/style.css">
<script>document.documentElement.className += " js";</script>
{ld}
</head>
<body>
<header class="hd"><div class="wrap hd-in">
  <a class="logo" href="{rel}">{LOGO}<span><b>Nepal Ski Conditions</b><i>Snow forecasts and reports for the Nepal Himalaya</i></span></a>
  <div class="units" role="group" aria-label="Units"><span>Units:</span><button type="button" data-units="metric" aria-pressed="true">°C · cm · m</button><button type="button" data-units="imperial" aria-pressed="false">°F · in · ft</button></div>
</div></header>
<nav class="nav" aria-label="Zones"><div class="wrap">{links}</div></nav>
<main class="wrap">
{body}
</main>
<footer class="ft"><div class="wrap">
  <p><b>Nepal Ski Conditions</b> is a free tool for skiers heading to Nepal, built and sponsored by <a href="{SPONSOR['sponsor']['url']}?{UTM}_footer" rel="sponsored noopener">King of the Hill</a>, guided ski expeditions in Nepal.</p>
  <p>Weather data: <a href="https://open-meteo.com/" rel="noopener">Open-Meteo.com</a> (CC BY 4.0), from national weather service models. Figures are model forecasts for the stated elevations, not observations, and are processed into daily and six-hourly summaries. Not an avalanche forecast.</p>
  <p><a href="{rel}about/">How it works</a> · <a href="{rel}data/conditions.json">Open data (JSON)</a> · <a href="https://github.com/Kingofthehillappjester/nepal-ski-conditions" rel="noopener">Source code</a></p>
</div></footer>
<script src="{rel}assets/app.js" defer></script>
</body>
</html>
"""

def outlook(z):
    label, colour = OUTLOOK[z["outlook"]]
    if z["outlook"] == "fresh" and z["snowing_now"]:
        label = "Snowing now"
    return f'<span class="ol {z["outlook"]}" style="--c:{colour}"><i></i>{esc(label)}</span>'

def box(title, inner, cls="", tag=""):
    t_ = f'<span class="tag">{tag}</span>' if tag else ""
    return f'<section class="box {cls}"><h2>{title}{t_}</h2><div class="bx">{inner}</div></section>'

def trip_card(trip, zone_slug=""):
    url = f'{trip["url"]}?{UTM}_{zone_slug or "home"}'
    return (f'<a class="trip" href="{esc(url)}" rel="sponsored noopener" target="_blank">'
            f'<img src="{esc(trip["image"])}" alt="" loading="lazy" decoding="async">'
            f'<b>{esc(trip["name"])}</b><span class="meta">{esc(trip["meta"])}</span>'
            f'<span class="txt">{esc(trip["blurb"])}</span><span class="go">See the trip »</span></a>')

def sponsored(zone=None):
    keys = [t["key"] for t in SPONSOR["trips"]]
    if zone and zone.get("trip") in TRIPS:
        keys.remove(zone["trip"])
        keys.insert(0, zone["trip"])
    cards = "".join(trip_card(TRIPS[k], zone["slug"] if zone else "") for k in keys[:3])
    inner = (f'<div class="trips">{cards}</div><p class="fine">These trips are run by King of the Hill, who build and pay for this site. '
             'Every trip is led by licensed Nepali guides from HST Adventures.</p>')
    return box("Ski Nepal with a guide", inner, "sponsored", "Sponsored")

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

def kit_box(zones):
    items = "".join(f"<li><b>{esc(h)}</b>{esc(p)}</li>" for h, p in kit_tips(zones))
    inner = (f'<ul class="kit">{items}</ul><p class="fine">Updated with the forecast. Full list: '
             f'<a href="{esc(SPONSOR["kit_list_url"])}?{UTM}_kit" rel="sponsored noopener">Nepal ski touring kit list</a> from King of the Hill.</p>')
    return box("What to pack this week", inner, "kitbox")

def fmt_time(s):
    return t(s).strftime("%-d %b %Y, %H:%M")

def updated(data):
    return f'<time datetime="{data["updated"]}:00+05:45" data-ago>{fmt_time(data["updated"])} Nepal time</time>'

def snow_cell(v, cls=""):
    return td(u("s", v, True) if v is not None and v >= 0.05 else '<span class="na">–</span>', snow_bg(v), cls)

def temp_cell(v, cls=""):
    return td(u("t", v, True), temp_bg(v), cls)

# ---------------------------------------------------------------- forecast table (AM / PM / night)

def forecast_table(z, which):
    ps = z["periods"][which]
    first = [i == 0 or ps[i]["day"] != ps[i - 1]["day"] for i in range(len(ps))]
    D = lambda i: "d0" if first[i] else ""
    groups = []
    for p in ps:
        if groups and groups[-1][0] == p["day"]:
            groups[-1][1] += 1
        else:
            groups.append([p["day"], 1])
    days = "".join(f'<th colspan="{n}" class="d0">{dt.date.fromisoformat(d).strftime("%a %-d %b" if n > 1 else "%a %-d")}</th>' for d, n in groups)
    per = "".join(f'<td class="{D(i)}">{"night" if p["name"] == "Night" else p["name"]}</td>' for i, p in enumerate(ps))

    def row(label, cells, cls=""):
        return f'<tr class="{cls}"><th class="lab" scope="row">{label}</th>{"".join(cells)}</tr>'

    def wind_cell(speed, deg, i, what):
        if speed is None:
            return td('<span class="na">–</span>', cls=D(i))
        arrow, name = wind_dir(deg)
        return td(f'<span class="arr">{arrow}</span>{u("w", speed, True)}', wind_bg(speed), D(i),
                  f"{what}: up to {speed:.0f} km/h from the {name}" if name else None)

    rows = [row("Weather", [td(icon(wmo(p["code"], p["name"] != "Night")[1], "wi", wmo(p["code"], p["name"] != "Night")[0]), cls=D(i)) for i, p in enumerate(ps)], "wx"),
            row(f"Snow ({ul('s')})", [snow_cell(p["snow"], D(i)) for i, p in enumerate(ps)], "sn")]
    if any((p["rain"] or 0) >= 0.5 for p in ps):
        rows.append(row("Rain (mm)", [td(f'{p["rain"]:.1f}' if (p["rain"] or 0) >= 0.5 else '<span class="na">–</span>', cls=D(i)) for i, p in enumerate(ps)]))
    rows += [row(f"Max temp ({ul('t')})", [temp_cell(p["tmax"], D(i)) for i, p in enumerate(ps)]),
             row(f"Min temp ({ul('t')})", [temp_cell(p["tmin"], D(i)) for i, p in enumerate(ps)]),
             row(f"Feels like ({ul('t')})", [temp_cell(p["feels"], D(i)) for i, p in enumerate(ps)]),
             row(f"Wind ({ul('w')})", [wind_cell(p["wind"], p["wdir"], i, "Wind") for i, p in enumerate(ps)], "wd"),
             row(f"Gusts ({ul('w')})", [td(u("w", p["gust"], True), wind_bg(p["gust"]), D(i)) for i, p in enumerate(ps)]),
             row(f"Summit wind ({ul('w')})", [wind_cell(p["summit"], p["sdir"], i, "Summit wind") for i, p in enumerate(ps)], "wd"),
             row(f"Freezing level ({ul('e')})", [td(u("e", p["freezing"], True), cls=D(i)) for i, p in enumerate(ps)]),
             row("Cloud (%)", [td(f'{p["cloud"]:.0f}' if p["cloud"] is not None else "–", cls=D(i)) for i, p in enumerate(ps)])]
    el = z[which]
    cap = f'{"Top" if which == "top" else "Base"}: {esc(el["name"])} {el["elev"]:,}m'
    return (f'<div class="elev{" on" if which == "top" else ""}" data-elev="{which}"><h3 class="elev-h">{cap}</h3>'
            f'<div class="fc-wrap"><table class="fct"><caption class="sr">{z["name"]} forecast, {cap}</caption>'
            f'<thead><tr class="day"><th class="lab">{cap.split(":")[0]} {el["elev"]:,}m</th>{days}</tr>'
            f'<tr class="per"><th class="lab">Nepal time</th>{per}</tr></thead><tbody>{"".join(rows)}</tbody></table></div></div>')

# ---------------------------------------------------------------- pages

def render_home(data):
    zones = data["zones"]
    rel = ""
    zl = lambda z, txt=None: f'<a href="{rel}{z["slug"]}/">{esc(txt or z["name"])}</a>'
    most7 = max(zones, key=lambda z: z["snow"]["past7"])
    coming = max(zones, key=lambda z: z["snow"]["next7"])
    coldest = min(zones, key=lambda z: z["tonight_top_min"] if z["tonight_top_min"] is not None else 99)
    windiest = max(zones, key=lambda z: z["summit_48"] or 0)
    fls = [z["now"]["freezing"] for z in zones if z["now"]["freezing"] is not None]
    fresh = [z for z in zones if z["outlook"] == "fresh"]
    summary = [
        ("Most snow, last 7 days", f'{u("s", most7["snow"]["past7"])} at {zl(most7)}' if most7["snow"]["past7"] >= 0.5 else "None. No new snow in any zone."),
        ("Most snow, next 7 days", f'{u("s", coming["snow"]["next7"])} at {zl(coming)}' if coming["snow"]["next7"] >= 0.5 else "None forecast in any zone."),
        ("Fresh snow now", ", ".join(zl(z) for z in fresh) or "None"),
        ("Coldest summit low today", f'{u("t", coldest["tonight_top_min"])} on {zl(coldest, coldest["top"]["name"])}'),
        ("Strongest summit wind, next 48h", f'{u("w", windiest["summit_48"])} at {zl(windiest)}'),
        ("Freezing level now", f'{u("e", min(fls))} to {u("e", max(fls))}' if fls else "–"),
    ]
    kv = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in summary)
    legend = "".join(f'<span class="ol {k}" style="--c:{c}"><i></i>{esc(lbl)}</span>' for k, (lbl, c) in OUTLOOK.items())

    rep_rows = "".join(
        f'<tr><th><a href="{rel}{z["slug"]}/">{esc(z["name"])}</a><span class="rg">{esc(z["region"])}</span></th>'
        f'<td class="l">{outlook(z)}</td><td>{u("e", z["top"]["elev"])}</td>'
        f'{snow_cell(z["snow"]["past24"])}{snow_cell(z["snow"]["past7"])}{snow_cell(z["snow"]["next72"])}'
        f'{temp_cell(z["now"]["base_t"])}{temp_cell(z["now"]["top_t"])}'
        f'<td>{u("e", z["now"]["freezing"], True)}</td>{td(u("w", z["summit_48"], True), wind_bg(z["summit_48"]))}</tr>'
        for z in zones)
    report = (f'<div class="scroll"><table class="rep"><thead><tr><th class="l">Zone</th><th class="l">Outlook</th><th>Summit</th>'
              f'<th>Snow 24h<br>({ul("s")})</th><th>Snow 7 days<br>({ul("s")})</th><th>Next 72h<br>({ul("s")})</th>'
              f'<th>Camp now<br>({ul("t")})</th><th>Summit now<br>({ul("t")})</th><th>Freezing<br>level ({ul("e")})</th>'
              f'<th>Summit wind<br>48h ({ul("w")})</th></tr></thead><tbody>{rep_rows}</tbody></table></div>'
              '<p class="fine">Snow figures are model totals at each zone\'s camp (lower elevation). Summit wind is the strongest model wind near summit height in the next 48 hours.</p>')

    wdays = [dt.date.fromisoformat(d["date"]) for d in zones[0]["days"][:7]]
    whead = "".join(f'<th>{d.strftime("%a")}<br>{d.strftime("%-d %b")}</th>' for d in wdays)
    wrows = "".join(
        f'<tr><th><a href="{rel}{z["slug"]}/">{esc(z["name"])}</a></th>'
        + "".join(td(f'{icon(wmo(d["code"])[1], "wi", wmo(d["code"])[0])}<span>{u("s", d["snow"], True) if (d["snow"] or 0) >= 0.05 else "–"}</span>', snow_bg(d["snow"]))
                  for d in z["days"][:7])
        + snow_cell(nsum(d["snow"] for d in z["days"][:7]), "tot") + "</tr>"
        for z in zones)
    week = (f'<div class="scroll"><table class="rep wk"><thead><tr><th class="l">Zone</th>{whead}<th>Total<br>({ul("s")})</th></tr></thead>'
            f'<tbody>{wrows}</tbody></table></div><p class="fine">Daily new snow ({ul("s")}) at each zone\'s camp, with the day\'s main weather.</p>')

    notes = ('<ul class="kit"><li><b>Fresh snow</b>10cm or more in the last 72 hours, 5cm in 24 hours, or snowing now.</li>'
             '<li><b>Snow on the way</b>10cm or more forecast in the next 72 hours.</li>'
             '<li><b>Strong winds up high</b>Summit-height winds of 70 km/h or more in the next 48 hours.</li>'
             '<li><b>Settled</b>None of the above.</li></ul>'
             '<p class="fine">Mountain weather in Nepal changes fast and models struggle with steep, high terrain. Use this for the big picture, not as a safety tool. Check with local guides and Nepal\'s '
             '<a href="https://www.dhm.gov.np/" rel="noopener">Department of Hydrology and Meteorology</a> before you go.</p>')

    body = f"""
<div class="title">
  <h1>Nepal snow report and forecast</h1>
  <p class="upd">Updated {updated(data)}. Forecasts for {len(zones)} ski zones in Nepal, refreshed every 3 hours.</p>
</div>
<div class="row">
  <div class="c7">{box("Snow map", map_svg(zones, rel) + f'<div class="legend">{legend}</div><p class="fine">Tap a zone for its full forecast.</p>')}</div>
  <div class="c5">{box("Snow summary", f'<table class="kv">{kv}</table>')}{kit_box(zones)}</div>
</div>
{box("Snow report: all zones", report)}
{box("7-day snow forecast", week)}
{sponsored()}
{box("What the outlooks mean", notes)}
"""
    schema = {"@context": "https://schema.org", "@type": "WebSite", "name": SITE_NAME, "url": SITE_URL + "/",
              "description": "Live snow and weather forecasts for Nepal's ski zones.",
              "publisher": {"@type": "Organization", "name": "King of the Hill", "url": SPONSOR["sponsor"]["url"]}}
    return page("Nepal Ski Conditions: snow report and forecast for Nepal's ski zones",
                "Snow report and forecast for Nepal's ski zones: Annapurna, Thorong La, Langtang, Mera Peak, Island Peak, Himlung, Putha Hiunchuli and Kalinchowk. New snow, freezing level, summit winds and 6-day forecasts.",
                "", body, rel, schema, current="")

def render_zone(z, data):
    rel = "../"
    n, s, st = z["now"], z["snow"], z["snow_top"]
    label, ic = wmo(n["code"], n["is_day"])
    level_h = "about 7,200m" if n["summit_level"] == "400" else "about 5,600m"
    best = ""
    if z["best_day"]:
        b = z["best_day"]
        bd = dt.date.fromisoformat(b["date"])
        best = (f'<p class="best"><b>Best looking day: {bd.strftime("%A %-d %B")}.</b> Lightest wind and clearest sky in the next week '
                f'(gusts to {b["gust"]:.0f} km/h, {b["cloud"]:.0f}% cloud by day).</p>')
    tabs = (f'<div class="tabs" role="tablist"><button type="button" role="tab" data-elev="top" aria-selected="true">Top: {esc(z["top"]["name"])} {z["top"]["elev"]:,}m</button>'
            f'<button type="button" role="tab" data-elev="base" aria-selected="false">Base: {esc(z["base"]["name"])} {z["base"]["elev"]:,}m</button></div>')
    fc_note = (f'<p class="fine">AM is 06:00 to 12:00, PM 12:00 to 18:00 and night 18:00 to 06:00, Nepal time. Wind is the strongest in each period, '
               f'and the arrow shows where it blows to. Summit wind is the model wind at {n["summit_level"]} hPa ({level_h}).</p>')

    season_lbl = "Season" + ("" if s["season_from"] <= data["season_start"] else f' (since {dt.date.fromisoformat(s["season_from"]).strftime("%-d %b")})')
    cols = [("past24", "Last 24h"), ("past72", "72h"), ("past7", "7 days"), ("past30", "30 days"), ("season", season_lbl),
            ("next24", "Next 24h"), ("next72", "72h"), ("next7", "7 days")]
    thead = "".join(f'<th{" class=fut" if k.startswith("next") else ""}>{lbl}</th>' for k, lbl in cols)
    srow = lambda name, el, d: (f'<tr><th>{name}<span class="rg">{esc(el["name"])} {el["elev"]:,}m</span></th>'
                                + "".join(snow_cell(d[k], "fut" if k.startswith("next") else "") for k, _ in cols) + "</tr>")
    snow_tbl = (f'<div class="scroll"><table class="rep st"><thead><tr><th class="l">New snow ({ul("s")})</th>{thead}</tr></thead>'
                f'<tbody>{srow("Base", z["base"], s)}{srow("Top", z["top"], st)}</tbody></table></div>')

    arrow, cname = wind_dir(n["wind_dir"])
    sarrow, sname = wind_dir(n["summit_dir"])
    cur = [("Weather", f'{icon(ic, "wi sm", label)} {esc(label)}'),
           (f'{esc(z["base"]["name"])}', u("t", n["base_t"])),
           (f'{esc(z["top"]["name"])}', u("t", n["top_t"])),
           ("Feels like at the top", u("t", n["feels_top"])),
           ("Wind at the camp", f'{u("w", n["wind"])} {cname and "from the " + cname}, gusts {u("w", n["gust"])}'),
           (f'Summit wind ({n["summit_level"]} hPa)', f'{u("w", n["summit_wind"])} {sname and "from the " + sname}'),
           ("Freezing level", u("e", n["freezing"])),
           ("Cloud cover", f'{n["cloud"]:.0f}%' if n["cloud"] is not None else "–"),
           ("Sunrise / sunset", f'{n["sunrise"] or "–"} / {n["sunset"] or "–"}')]
    cur_tbl = '<table class="kv">' + "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in cur) + "</table>"
    others = "".join(f'<li><a href="../{o["slug"]}/">{esc(o["name"])}</a> {outlook(o)}</li>' for o in data["zones"] if o["slug"] != z["slug"])
    about = (f'<p>{esc(z["about"])}</p><p><b>Best season:</b> {esc(z["season"])}.</p>'
             f'<p><a href="{esc(z["guide"][1])}?{UTM}_{z["slug"]}_guide" rel="noopener">{esc(z["guide"][0])} »</a> <span class="fine">from King of the Hill</span></p>')
    body = f"""
<p class="crumbs"><a href="../">Home</a> › {esc(z['region'])} › {esc(z['name'])}</p>
<div class="title">
  <h1>{esc(z['name'])} snow forecast</h1>
  <p class="sub">{esc(z['region'])}. {esc(z['base']['name'])} {z['base']['elev']:,}m to {esc(z['top']['name'])} {z['top']['elev']:,}m. {esc(z['level'])}.</p>
  <p class="upd">Outlook: {outlook(z)} &nbsp;·&nbsp; Updated {updated(data)}</p>
</div>
{best}
{box("6-day forecast", tabs + forecast_table(z, "top") + forecast_table(z, "base") + fc_note, "fcbox")}
<div class="row">
  <div class="c8">
    {box("Snow history and forecast", snow_tbl + chart_snow(z))}
    {box(f"About {esc(z['name'])}", about)}
  </div>
  <div class="c4">
    {box("Current conditions", cur_tbl)}
    {kit_box([z])}
    {box("Other zones", f'<ul class="links">{others}</ul>')}
  </div>
</div>
{sponsored(z)}
<p class="note">Model forecasts for the stated elevations, not observations. Not an avalanche forecast. Check conditions with local guides and Nepal's <a href="https://www.dhm.gov.np/" rel="noopener">Department of Hydrology and Meteorology</a>.</p>
"""
    title = f"{z['name']} snow forecast | {SITE_NAME}"
    desc = (f"Snow forecast for {z['name']}, Nepal: 6-day AM, PM and night forecast for {z['base']['name']} ({z['base']['elev']:,}m) "
            f"and {z['top']['name']} ({z['top']['elev']:,}m), with new snow, freezing level and summit winds. Updated every 3 hours.")
    schema = {"@context": "https://schema.org", "@type": "WebPage", "name": title, "description": desc,
              "url": f"{SITE_URL}/{z['slug']}/", "dateModified": data["updated_utc"],
              "about": {"@type": "Place", "name": z["name"], "geo": {"@type": "GeoCoordinates", "latitude": z["lat"], "longitude": z["lon"], "elevation": z["top"]["elev"]},
                        "containedInPlace": {"@type": "Country", "name": "Nepal"}}}
    return page(title, desc, f"{z['slug']}/", body, rel, schema, current=f"{z['slug']}/")

def render_about(data):
    rel = "../"
    zl = "".join(f'<li><b>{esc(z["name"])}</b>: {esc(z["base"]["name"])} {z["base"]["elev"]:,}m and {esc(z["top"]["name"])} {z["top"]["elev"]:,}m</li>' for z in data["zones"])
    inner = f"""
  <p>Nepal has no network of mountain weather stations or snow reports like the Alps. So this site does the next best thing: every three hours it asks global weather models for a forecast at two heights in each ski zone, the camp and the summit, and turns the numbers into tables you can read at a glance.</p>
  <h2>Where the data comes from</h2>
  <p>Forecasts come from <a href="https://open-meteo.com/" rel="noopener">Open-Meteo</a>, which combines models from national weather services, including ECMWF and NOAA's GFS, and adjusts temperature to the exact elevation we ask for. The data is licensed under <a href="https://creativecommons.org/licenses/by/4.0/" rel="noopener">CC BY 4.0</a>. We summarise it into daily and six-hourly figures; we don't change the underlying values.</p>
  <h2>The zones</h2>
  <ul>{zl}</ul>
  <h2>Reading the forecast table</h2>
  <ul>
    <li><b>AM, PM and night</b> are 06:00 to 12:00, 12:00 to 18:00 and 18:00 to 06:00, Nepal time. Switch between the top and the base of each zone with the tabs above the table.</li>
    <li><b>New snow</b> is the model's snowfall at that height. Models smooth out mountains, so real totals on high slopes can be much bigger or smaller. Blue cells get darker as totals rise.</li>
    <li><b>Temperatures</b> are shaded blue below freezing and red above it. Feels like includes wind chill.</li>
    <li><b>Wind</b> is the strongest in each period, with an arrow showing where it blows to. Orange cells mean 40 km/h or more.</li>
    <li><b>Summit wind</b> is the model wind at a standard pressure level: 500 hPa (about 5,600m) or 400 hPa (about 7,200m), whichever is closer to the summit.</li>
    <li><b>Freezing level</b> is the height where the air is at 0°C. Above it, precipitation falls as snow.</li>
    <li><b>Outlook</b>: <i>Fresh snow</i> means at least 10cm in the last 72 hours (or 5cm in 24 hours, or snowing now). <i>Snow on the way</i> means at least 10cm forecast in the next 72 hours. <i>Strong winds up high</i> means summit-height winds of 70 km/h or more in the next 48 hours. Otherwise <i>Settled</i>.</li>
    <li><b>Best looking day</b> picks the day in the next week with the lightest gusts and clearest daytime sky, and no heavy snow. It's a pointer, not a promise.</li>
  </ul>
  <h2>What it isn't</h2>
  <p>This is not an avalanche forecast and it is not a safety tool. Weather in the Himalaya changes fast, and models struggle with steep, high terrain. Always check with local guides and Nepal's <a href="https://www.dhm.gov.np/" rel="noopener">Department of Hydrology and Meteorology</a> before you go.</p>
  <h2>Who built it</h2>
  <p>This site is built and paid for by <a href="{SPONSOR['sponsor']['url']}?{UTM}_about" rel="sponsored noopener">King of the Hill</a>, who run guided ski expeditions in Nepal. Their trips appear as clearly marked sponsored placements. The forecasts are the same whoever you ski with.</p>
  <h2>Open data</h2>
  <p>Everything on the site is available as <a href="../data/conditions.json">JSON</a>, and the code is <a href="https://github.com/Kingofthehillappjester/nepal-ski-conditions" rel="noopener">on GitHub</a>. A daily snapshot is kept in the repository, so the season's history builds up over time.</p>
"""
    body = f'<p class="crumbs"><a href="../">Home</a> › How it works</p><div class="title"><h1>How it works</h1></div>{box("About this site", inner, "prose")}'
    return page(f"How it works | {SITE_NAME}", "How Nepal Ski Conditions builds its forecasts for Nepal's ski zones, what the numbers mean, and where the data comes from.", "about/", body, rel, current="about/")

def render_404():
    home = SITE_URL + "/"
    body = f'<div class="title"><h1>Page not found</h1><p class="sub"><a href="{home}">See all ski zones »</a></p></div>'
    return page(f"Not found | {SITE_NAME}", "Page not found.", "404.html", body, home, current="-")

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
              "zones": [{k: z[k] for k in ("slug", "name", "region", "lat", "lon", "base", "top", "now", "snow", "snow_top", "outlook", "days")} for z in data["zones"]]}
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
