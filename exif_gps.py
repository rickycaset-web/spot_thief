#!/usr/bin/env python3
"""
exif_gps.py - Estrae coordinate GPS, data/ora e info dispositivo dalle foto.

Input: file, cartelle (ricorsive) e/o URL http(s).
Output: tabella a schermo + (opzionali) CSV, KML, GeoJSON, mappa HTML.

Esempi:
    python exif_gps.py foto/
    python exif_gps.py IMG_1234.jpg IMG_5678.jpg --csv punti.csv --kml punti.kml
    python exif_gps.py --urls lista_url.txt --html mappa.html
    python exif_gps.py https://esempio.com/wp-content/uploads/2026/01/IMG_9719.jpg

Dipendenze: Pillow (pip install Pillow).
Per i file HEIC/HEIF serve anche: pip install pillow-heif
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict, fields
from datetime import datetime
from html import escape

try:
    from PIL import Image
except ImportError:
    sys.exit("Serve Pillow: pip install Pillow")

try:  # supporto opzionale HEIC (foto iPhone non convertite)
    from pillow_heif import register_heif_opener  # type: ignore

    register_heif_opener()
    HEIC_OK = True
except ImportError:
    HEIC_OK = False

IMAGE_EXT = {".jpg", ".jpeg", ".tif", ".tiff", ".png", ".webp", ".heic", ".heif"}

# ID dei tag EXIF usati
TAG_MAKE, TAG_MODEL, TAG_DATETIME = 0x010F, 0x0110, 0x0132
TAG_EXIF_IFD, TAG_GPS_IFD = 0x8769, 0x8825
TAG_DT_ORIGINAL, TAG_OFFSET_ORIGINAL, TAG_LENS_MODEL = 0x9003, 0x9011, 0xA434
GPS_LAT_REF, GPS_LAT, GPS_LON_REF, GPS_LON = 1, 2, 3, 4
GPS_ALT_REF, GPS_ALT, GPS_TIME = 5, 6, 7
GPS_SPEED_REF, GPS_SPEED, GPS_IMG_DIR, GPS_DATE = 12, 13, 17, 29

USER_AGENT = "Mozilla/5.0 (photo-geo-extractor)"


@dataclass
class PhotoInfo:
    source: str
    latitude: float | None = None
    longitude: float | None = None
    altitude_m: float | None = None
    datetime_local: str | None = None   # data/ora di scatto (ora del telefono)
    utc_offset: str | None = None       # es. +02:00
    gps_datetime_utc: str | None = None # data/ora dal GPS (UTC)
    weekday: str | None = None
    speed_kmh: float | None = None
    direction_deg: float | None = None  # direzione in cui puntava la fotocamera
    make: str | None = None
    model: str | None = None
    lens: str | None = None
    width: int | None = None
    height: int | None = None
    maps_url: str | None = None
    error: str | None = None

    @property
    def has_gps(self) -> bool:
        return self.latitude is not None and self.longitude is not None


GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]


# ---------------------------------------------------------------- utilità EXIF

def _f(x) -> float:
    """Converte un razionale EXIF (IFDRational o tupla) in float."""
    if isinstance(x, tuple) and len(x) == 2:
        return x[0] / x[1] if x[1] else 0.0
    return float(x)


def _dms_to_deg(dms, ref) -> float | None:
    try:
        d, m, s = (_f(v) for v in dms)
    except Exception:
        return None
    deg = d + m / 60 + s / 3600
    if isinstance(ref, bytes):
        ref = ref.decode(errors="ignore")
    if str(ref).strip().upper() in ("S", "W"):
        deg = -deg
    return round(deg, 6)


def _clean(s) -> str | None:
    if s is None:
        return None
    if isinstance(s, bytes):
        s = s.decode(errors="ignore")
    s = str(s).replace("\x00", "").strip()
    return s or None


def _parse_exif_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            pass
    return None


def extract(img: Image.Image, source: str) -> PhotoInfo:
    info = PhotoInfo(source=source, width=img.width, height=img.height)
    exif = img.getexif()
    if not exif:
        info.error = "nessun metadato EXIF"
        return info

    info.make = _clean(exif.get(TAG_MAKE))
    info.model = _clean(exif.get(TAG_MODEL))

    exif_ifd = exif.get_ifd(TAG_EXIF_IFD) or {}
    dt_raw = _clean(exif_ifd.get(TAG_DT_ORIGINAL)) or _clean(exif.get(TAG_DATETIME))
    dt = _parse_exif_dt(dt_raw)
    if dt:
        info.datetime_local = dt.strftime("%Y-%m-%d %H:%M:%S")
        info.weekday = GIORNI[dt.weekday()]
    info.utc_offset = _clean(exif_ifd.get(TAG_OFFSET_ORIGINAL))
    info.lens = _clean(exif_ifd.get(TAG_LENS_MODEL))

    gps = exif.get_ifd(TAG_GPS_IFD) or {}
    if GPS_LAT in gps and GPS_LON in gps:
        info.latitude = _dms_to_deg(gps[GPS_LAT], gps.get(GPS_LAT_REF, "N"))
        info.longitude = _dms_to_deg(gps[GPS_LON], gps.get(GPS_LON_REF, "E"))
    if GPS_ALT in gps:
        try:
            alt = _f(gps[GPS_ALT])
            ref = gps.get(GPS_ALT_REF, 0)
            if isinstance(ref, bytes):
                ref = ref[0] if ref else 0
            info.altitude_m = round(-alt if ref == 1 else alt, 1)
        except Exception:
            pass
    if GPS_SPEED in gps:
        try:
            sp = _f(gps[GPS_SPEED])
            ref = _clean(gps.get(GPS_SPEED_REF)) or "K"
            factor = {"K": 1.0, "M": 1.609344, "N": 1.852}.get(ref.upper(), 1.0)
            info.speed_kmh = round(sp * factor, 1)
        except Exception:
            pass
    if GPS_IMG_DIR in gps:
        try:
            info.direction_deg = round(_f(gps[GPS_IMG_DIR]), 1)
        except Exception:
            pass
    if GPS_DATE in gps and GPS_TIME in gps:
        try:
            h, m, s = (_f(v) for v in gps[GPS_TIME])
            d = _clean(gps[GPS_DATE]).replace(":", "-")
            info.gps_datetime_utc = f"{d} {int(h):02d}:{int(m):02d}:{int(s):02d}"
        except Exception:
            pass

    if info.has_gps:
        info.maps_url = f"https://www.google.com/maps?q={info.latitude},{info.longitude}"
    elif not info.error:
        info.error = "EXIF presente ma senza GPS"
    return info


# ---------------------------------------------------------------- input

def iter_sources(paths: list[str], url_file: str | None):
    for p in paths:
        if p.startswith(("http://", "https://")):
            yield p
        elif os.path.isdir(p):
            for root, _, files in os.walk(p):
                for name in sorted(files):
                    if os.path.splitext(name)[1].lower() in IMAGE_EXT:
                        yield os.path.join(root, name)
        else:
            yield p
    if url_file:
        with open(url_file, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    yield line


def load(source: str, timeout: float) -> PhotoInfo:
    try:
        if source.startswith(("http://", "https://")):
            req = urllib.request.Request(source, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            img = Image.open(io.BytesIO(data))
        else:
            img = Image.open(source)
        with img:
            return extract(img, source)
    except Exception as e:  # noqa: BLE001
        msg = f"{type(e).__name__}: {e}"
        if source.lower().endswith((".heic", ".heif")) and not HEIC_OK:
            msg = "HEIC non supportato: pip install pillow-heif"
        return PhotoInfo(source=source, error=msg)


# ---------------------------------------------------------------- output

def print_table(rows: list[PhotoInfo]) -> None:
    for r in rows:
        name = r.source if len(r.source) <= 70 else "…" + r.source[-69:]
        print(f"\n■ {name}")
        if r.has_gps:
            print(f"  📍 {r.latitude:.6f}, {r.longitude:.6f}"
                  + (f"   alt {r.altitude_m} m" if r.altitude_m is not None else ""))
            print(f"     {r.maps_url}")
        if r.datetime_local:
            off = f" ({r.utc_offset})" if r.utc_offset else ""
            print(f"  🕒 {r.weekday} {r.datetime_local}{off}")
        elif r.gps_datetime_utc:
            print(f"  🕒 {r.gps_datetime_utc} UTC")
        extra = []
        if r.speed_kmh is not None:
            extra.append(f"velocità {r.speed_kmh} km/h")
        if r.direction_deg is not None:
            extra.append(f"direzione {r.direction_deg}°")
        if extra:
            print("  🧭 " + ", ".join(extra))
        dev = " ".join(x for x in (r.make, r.model) if x)
        if dev:
            print(f"  📱 {dev}")
        if r.error:
            print(f"  ⚠️  {r.error}")


def write_csv(rows: list[PhotoInfo], path: str) -> None:
    names = [f.name for f in fields(PhotoInfo)]
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=names)
        w.writeheader()
        for r in rows:
            w.writerow(asdict(r))


def _label(r: PhotoInfo, i: int) -> str:
    base = os.path.basename(urllib.parse.urlparse(r.source).path) or r.source
    return f"{i}. {base}"


def _desc(r: PhotoInfo) -> str:
    parts = []
    if r.datetime_local:
        parts.append(f"{r.weekday} {r.datetime_local}" + (f" ({r.utc_offset})" if r.utc_offset else ""))
    if r.altitude_m is not None:
        parts.append(f"alt {r.altitude_m} m")
    if r.speed_kmh is not None:
        parts.append(f"{r.speed_kmh} km/h")
    dev = " ".join(x for x in (r.make, r.model) if x)
    if dev:
        parts.append(dev)
    parts.append(r.source)
    return " | ".join(parts)


def write_kml(rows: list[PhotoInfo], path: str) -> None:
    pts = [r for r in rows if r.has_gps]
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
           "<name>Foto geolocalizzate</name>"]
    for i, r in enumerate(pts, 1):
        when = ""
        if r.datetime_local:
            when = f"<TimeStamp><when>{r.datetime_local.replace(' ', 'T')}{r.utc_offset or ''}</when></TimeStamp>"
        out.append(
            f"<Placemark><name>{escape(_label(r, i))}</name>"
            f"<description>{escape(_desc(r))}</description>{when}"
            f"<Point><coordinates>{r.longitude},{r.latitude},{r.altitude_m or 0}</coordinates></Point>"
            "</Placemark>")
    out.append("</Document></kml>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))


def geojson(rows: list[PhotoInfo]) -> dict:
    feats = []
    for i, r in enumerate((r for r in rows if r.has_gps), 1):
        props = {k: v for k, v in asdict(r).items() if k not in ("latitude", "longitude")}
        props["label"] = _label(r, i)
        feats.append({"type": "Feature",
                      "geometry": {"type": "Point", "coordinates": [r.longitude, r.latitude]},
                      "properties": props})
    return {"type": "FeatureCollection", "features": feats}


def write_geojson(rows: list[PhotoInfo], path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(geojson(rows), fh, ensure_ascii=False, indent=2)


HTML_TMPL = """<!DOCTYPE html>
<html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mappa foto</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body,#map{height:100%;margin:0}</style></head>
<body><div id="map"></div><script>
const data = __DATA__;
const map = L.map('map');
const osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; OpenStreetMap'});
const sat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,attribution:'Esri'});
sat.addTo(map); L.control.layers({'Satellite':sat,'Mappa':osm}).addTo(map);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const layer = L.geoJSON(data,{onEachFeature:(f,l)=>{const p=f.properties;
 l.bindPopup(`<b>${esc(p.label)}</b><br>${esc(p.weekday||'')} ${esc(p.datetime_local||'')}<br>`+
 (p.altitude_m!=null?`alt ${esc(p.altitude_m)} m<br>`:'')+`<a href="${esc(p.maps_url)}" target="_blank">Google Maps</a>`);}}).addTo(map);
if (data.features.length) map.fitBounds(layer.getBounds().pad(0.3)); else map.setView([45,12],5);
</script></body></html>"""


def write_html(rows: list[PhotoInfo], path: str) -> None:
    payload = json.dumps(geojson(rows), ensure_ascii=False).replace("</", "<\\/")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(HTML_TMPL.replace("__DATA__", payload))


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Estrae coordinate GPS e data/ora dalle foto.")
    ap.add_argument("inputs", nargs="*", help="file, cartelle o URL")
    ap.add_argument("--urls", help="file di testo con un URL per riga")
    ap.add_argument("--csv", help="salva CSV")
    ap.add_argument("--kml", help="salva KML (Google Earth / My Maps)")
    ap.add_argument("--geojson", help="salva GeoJSON")
    ap.add_argument("--html", help="salva mappa HTML interattiva")
    ap.add_argument("--only-gps", action="store_true", help="mostra solo le foto con GPS")
    ap.add_argument("--timeout", type=float, default=20, help="timeout download URL (s)")
    a = ap.parse_args(argv)

    if not a.inputs and not a.urls:
        ap.print_help()
        return 1

    rows = [load(s, a.timeout) for s in iter_sources(a.inputs, a.urls)]
    rows.sort(key=lambda r: (r.datetime_local or r.gps_datetime_utc or "9999", r.source))
    shown = [r for r in rows if r.has_gps] if a.only_gps else rows

    print_table(shown)
    n_gps = sum(r.has_gps for r in rows)
    print(f"\nTotale: {len(rows)} foto, {n_gps} con GPS.")

    if a.csv:
        write_csv(shown, a.csv); print(f"CSV → {a.csv}")
    if a.kml:
        write_kml(rows, a.kml); print(f"KML → {a.kml}")
    if a.geojson:
        write_geojson(rows, a.geojson); print(f"GeoJSON → {a.geojson}")
    if a.html:
        write_html(rows, a.html); print(f"Mappa → {a.html}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
