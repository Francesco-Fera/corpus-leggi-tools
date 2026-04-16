"""Entry point ``corpus-leggi-bulk``.

Bulk load di atti Normattiva via API 4 (export asincrono). 3 subcommand:

- ``export``: chiama l'API asincrona e scarica lo ZIP AKN risultante
- ``import``: decomprime uno ZIP locale e lo ingerisce nel dataset
- ``run``: ``export`` + ``import`` in sequenza (con ZIP cache per retry/resume)

Il bulk NON popola ``articolo.vigenza_inizio`` (cfr. issue #4 wontfix): il
dataset materializzato riflette testo + rubrica + abrogazione, sufficiente
per l'uso primario (MCP/RAG, consultazione).
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from datetime import date
from pathlib import Path

from .normattiva_client import (
    TIPO_PROV_CODES,
    AsyncSearchParams,
    async_export_to_zip,
)
from .repo_writer import RepoWriter
from .sync_delta import process_atto_from_xml


def _validate_tipo(code: str) -> str:
    """``argparse`` type hook: valida il codice tipologica IPZS."""
    if code not in TIPO_PROV_CODES:
        valid = ", ".join(sorted(TIPO_PROV_CODES.keys()))
        raise argparse.ArgumentTypeError(
            f"tipo {code!r} non valido. Codici supportati: {valid}"
        )
    return code


def bulk_export(
    tipo: str,
    from_year: int,
    to_year: int,
    output_zip: Path,
    *,
    classe: str = "2",
    formato: str = "AKN",
) -> int:
    """Avvia un export async IPZS → scarica lo ZIP in ``output_zip``."""
    from_iso = f"{from_year:04d}-01-01"
    to_iso = f"{to_year:04d}-12-31"
    print(
        f"[bulk export] {tipo} {from_iso} → {to_iso} "
        f"(classe={classe}) → {output_zip}",
        file=sys.stderr,
    )
    params: AsyncSearchParams = {
        "classeProvvedimento": classe,
        "dataInizioEmanazione": from_iso,
        "dataFineEmanazione": to_iso,
        "filtriMap": {"codice_tipo_provvedimento": tipo},
    }
    async_export_to_zip(params, output_zip, formato=formato)
    print(f"[bulk export] Done: {output_zip}", file=sys.stderr)
    return 0


# Pattern nome file AKN all'interno delle cartelle atto nello ZIP IPZS:
#   {DATAGU}_{REDAZIONALE}_VIGENZA_{DATAVIGENZA}_V{N}.xml
#   {DATAGU}_{REDAZIONALE}_ORIGINALE_V0.xml
_VIGENZA_FILE_RE = re.compile(
    r"^(\d{8})_([^_]+)_VIGENZA_(\d{8})_V(\d+)\.xml$", re.IGNORECASE
)
_ORIGINALE_FILE_RE = re.compile(
    r"^(\d{8})_([^_]+)_ORIGINALE_V(\d+)\.xml$", re.IGNORECASE
)


def pick_best_xml(xml_files: list[Path]) -> Path | None:
    """Seleziona l'XML da processare in una cartella atto di uno ZIP IPZS.

    Preferenza:
      1. ``VIGENZA_V<N>`` con V massimo (atto consolidato all'ultima vigenza)
      2. ``ORIGINALE_V0`` come fallback (atto mai modificato post-pubblicazione)

    Ritorna None se nessun pattern riconosciuto.
    """
    vigenze: list[tuple[int, Path]] = []
    originali: list[tuple[int, Path]] = []
    for p in xml_files:
        m_v = _VIGENZA_FILE_RE.match(p.name)
        if m_v:
            vigenze.append((int(m_v.group(4)), p))
            continue
        m_o = _ORIGINALE_FILE_RE.match(p.name)
        if m_o:
            originali.append((int(m_o.group(3)), p))
    if vigenze:
        vigenze.sort(key=lambda t: t[0])
        return vigenze[-1][1]
    if originali:
        originali.sort(key=lambda t: t[0])
        return originali[-1][1]
    return None


def _zip_filename(tipo: str, from_year: int, to_year: int) -> str:
    return f"{tipo}_{from_year}-{to_year}.zip"


def bulk_import(
    zip_path: Path,
    dataset_root: Path,
    *,
    limit: int | None = None,
) -> int:
    """Decomprime uno ZIP IPZS e processa ogni cartella atto.

    Struttura attesa:
      ``{TIPO}_{YYYYMMDD}_{NUM}/ {DATAGU}_{REDAZ}_VIGENZA_{...}_V{N}.xml``.

    L'estrazione avviene in ``{zip_path}.parent / {zip_path.stem}_extracted/``.
    Se la cartella esiste la riusiamo (retry/resume). Errori per singolo atto
    non interrompono il run: vengono conteggiati e stampati su stderr.
    """
    if not zip_path.exists():
        raise FileNotFoundError(f"ZIP non trovato: {zip_path}")

    print(f"[bulk import] {zip_path} → {dataset_root}", file=sys.stderr)
    today = date.today().isoformat()
    writer = RepoWriter(dataset_root)

    errors = 0
    processed = 0
    skipped_no_xml = 0

    extract_dir = zip_path.parent / f"{zip_path.stem}_extracted"
    if extract_dir.exists():
        print(
            f"[bulk import] reuse cartella già estratta: {extract_dir}",
            file=sys.stderr,
        )
    else:
        print(f"[bulk import] extracting → {extract_dir}", file=sys.stderr)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)

    atto_dirs = sorted(d for d in extract_dir.iterdir() if d.is_dir())
    if limit is not None:
        atto_dirs = atto_dirs[:limit]
        print(f"[bulk import] limit={limit}", file=sys.stderr)
    print(f"[bulk import] {len(atto_dirs)} atti da processare", file=sys.stderr)

    try:
        for i, atto_dir in enumerate(atto_dirs, start=1):
            print(f"[{i}/{len(atto_dirs)}] {atto_dir.name}")
            xmls = list(atto_dir.glob("*.xml"))
            xml_path = pick_best_xml(xmls)
            if xml_path is None:
                print(
                    f"  SKIP: nessun AKN XML utile in {atto_dir.name}",
                    file=sys.stderr,
                )
                skipped_no_xml += 1
                continue
            try:
                process_atto_from_xml(xml_path, writer, today)
                processed += 1
            except Exception as e:
                print(f"  ERROR {atto_dir.name}: {e}", file=sys.stderr)
                errors += 1
                continue
    finally:
        writer.save_manifest()

    stats = writer.stats
    print(
        f"\n[bulk import] Done. atti_processed={processed} errors={errors} "
        f"skipped_no_xml={skipped_no_xml}",
        file=sys.stderr,
    )
    print(
        f"              files: written={stats['written']} "
        f"skipped={stats['skipped']}",
        file=sys.stderr,
    )
    return 0 if errors == 0 else 1


def bulk_run(
    tipo: str,
    from_year: int,
    to_year: int,
    dataset_root: Path,
    zip_cache: Path,
    *,
    classe: str = "2",
    limit: int | None = None,
    reuse_zip: bool = True,
) -> int:
    """``export`` + ``import`` in sequenza, con ZIP cache condivisa.

    Se lo ZIP per questa combinazione tipo×anni è già in cache e ``reuse_zip``
    è True (default), saltiamo l'export. Utile per retry rapidi post-fix.
    """
    zip_cache.mkdir(parents=True, exist_ok=True)
    zip_path = zip_cache / _zip_filename(tipo, from_year, to_year)

    if reuse_zip and zip_path.exists():
        print(f"[bulk run] ZIP in cache: {zip_path} — skip export", file=sys.stderr)
    else:
        rc = bulk_export(tipo, from_year, to_year, zip_path, classe=classe)
        if rc != 0:
            return rc

    return bulk_import(zip_path, dataset_root, limit=limit)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="corpus-leggi-bulk")
    sub = parser.add_subparsers(dest="command", required=True)

    common_dataset = argparse.ArgumentParser(add_help=False)
    common_dataset.add_argument(
        "--dataset-root",
        type=Path,
        required=True,
        help="Path al working tree di corpus-leggi",
    )

    p_export = sub.add_parser(
        "export", help="Scarica uno ZIP AKN per tipo x range anni"
    )
    p_export.add_argument(
        "--tipo",
        required=True,
        type=_validate_tipo,
        help="Codice tipologica IPZS (es. PLE=legge, PDL=decreto-legge, PLL=decreto-legislativo)",
    )
    p_export.add_argument("--from-year", required=True, type=int)
    p_export.add_argument("--to-year", required=True, type=int)
    p_export.add_argument(
        "--output", required=True, type=Path, help="Path dello ZIP da creare"
    )
    p_export.add_argument(
        "--classe",
        default="2",
        help="classeProvvedimento (1=tutto, 2=vigenti (default), 3=abrogati)",
    )

    p_import = sub.add_parser(
        "import",
        parents=[common_dataset],
        help="Ingerisci uno ZIP AKN locale nel dataset",
    )
    p_import.add_argument("--zip", dest="zip_path", required=True, type=Path)
    p_import.add_argument(
        "--limit", type=int, default=None, help="Processa solo i primi N atti"
    )

    p_run = sub.add_parser(
        "run", parents=[common_dataset], help="export + import in sequenza"
    )
    p_run.add_argument("--tipo", required=True, type=_validate_tipo)
    p_run.add_argument("--from-year", required=True, type=int)
    p_run.add_argument("--to-year", required=True, type=int)
    p_run.add_argument(
        "--zip-cache",
        type=Path,
        default=Path(".bulk_cache"),
        help="Cartella dove memorizzare gli ZIP scaricati (riusa se presente)",
    )
    p_run.add_argument("--classe", default="2")
    p_run.add_argument("--limit", type=int, default=None)
    p_run.add_argument(
        "--force-redownload",
        action="store_true",
        help="Ignora lo ZIP in cache e forza un nuovo export",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "export":
        return bulk_export(
            tipo=args.tipo,
            from_year=args.from_year,
            to_year=args.to_year,
            output_zip=args.output,
            classe=args.classe,
        )
    if args.command == "import":
        return bulk_import(
            zip_path=args.zip_path,
            dataset_root=args.dataset_root,
            limit=args.limit,
        )
    if args.command == "run":
        return bulk_run(
            tipo=args.tipo,
            from_year=args.from_year,
            to_year=args.to_year,
            dataset_root=args.dataset_root,
            zip_cache=args.zip_cache,
            classe=args.classe,
            limit=args.limit,
            reuse_zip=not args.force_redownload,
        )

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
