# Nepal Ski Conditions

Live snow and weather for Nepal's ski zones: Annapurna Sanctuary, Thorong La, Langtang, Mera Peak, Island Peak, Himlung Himal, Putha Hiunchuli and Kalinchowk.

Built and sponsored by [King of the Hill](https://www.kingofthehill.co.uk/). Weather data from [Open-Meteo.com](https://open-meteo.com/) (CC BY 4.0).

## How it works

- `build.py` asks Open-Meteo for forecasts at two heights in each zone (where you sleep and where you ski to), works out new snow, freezing level, summit-height winds and a 10-day outlook, and writes a static site to `dist/`. Standard-library Python, no dependencies.
- A GitHub Action (`.github/workflows/update.yml`) runs it every 3 hours and publishes to GitHub Pages.
- Each day's totals are saved to `data/history/`, so the season record builds up over time.

## Editing

| What | Where |
| --- | --- |
| Zones (names, heights, coordinates, text) | `zones.json` |
| Sponsored trips and kit-list link | `trips.json` |
| Look and feel | `assets/style.css` |
| Wording and layout | `build.py` (render functions) |

Every push to `main` rebuilds and redeploys the site.

## Settings (repo Settings, then Secrets and variables, then Actions)

| Name | Type | Purpose |
| --- | --- | --- |
| `OPEN_METEO_API_KEY` | Secret | Commercial Open-Meteo key. Needed before public launch, because the site carries sponsored placements. |
| `SITE_URL` | Variable | Public address, e.g. `https://nepalskiing.com` |
| `CUSTOM_DOMAIN` | Variable | e.g. `nepalskiing.com`. Writes the CNAME file for GitHub Pages. |
| `ALLOW_INDEXING` | Variable | Set to `1` to let search engines index the site. Off until launch. |

## Run locally

```
python build.py --raw dev/sample-raw.json --no-history
python -m http.server -d dist 8000
```
