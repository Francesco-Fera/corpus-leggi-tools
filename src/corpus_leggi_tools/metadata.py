"""Estrazione metadati strutturati da un documento Akoma Ntoso Normattiva.

Combina i metadati che già espone ``normattiva2md`` (dataGU, codiceRedaz,
dataVigenza, urn_nir) con la parte mancante per il nostro front matter:
tipo, denominazione, data, anno, numero, titolo pulito.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from normattiva2md.constants import AKN_NAMESPACE
from normattiva2md.xml_parser import extract_metadata_from_xml

URN_TYPE_TO_DENOM: dict[str, tuple[str, str]] = {
    "legge": ("LEGGE", "legge"),
    "decreto.legge": ("DECRETO-LEGGE", "decreto-legge"),
    "decreto.legislativo": ("DECRETO LEGISLATIVO", "decreto-legislativo"),
    "decreto.presidente.repubblica": (
        "DECRETO DEL PRESIDENTE DELLA REPUBBLICA",
        "decreto-presidente-repubblica",
    ),
    "decreto.presidente.consiglio.ministri": (
        "DECRETO DEL PRESIDENTE DEL CONSIGLIO DEI MINISTRI",
        "dpcm",
    ),
    "decreto.ministeriale": ("DECRETO MINISTERIALE", "decreto-ministeriale"),
    "decreto": ("DECRETO", "decreto"),
    "legge.costituzionale": ("LEGGE COSTITUZIONALE", "legge-costituzionale"),
    "costituzione": ("COSTITUZIONE", "costituzione"),
    "regio.decreto": ("REGIO DECRETO", "regio-decreto"),
    "regio.decreto.legge": ("REGIO DECRETO-LEGGE", "regio-decreto-legge"),
    "regio.decreto.legislativo": (
        "REGIO DECRETO LEGISLATIVO",
        "regio-decreto-legislativo",
    ),
    "regolamento": ("REGOLAMENTO", "regolamento"),
}


@dataclass(frozen=True)
class AttoMetadata:
    urn: str
    tipo: str
    denominazione: str
    slug_tipo: str
    data: str
    anno: int
    numero: str
    titolo: str
    codice_redazionale: str
    data_gu: str
    data_vigenza: str
    url: str
    url_xml: str
    url_permanente: str


def parse_urn(urn: str) -> tuple[str, str, str]:
    """Estrae (tipo, data ISO, numero) da un URN NIR canonico.

    Esempio: ``urn:nir:stato:legge:2024-12-13;203`` → ``("legge", "2024-12-13", "203")``.
    """
    m = re.match(r"urn:nir:stato:([^:]+):(\d{4}-\d{2}-\d{2});([^~!@]+)", urn)
    if not m:
        raise ValueError(f"URN non valido: {urn}")
    return m.group(1), m.group(2), m.group(3)


def extract_act_title(root: ET.Element) -> str:
    el = root.find(".//akn:docTitle", AKN_NAMESPACE)
    if el is None:
        return ""
    return re.sub(r"\s+", " ", " ".join(el.itertext())).strip()


def clean_title(title: str, codice_redaz: str) -> str:
    if codice_redaz:
        title = re.sub(
            rf"\s*\(\s*{re.escape(codice_redaz)}\s*\)\s*\.?\s*$", "", title
        )
    return title.rstrip(" .")


def build_metadata_from_xml(xml_path: str | Path, fallback_url: str = "") -> AttoMetadata:
    root = ET.parse(str(xml_path)).getroot()
    base = extract_metadata_from_xml(root)
    urn = base.get("urn_nir", "")
    if not urn:
        raise ValueError(f"URN NIR non estratto dal meta del file {xml_path}")
    tipo, data_iso, numero = parse_urn(urn)
    denom, slug = URN_TYPE_TO_DENOM.get(tipo, (tipo.upper(), tipo.replace(".", "-")))
    titolo = clean_title(extract_act_title(root), base.get("codiceRedaz", ""))
    return AttoMetadata(
        urn=urn,
        tipo=tipo,
        denominazione=denom,
        slug_tipo=slug,
        data=data_iso,
        anno=int(data_iso[:4]),
        numero=numero,
        titolo=titolo,
        codice_redazionale=base.get("codiceRedaz", ""),
        data_gu=base.get("dataGU", ""),
        data_vigenza=base.get("dataVigenza", ""),
        url=base.get("url", fallback_url),
        url_xml=base.get("url_xml", ""),
        url_permanente=base.get("url_permanente", ""),
    )


def list_article_eids(root: ET.Element) -> list[str]:
    return [
        eid
        for el in root.findall(".//akn:article", AKN_NAMESPACE)
        if (eid := el.get("eId"))
    ]


def eid_to_article_num(eid: str) -> str:
    """``art_2-bis`` → ``2bis``."""
    return eid.removeprefix("art_").replace("-", "")


def atto_directory(atto: AttoMetadata) -> str:
    """Path relativo (POSIX) della cartella dell'atto dentro il dataset."""
    return (
        f"leggi/{atto.slug_tipo}/{atto.anno}/"
        f"{atto.slug_tipo}_{atto.data_gu}_{atto.numero}"
    )
