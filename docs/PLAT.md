# PLAT.md — what goes on a professional plat, and why

A short working reference: what a plat/plan/map must contain to be
taken seriously (and to pass a board review), and how this engine
produces each piece. Written for a student-surveyor audience; several
of these conventions are FS-exam territory.

## Plat vs plan vs map

- **Plat** — the signed, sealed survey document. Highest burden:
  full title block, line/curve tables, notes, seal/signature block,
  the basis-of-bearings statement. What gets recorded.
- **Plan** — a project deliverable (grading plan, site plan). Same
  drawing quality, no seal block, no line tables required.
- **Map** — cartography: location, features, orthophoto. Minimal
  dressing. Built for build #4's basemap workflows.

The CLI mirrors this: `draft plat | plan | map`.

## The ten things every plat carries

1. **Title block** — firm, project, client, location, sheet of total.
   v1 keeps project/client/firm/location in the composer options dict.
2. **Surveyor's certificate with seal** — name, license number, state,
   date, a signature line, and the seal placeholder circle drawn from
   day one. The seal is the professional statement of responsibility;
   this engine draws its place, not a fake authority.
3. **North arrow** — star polygon with "N", oriented to the parcel
   CRS grid north. v1 note: this is *grid* north of the adjusted
   coordinates, not true or magnetic north — label it so.
4. **Graphic scale bar** — a physical bar is immune to
   photocopy-shrink, unlike a printed ratio. Drawn with alternating
   divisions plus the numeric ratio.
5. **Basis of bearings** — the *definitional* sentence that makes
   every bearing on the sheet mean something. Defaults to an assumed
   basis; set `--basis_of_bearings` for real projects.
6. **Datum / coordinate note** — which projection and epoch the
   coordinates belong to, or an assumed local system. Set with
   `--datum_note`.
7. **Line and curve tables** — bearings/distances for every leg,
   radius/delta/chord/arc/tangent for every curve. Tables are the
   machine-readable part of the plat: they must repeat *exactly* the
   values annotated on the drawing, which is why both come from one
   `Parcel` object.
8. **Bearings** — quadrant form (N/S dd°mm'ss" E/W), distances to the
   field unit (US survey foot here). Bearings come from the
   `survey-cogo` inverse, not hand math.
9. **Lot area** — by coordinates (shoelace), with circular-segment
   corrections where curves cut the chord, reported both as square
   feet and acres.
10. **Monuments** — set vs. found. v1 prints a generic monument note;
    mark this field honestly per job with `--monuments`.

## Legal description

The metes-and-bounds narrative is generated from the same resolved
`Parcel` as the drawing — the words literally cannot disagree with
the lines. The point of beginning, each call (bearing, distance, and
curve particulars), the area, and the "more or less" phrasing that
marks computed acreage.

## Sigmas on the sheet

Point uncertainties are one-sigma as stored. The 95% error ellipse
shown on control points scales the stored sigmas by 2.4477 — that's a
rendering choice, not part of the adjustment contract.

## Drafting hygiene this engine enforces

- The validity gate: an adjustment that isn't VALID never becomes a
  plat. The justification report rides inside the PDF as an appendix.
- One parcel object drives drawing, tables, area, and the legal
  description — a single source of truth by construction.
- Curves are checked for chord consistency before anything is drawn;
  a bad curve fails loudly instead of printing a wrong arc.
- Tables fail loudly when they overflow the strip instead of silently
  truncating — a plat that hides calls is worse than one that won't
  print. (Multi-sheet table continuation is a future version.)
