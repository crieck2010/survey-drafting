# INTEROP — handoff contracts for survey-drafting

Build #3 of the SurveySuite desktop product. It owns the
**adjusted coordinates → deliverables** step: `.sadj.json` in,
plat/plan/map PDF + manifest out. Everything is JSON in, PDF +
JSON out; the Python API mirrors the CLI one-to-one for the
desktop app (build #5).

## Inputs

### 1. Adjusted products — `.sadj.json`

Format `survey-adjust-workflow/adjusted`, schema v1 (read with
`drafting.sadj.read_sadj`; the reader rejects `schema_version > 1`
loudly). Consumed fields:

- `points[]` — `name`, `easting`/`northing`/`elevation` (metres,
  project CRS; `null` where the path doesn't estimate — level net
  gives elevations only), one-sigma `sigma_e`/`sigma_n`/`sigma_u`,
  `source`, `held`.
- `validity.valid` — **the gate**: `false` → `DraftRefused`
  (CLI exit 3) naming every failed criterion. No override flag
  exists on purpose.
- `report` — path to the justification narrative (resolved relative
  to the `.sadj.json` directory); embedded as appendix pages when
  found, noted as missing in the manifest when not.

Sigmas are one-sigma; 95% conversions (×2.4477 2D, ×1.96 per
component) are this package's rendering choice, documented in
`docs/PLAT.md`.

### 2. Parcel definition — `parcel.json`

Format `survey-drafting/parcel`, schema v1 (frozen):

```jsonc
{"format": "survey-drafting/parcel", "schema_version": 1,
 "name": "Lot 7", "units": "ft",            // "ft" = US survey foot | "m"
 "segments": [
   {"from": "101", "to": "102"},            // straight leg
   {"from": "102", "to": "103",
    "curve": {"radius": 50.0,              // in parcel units
              "delta_deg": 60.0,           // central angle, (0, 180)
              "turn": "right"}},           // "left" | "right"
   {"from": "103", "to": "101"}]}
```

Rules: point names must exist in the `.sadj.json` point set with
non-null E/N (single source of truth — no parallel coordinates);
curve radius/delta/turn are checked for consistency against the
endpoint chord and rejected loudly on mismatch; the parcel should
close (last `to` == first `from`) — an open boundary drafts with a
misclosure note on the legal description.

### 3. Style sheet — `style.json` (optional)

Format `survey-drafting/style`, schema v1. `draft style-template`
prints the documented default. Per-layer `color [R,G,B]`,
`width_pt`, `linetype` (solid|dashed|dotted|dashdot), `symbol`
(circle|square|triangle|cross|none), `symbol_size_pt`; named text
styles (`label`, `title`, `heading`, `table`, `note`). Unknown
layers fall back to a plain style; invalid values raise `StyleError`
naming the exact key. Omit `--style` for the built-in default.

### 4. Basemap raster (optional)

`--basemap ortho.png [--basemap_world ortho.pgw]`. v1: PNG/JPEG +
world file (`.pgw`/`.jgw`). The `RasterSource` interface in
`drafting/layers.py` is the contract:

```python
class RasterSource:
    def extent_world(self): ...  # (xmin, ymin, xmax, ymax), metres
    def image(self): ...         # (bytes, w, h, kind)
                                 # kind: "rgb"|"gray"|"jpeg-rgb"|"jpeg-gray"
```

Build #4 implements `GeoTIFFRaster(RasterSource)` — the composer
already draws any `RasterSource` on the `basemap` layer, so no
composer changes are needed.

## Outputs

### A. `<name>.pdf` — the deliverable

PDF 1.4 from the hand-rolled writer (`drafting/pdf.py`): sheet at
the requested size/scale, layer stack in draw order
(basemap → easements → boundary → linework → points → control →
annotations), title strip (plats: line/curve tables + notes +
seal/signature block; plans: no seal; maps: minimal), north arrow,
graphic + numeric scale bar, legend. Appendices: the adjustment
justification report (always, when found) and the metes-and-bounds
legal description (plats).

### B. `<name>.manifest.json` — deliverable manifest

```jsonc
{"format": "survey-drafting/deliverable", "schema_version": 1,
 "generator": "survey-drafting 0.1.0", "kind": "plat",
 "created_utc": "...",
 "inputs": {"sadj": {"path": ..., "sha256": ...},
            "parcel": {"path": ..., "sha256": ...},
            "report": {"path": ..., "sha256": ...} | null},
 "outputs": {"pdf": {"path": ..., "sha256": ..., "bytes": ...}},
 "validity": true, "sheet": "ARCH_D", "scale": "1\" = 50'",
 "units": "ft"}
```

Provenance for the whole plat set in one file — the app (build #5)
can show/verify it without opening the PDF.

## Python API (build #5)

```python
from drafting import load_style, compose_deliverable
from drafting.sadj import DraftRefused

style = load_style("style.json")
try:
    manifest = compose_deliverable("r.sadj.json", "parcel.json",
                                   style, "plat.pdf", {
        "kind": "plat", "sheet": "ARCH_D", "scale": "fit",
        "title": ..., "location": ..., "client": ..., "firm": ...,
        "project_no": ..., "date": ...,
        "surveyor": {"name": ..., "license_no": ..., "state": ...},
        "basis_of_bearings": ..., "datum_note": ..., "monuments": ...,
        "basemap": "ortho.png", "basemap_world": "ortho.pgw",
        "hide": ["annotations"],          # print-time layer toggles
        "sheet_no": 1, "sheet_count": 1})
except DraftRefused as e:
    show(e.failed)   # [(criterion, detail), ...]
```

`compose_deliverable` is pure: all inputs are paths/plain data,
all outputs are files + the returned manifest dict.

## What build #4 (drone basemap) needs from this package

Implement `RasterSource` for GeoTIFF (extent + decode to one of the
four `kind`s). Optionally extend `WorldFileRaster`'s format table.
Nothing else changes — layer toggles, viewport math, and PDF image
embedding already handle it.

## What build #5 (desktop app) needs from this package

- `compose_deliverable` + `DraftRefused` (above); `load_style` /
  `style_template` for the style editor; `parse_scale` and `SHEETS`
  from `drafting.layout` for the page-setup UI; `Layer.visible`
  flags are the print-time toggles.
- The weights editor lives in build #2 (`adjustflow
  weights-template`); the justification report is generated there
  and only *packaged* here.

## Versioning

- `survey-drafting/parcel` and `survey-drafting/style` schemas bump
  on breaking changes; readers reject newer loudly; additive fields
  don't bump.
- `survey-drafting/deliverable` manifest schema v1 likewise.
- This package pins `survey-cogo` to a commit SHA (see
  `pyproject.toml`); `.sadj.json` is read with stdlib `json` against
  the documented contract, not by importing survey-adjust-workflow,
  so drafting never breaks when the adjuster revs.
