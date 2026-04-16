"""Conversione Akoma Ntoso XML → Markdown con front matter YAML arricchito.

Usa ``normattiva2md.convert_xml`` per il core, poi post-processa:
- strippa il front matter minimale di ondata;
- normalizza il titolo di articolo (inline o multiline) in H1 unificato;
- costruisce YAML strutturato con metadati atto + articolo.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

from normattiva2md import convert_xml

from .metadata import AttoMetadata


class ArticoloMeta(NamedTuple):
    """Metadati post-conversione di un articolo per consumo dall'indexer."""

    rubrica: str          # vuota se articolo abrogato o senza rubrica
    abrogato: bool
    abrogato_da: str | None


_ABROGATION_RE = re.compile(
    r"^\(\(\s*ARTICOLO\s+(?:ABROGATO|SOPPRESSO)\s+DAL\s+(.+?)\s*\)\)\.?\s*$",
    re.IGNORECASE,
)


def detect_abrogation(rubrica_raw: str) -> tuple[bool, str | None]:
    """Rileva rubriche prodotte da ondata per articoli abrogati/soppressi.

    Il pattern è ``((ARTICOLO ABROGATO DAL <atto>))`` (oppure ``SOPPRESSO``).
    Ritorna ``(True, "<atto>")`` se matcha, ``(False, None)`` altrimenti.

    Quando abrogato la rubrica originale va scartata: rappresentiamo il fatto
    con un campo ``abrogato_da`` dedicato + ``vigente: false``.
    """
    m = _ABROGATION_RE.match(rubrica_raw.strip())
    if m is None:
        return False, None
    return True, m.group(1).strip().rstrip(".")


def strip_ondata_front_matter(md: str) -> str:
    if not md.startswith("---"):
        return md
    end = md.find("\n---", 3)
    if end == -1:
        return md
    return md[end + 4 :].lstrip("\n")


_EXTS = "bis|ter|quater|quinquies|sexies|septies|octies|novies|decies"
# Il numero articolo nel raw ondata: "3", "3-bis", "64-quater", "3 bis"...
_ARTICLE_NUM_PATTERN = rf"\d+(?:[-\s](?:{_EXTS}))*"


def format_article_display_num(num: str) -> str:
    """``3bis`` → ``3-bis`` per rendering leggibile nel titolo H1."""
    m = re.match(rf"^(\d+)({_EXTS})$", num)
    return f"{m.group(1)}-{m.group(2)}" if m else num


def normalize_article_heading(body: str, num: str) -> tuple[str, str]:
    """Converte il titolo dell'articolo in ``# Art. {display_num} — Rubrica``.

    Ondata produce due varianti a seconda della sorgente:
      1. ``## Art. N. - Rubrica`` (inline, separatore ``\\s-\\s``)
      2. ``## Art. N.`` seguito da riga vuota + rubrica

    Il numero può contenere ``-bis``, ``-ter``, ecc. (es. ``Art. 3-bis. - …``).
    Il separatore verso la rubrica richiede spazi attorno al ``-`` per
    distinguerlo dal dash interno al numero.

    ``num`` è la forma compatta (es. ``3bis``); usiamo la sua display form
    nel titolo rigenerato — ignoriamo il numero presente nel raw.

    Ritorna (body_normalizzato, rubrica_estratta). Rubrica vuota se assente.
    """
    display = format_article_display_num(num)
    rubrica = ""

    inline = re.compile(
        rf"^#{{2,4}}\s*Art\.\s*{_ARTICLE_NUM_PATTERN}\s*\.?\s+-\s+([^\n]+)$",
        re.MULTILINE,
    )
    m = inline.search(body)
    if m:
        rubrica = m.group(1).strip().rstrip(".")
        body = inline.sub(f"# Art. {display} — {rubrica}", body, count=1)
        return body, rubrica

    multiline = re.compile(
        rf"^(#{{2,4}}\s*Art\.\s*{_ARTICLE_NUM_PATTERN}\s*\.?\s*)\n\s*\n([^\n]+)$",
        re.MULTILINE,
    )
    m = multiline.search(body)
    if m:
        candidate = m.group(2).strip().rstrip(".")
        is_comma_or_list = bool(
            re.match(r"^\d+[\.\)]\s", candidate)
        ) or candidate.startswith(("- ", "* "))
        if not is_comma_or_list:
            rubrica = candidate
            body = multiline.sub(f"# Art. {display} — {rubrica}", body, count=1)
            return body, rubrica

    solo = re.compile(
        rf"^#{{2,4}}\s*Art\.\s*{_ARTICLE_NUM_PATTERN}\s*\.?\s*$",
        re.MULTILINE,
    )
    body = solo.sub(f"# Art. {display}", body, count=1)
    return body, rubrica


def yaml_scalar(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return f'"{escaped}"'


def build_article_md(
    atto: AttoMetadata,
    num: str,
    body_md: str,
    today: str,
    *,
    vigenza_inizio: str | None = None,
) -> tuple[str, ArticoloMeta]:
    body = strip_ondata_front_matter(body_md)
    body, rubrica_raw = normalize_article_heading(body, num)
    abrogato, abrogato_da = detect_abrogation(rubrica_raw) if rubrica_raw else (False, None)

    if abrogato:
        # Gli articoli abrogati non hanno contenuto oltre al marker di
        # abrogazione: rimpiazziamo l'intero body con un H1 pulito + callout.
        display = format_article_display_num(num)
        body = (
            f"# Art. {display}\n\n"
            f"> **Articolo abrogato** — {abrogato_da}\n"
        )
        rubrica_for_fm = ""
    else:
        rubrica_for_fm = rubrica_raw

    articolo_urn = f"{atto.urn}~art{num}"
    rubrica_yaml = yaml_scalar(rubrica_for_fm) if rubrica_for_fm else "null"
    vigenza_line = (
        f"  vigenza_inizio: {yaml_scalar(vigenza_inizio)}\n" if vigenza_inizio else ""
    )
    abrogato_line = (
        f"  abrogato_da: {yaml_scalar(abrogato_da)}\n" if abrogato and abrogato_da else ""
    )
    vigente_yaml = "false" if abrogato else "true"
    front = f"""---
atto:
  titolo: {yaml_scalar(atto.titolo)}
  tipo: {atto.denominazione}
  numero: "{atto.numero}"
  data: {atto.data}
  anno: {atto.anno}
  codice_redazionale: {atto.codice_redazionale}
  urn: {atto.urn}
articolo:
  numero: "{num}"
  urn: {articolo_urn}
  rubrica: {rubrica_yaml}
{vigenza_line}{abrogato_line}vigente: {vigente_yaml}
aggiornato_al: {today}
fonte: normattiva.it
licenza: CC-BY-4.0
---

"""
    meta = ArticoloMeta(
        rubrica=rubrica_for_fm, abrogato=abrogato, abrogato_da=abrogato_da
    )
    return front + body.strip() + "\n", meta


def build_index_md(
    atto: AttoMetadata,
    articles: list[tuple[str, ArticoloMeta]],
    today: str,
) -> str:
    front = f"""---
titolo: {yaml_scalar(atto.titolo)}
tipo: {atto.denominazione}
numero: "{atto.numero}"
data: {atto.data}
anno: {atto.anno}
codice_redazionale: {atto.codice_redazionale}
urn: {atto.urn}
vigente: true
numero_articoli: {len(articles)}
aggiornato_al: {today}
fonte: normattiva.it
licenza: CC-BY-4.0
---

# {atto.denominazione} {atto.data} — n. {atto.numero}

**{atto.titolo}**

> URN: `{atto.urn}`
> [Fonte Normattiva]({atto.url_permanente or atto.url})

## Articoli

"""
    lines: list[str] = []
    for num, meta in articles:
        display = format_article_display_num(num)
        if meta.abrogato:
            label = f"Art. {display} _(abrogato)_"
        elif meta.rubrica:
            label = f"Art. {display} — {meta.rubrica}"
        else:
            label = f"Art. {display}"
        lines.append(f"- [{label}](art-{num}.md)")
    return front + "\n".join(lines) + "\n"


def convert_article_to_md(
    xml_path: Path,
    atto: AttoMetadata,
    num: str,
    today: str,
    *,
    vigenza_inizio: str | None = None,
) -> tuple[str, ArticoloMeta] | None:
    """Full pipeline per un articolo: ondata + post-processing.

    Ritorna ``(markdown_finale, ArticoloMeta)`` oppure ``None`` se l'articolo
    non è presente nell'XML.
    """
    result = convert_xml(str(xml_path), article=num, quiet=True)
    if result is None:
        return None
    return build_article_md(
        atto, num, result.markdown, today, vigenza_inizio=vigenza_inizio
    )
