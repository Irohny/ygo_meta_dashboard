# YGO Crawler

## Voraussetzungen

- Python 3.12+
- uv fuer Installation und Ausfuehrung
- SQLite als lokale Datenbank
- Streamlit fuer das Dashboard
- just optional als Kommando-Wrapper

## Nutzung

1. Abhaengigkeiten installieren:

```bash
uv sync
```

2. Turnierdecks crawlen und in `data/ygo.sqlite` speichern:

```bash
just crawl
```

3. Kartenmetadaten anreichern:

```bash
just enrich-cards
```

4. Dashboard starten:

```bash
just dashboard
```

## Optional

Parameterisierte just-Aufrufe sind positional:

```bash
just crawl "https://ygoprodeck.com/category/format/tournament%20meta%20decks" 1 data/ygo.sqlite
just dashboard data/ygo.sqlite
```

CSV-Export erzeugen:

```bash
just dump-csv
```

Verfuegbare Rezepte anzeigen:

```bash
just
```