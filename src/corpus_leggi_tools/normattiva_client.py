"""Wrapper delle API Normattiva OpenData necessarie per il delta sync.

Endpoint coperti:
- download AKN di un singolo atto via URN (per ``sync atto`` e iterazione delta)
- ricerca atti aggiornati in un intervallo di date (per ``sync range``/``daily``)

Bulk load via export asincrono (API 4) non è ancora qui — arriverà in un modulo
dedicato quando lo implementiamo.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TypedDict

import requests
from normattiva2md.normattiva_api import download_akoma_ntoso_via_opendata

NORMATTIVA_API_BASE = (
    "https://api.normattiva.it/t/normattiva.api/bff-opendata/v1/api/v1"
)

DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "it-IT,it;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://dati.normattiva.it",
    "User-Agent": "corpus-leggi-bot/1.0",
}

DENOM_TO_URN_TYPE: dict[str, str] = {
    "LEGGE": "legge",
    "DECRETO-LEGGE": "decreto.legge",
    "DECRETO LEGISLATIVO": "decreto.legislativo",
    "DECRETO DEL PRESIDENTE DELLA REPUBBLICA": "decreto.presidente.repubblica",
    "DECRETO DEL PRESIDENTE DEL CONSIGLIO DEI MINISTRI": (
        "decreto.presidente.consiglio.ministri"
    ),
    "DECRETO MINISTERIALE": "decreto.ministeriale",
    "DECRETO": "decreto",
    "LEGGE COSTITUZIONALE": "legge.costituzionale",
    "COSTITUZIONE": "costituzione",
    "REGIO DECRETO": "regio.decreto",
    "REGIO DECRETO-LEGGE": "regio.decreto.legge",
    "REGIO DECRETO LEGISLATIVO": "regio.decreto.legislativo",
    "REGOLAMENTO": "regolamento",
}


class AttoAggiornato(TypedDict):
    """Atto restituito da ``POST /ricerca/aggiornati`` (campi normalizzati)."""

    codice_redazionale: str
    denominazione_atto: str
    numero_provvedimento: str
    anno_provvedimento: int
    mese_provvedimento: int
    giorno_provvedimento: int
    data_ultima_modifica: str
    titolo: str


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


def search_updated(
    from_date: date,
    to_date: date,
    *,
    timeout: float = 30.0,
) -> list[AttoAggiornato]:
    """Chiama ``POST /ricerca/aggiornati`` e ritorna la lista normalizzata.

    Limiti documentati dall'IPZS:
    - intervallo massimo 12 mesi (errore 1501)
    - risultati massimi 7000 atti (errore 1502)
    - ``from_date`` non deve superare ``to_date`` (errore 1503)

    Valida i casi base client-side per fallire presto con messaggi chiari.
    """
    if from_date > to_date:
        raise ValueError(
            f"from_date ({from_date}) è successivo a to_date ({to_date})"
        )
    if (to_date - from_date).days > 366:
        raise ValueError(
            f"intervallo {from_date}→{to_date} supera 12 mesi (errore API 1501)"
        )

    url = f"{NORMATTIVA_API_BASE}/ricerca/aggiornati"
    payload = {
        "dataInizioAggiornamento": f"{from_date.isoformat()}T00:00:00.000Z",
        "dataFineAggiornamento": f"{to_date.isoformat()}T00:00:00.000Z",
    }
    response = requests.post(
        url, json=payload, headers=DEFAULT_HEADERS, timeout=timeout
    )
    response.raise_for_status()
    data = response.json()
    return [_normalize_atto_aggiornato(a) for a in data.get("listaAtti", [])]


def _normalize_atto_aggiornato(raw: dict[str, object]) -> AttoAggiornato:
    return {
        "codice_redazionale": str(raw.get("codiceRedazionale", "")),
        "denominazione_atto": str(raw.get("denominazioneAtto", "")),
        "numero_provvedimento": str(raw.get("numeroProvvedimento", "")),
        "anno_provvedimento": int(str(raw.get("annoProvvedimento", "0"))),
        "mese_provvedimento": int(str(raw.get("meseProvvedimento", "0"))),
        "giorno_provvedimento": int(str(raw.get("giornoProvvedimento", "0"))),
        "data_ultima_modifica": str(raw.get("dataUltimaModifica", "")),
        "titolo": str(raw.get("titoloAtto", "")),
    }


def build_urn_from_updated(atto: AttoAggiornato) -> str:
    """Costruisce l'URN NIR canonico dall'atto ritornato da /ricerca/aggiornati.

    Solleva ``KeyError`` se la denominazione non è mappata (tipo atto non gestito).
    """
    denom = atto["denominazione_atto"]
    if denom not in DENOM_TO_URN_TYPE:
        raise KeyError(f"denominazione atto non mappata: {denom!r}")
    urn_type = DENOM_TO_URN_TYPE[denom]
    data_iso = (
        f"{atto['anno_provvedimento']:04d}-"
        f"{atto['mese_provvedimento']:02d}-"
        f"{atto['giorno_provvedimento']:02d}"
    )
    return f"urn:nir:stato:{urn_type}:{data_iso};{atto['numero_provvedimento']}"
