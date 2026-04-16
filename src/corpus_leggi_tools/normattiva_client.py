"""Wrapper minimale delle API Normattiva OpenData.

Per ora espone solo il download AKN di un singolo atto via URN (utile per il
delta sync). Le altre API (ricerca aggiornati, export asincrono, tipologiche)
saranno aggiunte quando servono per sync_delta / bulk_load.
"""

from __future__ import annotations

from pathlib import Path

from normattiva2md.normattiva_api import download_akoma_ntoso_via_opendata


def build_url_from_urn(urn: str) -> str:
    return f"https://www.normattiva.it/uri-res/N2Ls?{urn}"


def download_akn_by_urn(
    urn: str,
    output_path: Path,
    *,
    quiet: bool = True,
) -> bool:
    """Scarica il documento Akoma Ntoso dell'atto identificato da URN.

    Usa l'API OpenData IPZS (no auth). ``output_path`` è un path di file,
    la cartella viene creata se non esiste.

    Ritorna True se il download è andato a buon fine.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    url = build_url_from_urn(urn)
    success, _, _ = download_akoma_ntoso_via_opendata(
        url, str(output_path), session=None, quiet=quiet
    )
    return bool(success)
