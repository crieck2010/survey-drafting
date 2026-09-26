"""Command-line interface: `draft`."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .compose import compose_deliverable
from .layout import SHEETS
from .sadj import DraftRefused, SadjError
from .styles import StyleError, load_style, style_template, DEFAULT_STYLE
from .geometry import ParcelError
from .layers import LayerError


def _style_arg(path):
    if path is None:
        return DEFAULT_STYLE
    return load_style(path)


def cmd_draft(args) -> int:
    try:
        style = _style_arg(args.style)
    except StyleError as exc:
        print(f"draft: style error: {exc}", file=sys.stderr)
        return 2

    options = {
        "kind": args.kind,
        "sheet": args.sheet,
        "scale": args.scale,
        "title": args.title,
        "location": args.location,
        "client": args.client,
        "firm": args.firm,
        "project_no": args.project_no,
        "drawn_by": args.drawn_by,
        "checked_by": args.checked_by,
        "date": args.date,
        "basis_of_bearings": args.basis_of_bearings,
        "datum_note": args.datum_note,
        "monuments": args.monuments,
        "basemap": args.basemap,
        "basemap_world": args.basemap_world,
        "hide": args.hide.split(",") if args.hide else [],
        "sheet_no": args.sheet_no,
        "sheet_count": args.sheet_count,
        "surveyor": {
            "name": args.surveyor_name,
            "license_no": args.license_no,
            "state": args.surveyor_state,
        },
    }
    try:
        manifest = compose_deliverable(
            args.adjusted, args.parcel, style, args.out, options)
    except DraftRefused as exc:
        print(f"draft: {exc}", file=sys.stderr)
        return 3
    except (SadjError, ParcelError, StyleError, LayerError,
            ValueError) as exc:
        print(f"draft: error: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {args.out} "
          f"({manifest['outputs']['pdf']['bytes']} bytes, "
          f"scale {manifest['scale']})")
    print(f"wrote {args.out.rsplit('.', 1)[0]}.manifest.json")
    return 0


def cmd_style_template(_args) -> int:
    json.dump(style_template(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="draft",
        description="Draft plats, plans, and maps from adjusted survey "
                    "data (survey-drafting %s)" % __version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    for kind in ("plat", "plan", "map"):
        p = sub.add_parser(kind, help=f"compose a {kind} deliverable")
        p.add_argument("--adjusted", required=True,
                       help=".sadj.json from survey-adjust-workflow")
        p.add_argument("--parcel", required=True,
                       help="parcel definition JSON (survey-drafting/parcel)")
        p.add_argument("--style", default=None,
                       help="style sheet JSON (default: built-in)")
        p.add_argument("--out", required=True, help="output PDF path")
        p.add_argument("--sheet", default="ARCH_D",
                       choices=sorted(SHEETS))
        p.add_argument("--scale", default="fit",
                       help="'fit' or a standard scale (e.g. 50, 1:1000 -> 1000)")
        p.add_argument("--title", default="BOUNDARY SURVEY")
        p.add_argument("--location", default="")
        p.add_argument("--client", default="")
        p.add_argument("--firm", default="")
        p.add_argument("--project_no", default="")
        p.add_argument("--drawn_by", default="")
        p.add_argument("--checked_by", default="")
        p.add_argument("--date", default="")
        p.add_argument("--basis_of_bearings", default="")
        p.add_argument("--datum_note", default="")
        p.add_argument("--monuments", default="")
        p.add_argument("--basemap", default=None,
                       help="basemap image (.png/.jpg) for the basemap layer")
        p.add_argument("--basemap_world", default=None,
                       help="world file for the basemap image")
        p.add_argument("--hide", default="",
                       help="comma-separated layers to hide at print time")
        p.add_argument("--sheet_no", type=int, default=1)
        p.add_argument("--sheet_count", type=int, default=1)
        p.add_argument("--surveyor_name", default="")
        p.add_argument("--license_no", default="")
        p.add_argument("--surveyor_state", default="")
        p.set_defaults(kind=kind, func=cmd_draft)

    st = sub.add_parser("style-template",
                        help="print the default style sheet JSON")
    st.set_defaults(func=cmd_style_template)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
