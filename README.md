# 📍 Spot Thief

Estrae **coordinate GPS**, **data/ora di scatto** e **dispositivo** dai metadati EXIF delle foto, e li mette su mappa con export **CSV / KML / GeoJSON**.

Ci sono due modi per usarlo:

| | Pagina web (`index.html`) | Script (`exif_gps.py`) |
|---|---|---|
| Come | trascini le foto nel browser | riga di comando |
| Installazione | nessuna | Python 3.9+ e Pillow |
| Cartelle intere | sì (selezione multipla) | sì, ricorsivo |
| Da URL | solo se il sito lo permette (CORS) | sì, anche liste di URL |
| HEIC iPhone | sì | con `pillow-heif` |

Tutto gira in locale: le foto non vengono mandate da nessuna parte.

---

## Pagina web

### Online
👉 **https://rickycaset-web.github.io/spot_thief/**

(GitHub Pages: *Settings → Pages → Branch `main` / root*)

### In locale
Apri `index.html` con doppio clic.

### Funzioni
- drag & drop di più foto insieme
- mappa satellitare / stradale, con il layer opzionale **OpenSeaMap** (segnali nautici)
- marker numerati in ordine cronologico, clic su una foto per centrare la mappa
- export **CSV** (Excel), **KML** (Google My Maps / Google Earth, con timestamp), **GeoJSON**
- "Copia coordinate" per incollare tutto al volo

---

## Script Python

```bash
pip install Pillow            # obbligatorio
pip install pillow-heif       # opzionale, per i .HEIC
```

```bash
# una cartella intera
python exif_gps.py foto/

# file singoli + export
python exif_gps.py IMG_1.jpg IMG_2.jpg --csv punti.csv --kml punti.kml --html mappa.html

# direttamente da URL
python exif_gps.py https://sito.com/wp-content/uploads/2026/01/IMG_9719.jpg

# lista di URL (uno per riga, # per commenti)
python exif_gps.py --urls lista.txt --kml punti.kml --only-gps
```

| Opzione | Cosa fa |
|---|---|
| `--csv FILE` | tabella con tutti i campi |
| `--kml FILE` | punti per Google My Maps / Earth |
| `--geojson FILE` | per QGIS, geojson.io ecc. |
| `--html FILE` | mappa interattiva standalone |
| `--only-gps` | mostra/salva solo le foto con coordinate |
| `--urls FILE` | file con un URL per riga |

Output a schermo:
```
■ IMG_9719.jpg
  📍 44.547614, 14.276381   alt 2.0 m
     https://www.google.com/maps?q=44.547614,14.276381
  🕒 mercoledì 2026-01-14 07:32:10 (+01:00)
  📱 Apple iPhone 17 Pro Max
```

---

## Campi estratti

`latitude`, `longitude`, `altitude_m`, `datetime_local` (ora del telefono), `utc_offset`, `gps_datetime_utc`, `weekday`, `speed_kmh`, `direction_deg` (dove puntava la fotocamera), `make`, `model`, `lens`, dimensioni e link Google Maps.

## Quando non trova niente

- **Instagram, Facebook, WhatsApp, TikTok** cancellano i metadati.
- Le **miniature** generate dai CMS (es. `/elementor/thumbs/`, `-1024x768.jpg`) spesso li perdono: cerca il file originale in `/wp-content/uploads/ANNO/MESE/`.
- Le immagini esportate da **Figma / Photoshop** ("Mask group", "Export") di solito non li hanno.
- Con **EXIF presente ma senza GPS**, la localizzazione era spenta sul telefono.
- Le coordinate indicano **dove è stata scattata** la foto, non necessariamente dove è stata caricata.

## Licenza
MIT
