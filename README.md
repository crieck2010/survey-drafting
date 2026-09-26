# survey-drafting

A pure-Python, dependency-free **drafting and deliverables engine** for
land surveying: adjusted coordinates in, professional-grade plats,
plans, and maps out as PDF.

This is build #3 of the SurveySuite desktop product. It owns the
**adjusted coordinates → deliverables** step:

```
Emlid CSV --(survey-field)--> job.sfield.json --(survey-adjust-workflow)-->
result.sadj.json --(survey-drafting)--> plat.pdf + manifest.json
```

The engine refuses to draft from an adjustment that is not VALID, and
the adjustment's justification report travels inside the PDF as an
appendix — the plat set is self-justifying.

Engine-only on purpose — no UI, no third-party libraries, not even a
PDF library: the vector PDF writer is hand-rolled in `pdf.py`. It can
be imported by scripts, embedded in the desktop app (build #5), or
installed as a library.

## Features

- **Validity gate** — refuses (non-zero exit, failed criteria named)
  to draft when `validity.valid` is false in the `.sadj.json`
  contract. Weights and the justification report from build #2 travel
  with the deliverable; this module consumes them, never rebuilds them.
- **Parcel geometry** — boundary linework from an ordered point list,
  bearing/distance callouts via the `survey-cogo` engine, circular
  curve support with curve tables, lot area (with circular-segment
  corrections), US survey feet or metres.
- **Metes-and-bounds generator** — a written legal description derived
  from the same resolved parcel as the drawing, so the words can never
  disagree with the lines.
- **Layer model** — named layers (control, boundary, linework, points,
  annotations, easements, basemap raster) each with a visibility
  toggle, the toggle the app exposes at print time.
- **Basemap raster v1** — world-file-referenced PNG/JPEG (what ODM and
  DJI Terra export); the `RasterSource` contract is defined so build
  #4's GeoTIFF plugs in unchanged.
- **Layouts** — ANSI A–E and ARCH C/D sheets, viewports at standard
  engineering scales (1"=10' … 1"=100', 1:250 … 1:5000) or fit,
  title block with a **seal/signature block from day one**, north
  arrow, graphic + numeric scale bar, legend, line/curve tables.
- **User-dictated styling** — a human-editable JSON style sheet
  (line weights/types, symbols, text styles, colors), validated loudly,
  same philosophy as the weights config in build #2.
- **PDF backend** — hand-written PDF 1.4: lines, polygons, hatches,
  text in the standard 14 fonts, JPEG passthrough and PNG embedding.
  Validated structurally in tests and against poppler.

## Installation

Requires Python 3.9+.

```bash
pip install "survey-drafting @ git+https://github.com/crieck2010/survey-drafting@v0.1.0"
```

## Worked example — CSV to plat, end to end

The `examples/` folder carries a tiny synthetic lot (`lot7-*.csv`,
Emlid Flow format with base coordinates, two occupations per corner).
The full field-to-finish chain across all three repos:

```bash
# 1. Import the Emlid CSVs (survey-field, build #1)
field import lot7-2026-09-24.csv -o day1.sfield.json --name "Lot 7 demo"
field import lot7-2026-09-25.csv -o day2.sfield.json --name "Lot 7 demo"
# (merge the two sessions into one job file)

# 2. Weight and adjust (survey-adjust-workflow, build #2)
adjustflow weights-template > weights.json   # edit your stochastic model
adjustflow run --job job.sfield.json --weights weights.json \
    --report report.md --out result.sadj.json --path rtk
# verdict: VALID

# 3. Draft the plat (this repo, build #3)
draft plat --adjusted result.sadj.json --parcel parcel.json \
    --out plat.pdf --sheet ARCH_D \
    --title "BOUNDARY SURVEY" --location "Rochester, NY" \
    --surveyor_name "Charles Rieck" --surveyor_state "NY"
# wrote plat.pdf (..., scale FIT (1" = 7.0'))
# wrote plat.manifest.json
```

`parcel.json` names the boundary as an ordered segment list over the
*adjusted* point names (single source of truth):

```json
{"format": "survey-drafting/parcel", "schema_version": 1,
 "name": "Lot 7", "units": "ft",
 "segments": [{"from": "101", "to": "102"},
              {"from": "102", "to": "103",
               "curve": {"radius": 50.0, "delta_deg": 60.0, "turn": "right"}},
              {"from": "103", "to": "104"},
              {"from": "104", "to": "101"}]}
```

Curve geometry is consistency-checked against the endpoint chord and
rejected loudly if it disagrees.

## CLI

```
draft plat --adjusted result.sadj.json --parcel parcel.json \
    --style style.json --out plat.pdf
draft plan ...   # simpler title block, no seal
draft map  ...   # minimal cartography, no tables
draft style-template   # print the default style sheet JSON
```

Useful flags: `--sheet ARCH_D`, `--scale 50` (or `fit`),
`--basemap ortho.png` (+ `--basemap_world ortho.pgw`),
`--hide annotations,basemap`, `--surveyor_name/--license_no/--surveyor_state`,
`--basis_of_bearings`, `--datum_note`.

Exit codes: 0 ok · 2 input/style/parcel error · 3 refused — adjustment
not VALID (failed criteria printed).

## Python API (for the desktop app, build #5)

```python
from drafting import load_style, compose_deliverable

style = load_style("style.json")          # validated, user-editable
manifest = compose_deliverable(
    "result.sadj.json", "parcel.json", style, "plat.pdf",
    {"kind": "plat", "sheet": "ARCH_D", "scale": "fit",
     "title": "BOUNDARY SURVEY", "location": "Rochester, NY",
     "surveyor": {"name": "Charles Rieck", "license_no": "...",
                  "state": "NY"},
     "basemap": "ortho.png",             # optional
     "hide": ["annotations"]})           # print-time layer toggles
```

`DraftRefused` (from `drafting.sadj`) is raised when the adjustment is
not valid — catch it to show the failed criteria in the UI.

## Docs

- `docs/INTEROP.md` — exact contracts: inputs, outputs, what builds
  #4 (drone basemap) and #5 (desktop app) consume.
- `docs/PLAT.md` — what goes on a professional plat and why
  (educational; FS-exam relevant).
- `CHANGELOG.md` — version history.

## Versioning

Semantic versioning. `parcel.json` (`survey-drafting/parcel` v1) and
`style.json` (`survey-drafting/style` v1) schemas are versioned;
readers reject newer versions loudly. Additive fields don't bump.

## License

MIT — see LICENSE.
