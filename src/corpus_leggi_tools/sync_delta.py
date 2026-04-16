"""Entry point ``corpus-leggi-sync``.

Subcommand:
- ``atto --urn <URN>``: scarica, converte e scrive nel dataset un singolo atto
- ``range --from <DATE> --to <DATE>``: cerca atti aggiornati nell'intervallo
  (``POST /ricerca/aggiornati``) e sincronizza ognuno
- ``daily``: legge ``data/last_sync.json``, fa ``range`` da lì a oggi, aggiorna
  il file. Entry point del cron giornaliero.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

from .converter import ArticoloMeta, build_index_md, convert_article_to_md
from .metadata import (
    AttoMetadata,
    atto_directory,
    build_metadata_from_xml,
    eid_to_article_num,
    list_article_eids,
)
from .normattiva_client import (
    build_url_from_urn,
    build_urn_from_updated,
    download_akn_by_urn,
    fetch_articolo_vigenza,
    search_updated,
)
from .repo_writer import RepoWriter

# Pausa tra chiamate API (IPZS raccomanda 300ms).
API_PAUSE_SEC = 0.3

LAST_SYNC_REL_PATH = "data/last_sync.json"


def _xml_cache_path(xml_cache: Path, atto: AttoMetadata) -> Path:
    return xml_cache / f"{atto.slug_tipo}_{atto.data_gu}_{atto.numero}.xml"


def _download_to_tmp(urn: str, xml_cache: Path) -> Path:
    tmp_path = xml_cache / "_tmp_download.xml"
    xml_cache.mkdir(parents=True, exist_ok=True)
    if tmp_path.exists():
        tmp_path.unlink()
    if not download_akn_by_urn(urn, tmp_path, quiet=True):
        raise RuntimeError(f"Download fallito per URN: {urn}")
    return tmp_path


def _process_atto(
    urn: str,
    dataset_root: Path,
    xml_cache: Path,
    writer: RepoWriter,
    today: str,
) -> tuple[int, int]:
    """Sync di un singolo atto dentro un writer già istanziato.

    Ritorna (articoli_scritti, articoli_skippati).
    """
    tmp_xml = _download_to_tmp(urn, xml_cache)
    atto = build_metadata_from_xml(tmp_xml, fallback_url=build_url_from_urn(urn))
    final_xml = _xml_cache_path(xml_cache, atto)
    tmp_xml.replace(final_xml)

    print(f"  {atto.denominazione} {atto.data} n. {atto.numero} — {atto.titolo[:80]}")

    root = ET.parse(final_xml).getroot()
    eids = list_article_eids(root)
    rel_dir = atto_directory(atto)
    articles_meta: list[tuple[str, ArticoloMeta]] = []
    written_before = writer.stats["written"]
    skipped_before = writer.stats["skipped"]

    for eid in eids:
        num = eid_to_article_num(eid)
        articolo_urn = f"{atto.urn}~art{num}"
        try:
            vigenza_inizio = fetch_articolo_vigenza(articolo_urn)
        except Exception as e:
            # Soft-fail: se la chiamata vigenza fallisce non blocchiamo il
            # processing dell'articolo, lo scriviamo senza il campo.
            print(f"    WARN fetch vigenza {articolo_urn}: {e}", file=sys.stderr)
            vigenza_inizio = None
        time.sleep(API_PAUSE_SEC)
        result = convert_article_to_md(
            final_xml, atto, num, today, vigenza_inizio=vigenza_inizio
        )
        if result is None:
            continue
        md, art_meta = result
        writer.write_if_changed(f"{rel_dir}/art-{num}.md", md)
        articles_meta.append((num, art_meta))

    writer.write_if_changed(
        f"{rel_dir}/_index.md", build_index_md(atto, articles_meta, today)
    )

    delta_written = writer.stats["written"] - written_before
    delta_skipped = writer.stats["skipped"] - skipped_before
    print(f"    → articoli: written={delta_written}, skipped={delta_skipped}")
    return delta_written, delta_skipped


def sync_single_atto(
    urn: str,
    dataset_root: Path,
    xml_cache: Path,
) -> int:
    print(f"[sync atto] URN: {urn}")
    today = date.today().isoformat()
    writer = RepoWriter(dataset_root)
    try:
        _process_atto(urn, dataset_root, xml_cache, writer, today)
    finally:
        writer.save_manifest()
    stats = writer.stats
    print(f"\n[sync atto] Done. written={stats['written']} skipped={stats['skipped']}")
    return 0


def sync_range(
    from_date: date,
    to_date: date,
    dataset_root: Path,
    xml_cache: Path,
    *,
    persist_last_sync: bool = False,
    limit: int | None = None,
    dry_run: bool = False,
) -> int:
    print(f"[sync range] ricerca aggiornati {from_date} → {to_date}")
    atti = search_updated(from_date, to_date)
    print(f"[sync range] {len(atti)} atti totali")
    if limit is not None:
        atti = atti[:limit]
        print(f"[sync range] limit={limit}, processo i primi {len(atti)}")
    if dry_run:
        print("[sync range] dry-run: elenco atti senza scaricare\n")
        for i, atto in enumerate(atti, start=1):
            try:
                urn = build_urn_from_updated(atto)
            except KeyError:
                urn = "(tipo non mappato)"
            title = atto["titolo"][:80].replace("\n", " ")
            print(f"  [{i}/{len(atti)}] {urn}")
            print(f"          {title}")
        return 0

    print()
    today = date.today().isoformat()
    writer = RepoWriter(dataset_root)
    errors = 0
    skipped_types = 0
    skipped_urn = 0

    try:
        for i, atto in enumerate(atti, start=1):
            print(f"[{i}/{len(atti)}]")
            try:
                urn = build_urn_from_updated(atto)
            except KeyError as e:
                print(f"  SKIP (tipo non mappato): {e}")
                skipped_types += 1
                continue
            try:
                _process_atto(urn, dataset_root, xml_cache, writer, today)
            except ValueError as e:
                # URN malformato (es. autorità non-stato): skip noto, non
                # blocca persist_last_sync. Vedi issue #6.
                print(f"  SKIP (URN non supportato): {e}", file=sys.stderr)
                skipped_urn += 1
                continue
            except Exception as e:
                print(f"  ERROR su {urn}: {e}", file=sys.stderr)
                errors += 1
                continue
    finally:
        writer.save_manifest()

    if persist_last_sync and errors == 0:
        write_last_sync(dataset_root, to_date)

    stats = writer.stats
    print(
        f"\n[sync range] Done. atti={len(atti)} errors={errors} "
        f"skipped_types={skipped_types} skipped_urn={skipped_urn}"
    )
    print(f"              files: written={stats['written']} skipped={stats['skipped']}")
    return 0 if errors == 0 else 1


def sync_daily(dataset_root: Path, xml_cache: Path) -> int:
    last = read_last_sync(dataset_root)
    today_d = date.today()
    if last is None:
        from_d = today_d - timedelta(days=1)
        print(f"[sync daily] nessun last_sync.json, uso {from_d} come inizio")
    else:
        from_d = last
    if from_d >= today_d:
        print(f"[sync daily] già sincronizzato fino a {last}, niente da fare")
        return 0
    return sync_range(
        from_date=from_d,
        to_date=today_d,
        dataset_root=dataset_root,
        xml_cache=xml_cache,
        persist_last_sync=True,
    )


def read_last_sync(dataset_root: Path) -> date | None:
    path = dataset_root / LAST_SYNC_REL_PATH
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    value = raw.get("last_sync")
    if not isinstance(value, str):
        return None
    return date.fromisoformat(value)


def write_last_sync(dataset_root: Path, d: date) -> None:
    path = dataset_root / LAST_SYNC_REL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"last_sync": d.isoformat()}
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="corpus-leggi-sync")
    sub = parser.add_subparsers(dest="command", required=True)

    common_dataset = argparse.ArgumentParser(add_help=False)
    common_dataset.add_argument(
        "--dataset-root",
        type=Path,
        required=True,
        help="Path al working tree di corpus-leggi",
    )
    common_dataset.add_argument(
        "--xml-cache",
        type=Path,
        default=Path(".xml_cache"),
        help="Cartella dove memorizzare gli AKN XML scaricati",
    )

    p_atto = sub.add_parser(
        "atto",
        parents=[common_dataset],
        help="Sync di un singolo atto via URN",
    )
    p_atto.add_argument(
        "--urn",
        required=True,
        help="URN NIR canonico (es. urn:nir:stato:legge:2024-12-13;203)",
    )

    p_range = sub.add_parser(
        "range",
        parents=[common_dataset],
        help="Sync degli atti modificati in un intervallo di date",
    )
    p_range.add_argument("--from", dest="from_date", required=True, type=date.fromisoformat)
    p_range.add_argument("--to", dest="to_date", required=True, type=date.fromisoformat)
    p_range.add_argument(
        "--persist-last-sync",
        action="store_true",
        help="Aggiorna data/last_sync.json a --to se il run non ha errori",
    )
    p_range.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Processa solo i primi N atti (utile per test)",
    )
    p_range.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo elenca gli atti trovati, senza scaricare/scrivere",
    )

    sub.add_parser(
        "daily",
        parents=[common_dataset],
        help="Delta sync da last_sync.json a oggi (entry point del cron)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "atto":
        return sync_single_atto(
            urn=args.urn,
            dataset_root=args.dataset_root,
            xml_cache=args.xml_cache,
        )

    if args.command == "range":
        return sync_range(
            from_date=args.from_date,
            to_date=args.to_date,
            dataset_root=args.dataset_root,
            xml_cache=args.xml_cache,
            persist_last_sync=args.persist_last_sync,
            limit=args.limit,
            dry_run=args.dry_run,
        )

    if args.command == "daily":
        return sync_daily(
            dataset_root=args.dataset_root,
            xml_cache=args.xml_cache,
        )

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
