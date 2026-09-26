"""Lazy imports of the sibling survey-suite engines.

survey-drafting reuses the engines instead of reimplementing them:

* ``cogo`` (crieck2010/survey-cogo) -- inverses (azimuth/distance),
  bearing conversion, polygon area. Used for every bearing/distance
  label and for parcel geometry.

Imports are lazy so ``import drafting`` never fails at module scope;
each accessor raises an ImportError naming the exact pip command when
the peer is missing.
"""

from __future__ import annotations

COGO_REQ = (
    "survey-cogo @ git+https://github.com/crieck2010/survey-cogo"
    "@f59b04d8048d282cffe281723d53d521b720007d"
)


def require_cogo():
    try:
        import cogo  # type: ignore
        import cogo.inverse  # type: ignore  # noqa: F401
        import cogo.area  # type: ignore  # noqa: F401
        import cogo.point  # type: ignore  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "survey-cogo is required for drafting geometry:\n"
            f"    pip install {COGO_REQ!r}"
        ) from exc
    return cogo
