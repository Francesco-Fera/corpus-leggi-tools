# corpus-leggi-tools

Pipeline Python per popolare e mantenere aggiornato il dataset [**corpus-leggi**](https://github.com/Francesco-Fera/corpus-leggi) con i testi delle leggi italiane da [Normattiva](https://www.normattiva.it) (IPZS).

## Architettura

```
┌──────────────┐    ┌──────────────────┐    ┌─────────────┐
│ Normattiva   │───▶│ corpus-leggi     │───▶│ corpus-leggi│
│ OpenData API │    │ -tools (pipeline)│ push│ (dataset)   │
└──────────────┘    └─────┬────────────┘    └─────────────┘
                          │ uses pip
                          ▼
                   ┌──────────────┐
                   │ normattiva2md│  ← conversione AKN → Markdown
                   └──────────────┘
```

## Moduli

| Modulo | Responsabilità |
|--------|----------------|
| `normattiva_client` | Wrapper REST API Normattiva OpenData (ricerca aggiornati, export asincrono, dettaglio atto-urn) |
| `metadata` | Estrazione metadati da Akoma Ntoso XML (URN, titolo, tipo, numero, data, ecc.) |
| `converter` | Orchestrazione conversione AKN → Markdown, un file per articolo, front matter YAML arricchito |
| `repo_writer` | Scrittura atomica con dedup SHA-256 + manifest persistente |
| `indexer` | Generazione `index.json`, `README.md` navigabile, (opzionale) SQLite FTS5 |
| `sync_delta` | Delta sync giornaliero — entry point `corpus-leggi-sync` |
| `bulk_load` | Carico iniziale via export asincrono — entry point `corpus-leggi-bulk` |

## Sviluppo

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash
# source .venv/bin/activate      # Linux/macOS
pip install -e ".[dev]"
```

Dipendenze core: `normattiva2md`, `requests`, `pyyaml`.
Dipendenze dev: `pytest`, `ruff`, `mypy`.

## Uso

```bash
# Delta sync (daily cron)
corpus-leggi-sync

# Bulk load iniziale
corpus-leggi-bulk --tipo legge --anno-inizio 2020 --anno-fine 2024
```

(Dettagli CLI in fase di sviluppo.)

## Licenza

[MIT](LICENSE).

## Vedi anche

- Dataset: [corpus-leggi](https://github.com/Francesco-Fera/corpus-leggi)
- Converter AKN → MD: [ondata/normattiva_2_md](https://github.com/ondata/normattiva_2_md)
- API: [dati.normattiva.it](https://dati.normattiva.it)
