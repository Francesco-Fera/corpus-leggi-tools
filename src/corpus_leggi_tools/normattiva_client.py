"""Wrapper delle API Normattiva OpenData.

Endpoint coperti:
- download AKN di un singolo atto via URN (per ``sync atto`` e iterazione delta)
- ricerca atti aggiornati in un intervallo di date (per ``sync range``/``daily``)
- export asincrono (API 4): avvia ricerca → conferma → polling → download ZIP
  (per ``bulk_load`` di un tipo atto × range anni)
"""

from __future__ import annotations

import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, TypedDict

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

# Codici "tipologica" IPZS (usati nel campo ``codice_tipo_provvedimento`` dei
# filtriMap nella ricerca avanzata / asincrona). Li mappiamo al tipo URN per
# usarli coerentemente lato bulk load.
TIPO_PROV_CODES: dict[str, str] = {
    "COS": "costituzione",
    "PLE": "legge",
    "PLC": "legge.costituzionale",
    "PDL": "decreto.legge",
    "PLL": "decreto.legislativo",
    "PPR": "decreto.presidente.repubblica",
    "PCM_DPC": "decreto.presidente.consiglio.ministri",
    "PDM": "decreto.ministeriale",
    "DCT": "decreto",
    "D10": "regolamento",
    "PRD": "regio.decreto",
    "PRL": "regio.decreto.legge",
    "RDL": "regio.decreto.legislativo",
}

# Polling dell'export asincrono: il token scade in ~10 minuti lato IPZS.
ASYNC_POLL_INTERVAL_SEC = 5.0
ASYNC_POLL_MAX_WAIT_SEC = 600.0


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


# ---------------------------------------------------------------------------
# API 4 — Export asincrono per bulk load
# ---------------------------------------------------------------------------


class AsyncSearchParams(TypedDict, total=False):
    """Parametri della ricerca asincrona (body di ``parametriRicerca``).

    Tutti i campi sono opzionali: IPZS li filtra quando assenti. Le chiavi
    seguono il contratto dell'API IPZS, non normalizzato (camelCase).
    """

    classeProvvedimento: str
    dataInizioEmanazione: str
    dataFineEmanazione: str
    filtriMap: dict[str, Any]


def _extract_token(response_body: Any) -> str | None:
    """Trova il token UUID nella risposta di ``nuova-ricerca``.

    La forma esatta non è documentata: proviamo le varianti più plausibili
    (top-level stringa, ``{"token": ...}``, ``{"data": {"token": ...}}``,
    ``{"data": "..."}``).
    """
    if isinstance(response_body, str):
        return response_body.strip() or None
    if isinstance(response_body, dict):
        for key in ("token", "taskId", "uuid", "id"):
            val = response_body.get(key)
            if isinstance(val, str) and val:
                return val
        data = response_body.get("data")
        if isinstance(data, str) and data:
            return data
        if isinstance(data, dict):
            return _extract_token(data)
    return None


def async_search_start(
    params: AsyncSearchParams,
    *,
    formato: str = "AKN",
    tipo_ricerca: str = "A",
    modalita: str = "C",
    data_vigenza: str | None = None,
    timeout: float = 30.0,
) -> str:
    """Avvia un export asincrono. Ritorna il token della richiesta.

    ``formato``: ``AKN`` (default, quello che ci serve), ``HTML``, ``JSON``, ``XML``,
    ``URI``, ``PDF``, ``EPUB``, ``RTF``.
    ``tipo_ricerca``: ``A`` avanzata (usa ``parametriRicerca``), ``S`` semplice.
    ``modalita``: ``C`` come da esempio IPZS (significato non documentato).
    ``data_vigenza``: default = oggi in ISO ``YYYY-MM-DD``.
    """
    url = f"{NORMATTIVA_API_BASE}/ricerca-asincrona/nuova-ricerca"
    payload = {
        "formato": formato,
        "tipoRicerca": tipo_ricerca,
        "modalita": modalita,
        "dataVigenza": data_vigenza or date.today().isoformat(),
        "parametriRicerca": dict(params),
    }
    response = requests.post(
        url, json=payload, headers=DEFAULT_HEADERS, timeout=timeout
    )
    response.raise_for_status()
    try:
        body: Any = response.json()
    except ValueError:
        body = response.text
    token = _extract_token(body)
    if not token:
        raise RuntimeError(
            f"nuova-ricerca: token non trovato nella risposta: {body!r}"
        )
    return token


def async_search_confirm(token: str, *, timeout: float = 30.0) -> None:
    """Conferma la ricerca asincrona (sblocca l'elaborazione lato IPZS)."""
    url = f"{NORMATTIVA_API_BASE}/ricerca-asincrona/conferma-ricerca"
    response = requests.put(
        url, json={"token": token}, headers=DEFAULT_HEADERS, timeout=timeout
    )
    response.raise_for_status()


def async_search_poll(
    token: str,
    *,
    poll_interval: float = ASYNC_POLL_INTERVAL_SEC,
    max_wait: float = ASYNC_POLL_MAX_WAIT_SEC,
    timeout: float = 30.0,
    quiet: bool = False,
) -> str:
    """Polla ``check-status`` fino a ricevere ``303``. Ritorna l'URL di download.

    Stati documentati IPZS:
      1=attesa, 2=in elaborazione, 3=pronta, 5=sovraccarico, 6=tempi lunghi.

    Solleva ``TimeoutError`` se ``max_wait`` viene superato (token scade a ~10min),
    ``RuntimeError`` se un ``303`` non porta l'header ``x-ipzs-location``.
    """
    url = f"{NORMATTIVA_API_BASE}/ricerca-asincrona/check-status/{token}"
    deadline = time.monotonic() + max_wait
    attempt = 0
    while True:
        attempt += 1
        # allow_redirects=False per intercettare il 303 e leggere
        # ``x-ipzs-location`` (altrimenti requests segue il redirect e perdiamo
        # l'header).
        response = requests.get(
            url, headers=DEFAULT_HEADERS, timeout=timeout, allow_redirects=False
        )
        if response.status_code == 303:
            location = response.headers.get("x-ipzs-location") or response.headers.get(
                "Location"
            )
            if not location:
                raise RuntimeError(
                    "check-status: 303 senza header x-ipzs-location / Location"
                )
            if not quiet:
                print(
                    f"  [poll attempt={attempt}] pronta → {location}", file=sys.stderr
                )
            return location
        if response.status_code != 200:
            response.raise_for_status()
        if not quiet:
            print(
                f"  [poll attempt={attempt}] stato intermedio, ri-provo tra {poll_interval}s",
                file=sys.stderr,
            )
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"polling token={token} scaduto dopo {max_wait}s"
            )
        time.sleep(poll_interval)


def download_file(
    url: str,
    output_path: Path,
    *,
    chunk_size: int = 1024 * 1024,
    timeout: float = 300.0,
) -> Path:
    """Scarica un file (ZIP/binary) da URL assoluto. Crea la directory parent.

    ``Content-Type: application/json`` in DEFAULT_HEADERS non interferisce con
    le GET (serve solo come fallback lato server), quindi riusiamo gli header
    standard per coerenza.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(
        url, headers=DEFAULT_HEADERS, stream=True, timeout=timeout
    ) as response:
        response.raise_for_status()
        with open(output_path, "wb") as fh:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    fh.write(chunk)
    return output_path


def async_export_to_zip(
    params: AsyncSearchParams,
    output_zip: Path,
    *,
    formato: str = "AKN",
    tipo_ricerca: str = "A",
    modalita: str = "C",
    data_vigenza: str | None = None,
    poll_interval: float = ASYNC_POLL_INTERVAL_SEC,
    max_wait: float = ASYNC_POLL_MAX_WAIT_SEC,
    timeout: float = 60.0,
    download_timeout: float = 600.0,
    quiet: bool = False,
) -> Path:
    """Full flow: avvia ricerca → conferma → polling → download ZIP.

    Incapsula i 3 step dell'API 4 + il download finale. Usato da ``bulk_load``
    per materializzare un chunk di atti (es. leggi 2020-2024) in un unico ZIP.
    """
    if not quiet:
        print(f"[async export] start: formato={formato} params={params}", file=sys.stderr)
    token = async_search_start(
        params,
        formato=formato,
        tipo_ricerca=tipo_ricerca,
        modalita=modalita,
        data_vigenza=data_vigenza,
        timeout=timeout,
    )
    if not quiet:
        print(f"[async export] token={token} → conferma", file=sys.stderr)
    async_search_confirm(token, timeout=timeout)
    download_url = async_search_poll(
        token,
        poll_interval=poll_interval,
        max_wait=max_wait,
        timeout=timeout,
        quiet=quiet,
    )
    if not quiet:
        print(f"[async export] download {download_url} → {output_zip}", file=sys.stderr)
    return download_file(download_url, output_zip, timeout=download_timeout)
