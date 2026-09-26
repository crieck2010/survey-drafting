# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-09-26

### Added

- `compose_deliverable` now accepts a `RasterSource` instance (anything with
  `extent_world`/`image`, e.g. survey-basemap's `GeoTIFFRasterSource`) in the
  `basemap` option, in addition to an image path. Backward compatible: string
  paths still build a `WorldFileRaster` exactly as before. Enables the
  SurveySuite desktop app (build #5) to draft plats directly over GeoTIFF
  orthomosaics with no intermediate files.

## [0.1.0] - 2026-09-26

Initial release. Build #3 of the SurveySuite desktop product:
adjusted coordinates to professional plat/plan/map PDFs.

### Added

- `.sadj.json` reader (`drafting/sadj.py`) with a hard validity gate:
  drafting refuses (exit code 3, failed criteria named) when
  `validity.valid` is false. Weights and the justification report from
  build #2 travel with the deliverable; this module never rebuilds them.
- Parcel engine (`geometry.py`, `legal.py`) on top of `survey-cogo`:
  bearings/distances by cogo inverse, quadrant bearings, curve
  consistency checks, shoelace area with circular-segment corrections,
  US survey foot / metre support, metes-and-bounds legal description
  generated from the same resolved parcel as the drawing.
- Layer model (`layers.py`): control, boundary, linework, points,
  annotations, easements, basemap — each with a print-time visibility
  toggle; `RasterSource` contract for basemaps.
- Basemap v1: world-file-referenced PNG/JPEG rasters, decoded with
  stdlib-only PNG decoders (sub/up/average/Paeth filters, 8-bit
  RGB/gray, interlacing rejected loudly); GeoTIFF is build #4.
- Layout engine (`layout.py`): ANSI A–E and ARCH C/D sheets, standard
  engineering scales plus fit, north arrow, graphic + numeric scale
  bar, legend, line/curve tables, sheet index, title strip with a
  seal/signature block (plats) from day one.
- Hand-written vector PDF 1.4 backend (`pdf.py`): lines, polygons,
  hatches, text in the standard 14 fonts, JPEG passthrough, PNG
  embedding via Flate with correct `/DecodeParms`.
- User-editable, validated JSON style sheets (`draft style-template`),
  same philosophy as the weights config in build #2.
- CLI (`draft plat|plan|map`) and importable `compose_deliverable`
  for the desktop app (build #5).
- PDF carries the adjustment justification report and the legal
  description as text appendices; every run writes a `.manifest.json`
  with input/output SHA-256 provenance.
- 44 tests, all passing.

### Known limitations (v1)

- GeoTIFF basemaps arrive in build #4 (drone basemap layer).
- PDF uses the standard 14 base fonts; no arbitrary font embedding.
- Line/curve tables fail loudly on overflow — no multi-sheet table
  continuation yet.
- Deliverable validity depends entirely on build #2's verdict; this
  module never overrides it.
