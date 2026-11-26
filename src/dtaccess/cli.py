"""Command line: `dtaccess run ...` and `dtaccess classify ...`."""
import argparse
import json
import sys

from . import __version__
from .settings import Settings, Repairs


def _kv(items, sep="="):
    out = {}
    for it in items or []:
        k, v = it.split(sep, 1); out[k] = v
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="dtaccess", description="Directional transit access from GTFS and OpenStreetMap.")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="full run for one city (needs Java 21 and r5py)")
    r.add_argument("--gtfs", nargs="+", required=True, help="GTFS zip files (or folders)")
    r.add_argument("--osm", required=True, help="OpenStreetMap .osm.pbf covering the city plus a 10 km margin")
    r.add_argument("--boundary", required=True, help="city boundary polygon (GeoJSON, GeoPackage, shapefile)")
    r.add_argument("--population", help="population raster (WGS84, people per pixel) or polygon file with a population column")
    r.add_argument("--population-column", help="population column name for a polygon file")
    r.add_argument("--out", required=True, help="output folder")
    r.add_argument("--date", required=True, help="service day YYYY-MM-DD (a weekday on which the feeds run)")
    r.add_argument("--centre", help="city centre as LAT,LON")
    r.add_argument("--centre-name", nargs="+", help="city name(s) to look up as an OpenStreetMap place=city node")
    r.add_argument("--un-brt", nargs="*", metavar="COLUMN=VALUE", help="routes marked as rapid bus for the UN rule, e.g. agency_name=Casabusway")
    r.add_argument("--route-type-override", nargs="*", metavar="FEED.zip=TYPE", help="treat every route of a feed as this route_type for coverage")
    r.add_argument("--timezone", help="IANA zone used if a feed gives no agency_timezone")
    r.add_argument("--label-stops", help="stop file with a `mode` column, used for the class labels instead of served stops")
    r.add_argument("--feed-copy", choices=["active", "original"], default="active")
    r.add_argument("--no-clip", action="store_true", help="use the .osm.pbf as it is (already clipped)")
    r.add_argument("--r5-jar", help="path to the R5 jar (default: the one r5py downloads)")
    r.add_argument("--res", type=int, default=8); r.add_argument("--heap", default="30G")
    r.add_argument("--walk-matrix", action="store_true", help="also route walk-only (diagnostic)")
    r.add_argument("--no-repair", nargs="*", default=[], metavar="NAME", help=f"switch a feed repair off: {', '.join(Repairs.__dataclass_fields__)}")

    c = sub.add_parser("classify", help="re-run the indicators from a routed run's cache folder (no Java needed)")
    c.add_argument("--cache", required=True); c.add_argument("--out", required=True)

    a = ap.parse_args(argv)
    if a.cmd == "classify":
        from .classify import classify_from_cache
        res = classify_from_cache(a.cache, a.out)
        print(json.dumps({"headline_share": res["summary"]["headline"]["un"]["share"]}))
        return 0
    rep = Repairs()
    for n in a.no_repair:
        if n not in Repairs.__dataclass_fields__: ap.error(f"unknown repair {n}")
        setattr(rep, n, False)
    S = Settings(res=a.res, heap=a.heap, walk_matrix=a.walk_matrix, repairs=rep)
    brt = {}
    for k, v in ((it.split("=", 1)) for it in (a.un_brt or [])): brt.setdefault(k, []).append(v)
    from .pipeline import run_city
    run_city(a.gtfs, a.osm, a.boundary, a.out, population=a.population, date=a.date,
             centre=tuple(float(x) for x in a.centre.split(",")) if a.centre else None, centre_names=a.centre_name, un_brt=brt or None,
             route_type_override=_kv(a.route_type_override) or None, timezone=a.timezone, label_stops=a.label_stops,
             population_column=a.population_column, feed_copy=a.feed_copy, clip=not a.no_clip, r5_jar=a.r5_jar, settings=S)
    return 0


if __name__ == "__main__":
    sys.exit(main())
