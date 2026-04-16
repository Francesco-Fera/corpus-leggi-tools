"""Entry point ``corpus-leggi-sync``.

Per ora implementa una sola subcommand: ``atto --urn <URN>`` che scarica,
converte e scrive nel dataset un singolo atto (vertical slice del delta).
Il sync delta completo (ricerca aggiornati + loop) sarà aggiunto in seguito.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

from .converter import build_index_md, convert_article_to_md
from .metadata import (
    AttoMetadata,
    atto_directory,
    build_metadata_from_xml,
    eid_to_article_num,
    list_article_eids,
)
from .normattiva_client import build_url_from_urn, download_akn_by_urn
from .repo_writer import RepoWriter


def _xml_cache_path(xml_cache: Path, atto: AttoMetadata) -> Path:
    return xml_cache / f"{atto.slug_tipo}_{atto.data_gu}_{atto.numero}.xml"


def _download_if_needed(urn: str, xml_cache: Path) -> Path:
    """Scarica l'AKN in un path provvisorio se non in cache, poi rinomina.

    Il nome finale richiede i metadati (slug/numero) estratti dall'XML stesso,
    quindi usiamo un path temporaneo e rinominiamo al volo.
    """
    tmp_path = xml_cache / "_tmp_download.xml"
    xml_cache.mkdir(parents=True, exist_ok=True)
    if tmp_path.exists():
        tmp_path.unlink()
    if not download_akn_by_urn(urn, tmp_path, quiet=False):
        raise RuntimeError(f"Download fallito per URN: {urn}")
    return tmp_path


def sync_single_atto(
    urn: str,
    dataset_root: Path,
    xml_cache: Path,
) -> int:
    print(f"[sync] URN: {urn}")
    tmp_xml = _download_if_needed(urn, xml_cache)
    atto = build_metadata_from_xml(tmp_xml, fallback_url=build_url_from_urn(urn))
    final_xml = _xml_cache_path(xml_cache, atto)
    tmp_xml.replace(final_xml)

    print(f"[sync] Atto: {atto.denominazione} {atto.data} n. {atto.numero}")
    print(f"[sync] Titolo: {atto.titolo}")

    root = ET.parse(final_xml).getroot()
    eids = list_article_eids(root)
    print(f"[sync] Articoli nel documento: {len(eids)}")

    today = date.today().isoformat()
    writer = RepoWriter(dataset_root)
    rel_dir = atto_directory(atto)
    articles_meta: list[tuple[str, str]] = []

    for eid in eids:
        num = eid_to_article_num(eid)
        result = convert_article_to_md(final_xml, atto, num, today)
        if result is None:
            print(f"       ! art {num}: non trovato (skip)")
            continue
        md, rubrica = result
        rel_path = f"{rel_dir}/art-{num}.md"
        changed = writer.write_if_changed(rel_path, md)
        articles_meta.append((num, rubrica))
        marker = "✓" if changed else "="
        print(f"       {marker} {rel_path}")

    index_md = build_index_md(atto, articles_meta, today)
    writer.write_if_changed(f"{rel_dir}/_index.md", index_md)
    writer.save_manifest()

    stats = writer.stats
    print(f"\n[sync] Done. written={stats['written']} skipped={stats['skipped']}")
    print(f"[sync] Dataset dir: {dataset_root / rel_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="corpus-leggi-sync")
    sub = parser.add_subparsers(dest="command", required=True)

    p_atto = sub.add_parser("atto", help="Sync di un singolo atto via URN")
    p_atto.add_argument(
        "--urn",
        required=True,
        help="URN NIR canonico (es. urn:nir:stato:legge:2024-12-13;203)",
    )
    p_atto.add_argument(
        "--dataset-root",
        type=Path,
        required=True,
        help="Path al working tree di corpus-leggi",
    )
    p_atto.add_argument(
        "--xml-cache",
        type=Path,
        default=Path(".xml_cache"),
        help="Cartella dove memorizzare gli AKN XML scaricati (default: .xml_cache)",
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

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
