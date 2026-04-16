"""Conversione Akoma Ntoso XML → Markdown con front matter YAML arricchito.

Usa ``normattiva2md.convert_xml`` per il core, poi post-processa:
- strippa il front matter minimale di ondata;
- normalizza il titolo di articolo (inline o multiline) in H1 unificato;
- costruisce YAML strutturato con metadati atto + articolo.
"""

from __future__ import annotations

import re
from pathlib import Path

from normattiva2md import convert_xml

from .metadata import AttoMetadata


def strip_ondata_front_matter(md: str) -> str:
    if not md.startswith("---"):
        return md
    end = md.find("\n---", 3)
    if end == -1:
        return md
    return md[end + 4 :].lstrip("\n")


def normalize_article_heading(body: str) -> tuple[str, str]:
    """Converte il titolo dell'articolo in ``# Art. N — Rubrica`` (H1 unificato).

    Ondata produce due varianti a seconda della sorgente:
      1. ``## Art. N. - Rubrica`` (inline)
      2. ``## Art. N.`` seguito da riga vuota + rubrica su riga separata

    Ritorna (body_normalizzato, rubrica_estratta). Rubrica vuota se assente.
    """
    rubrica = ""

    def repl_inline(m: re.Match[str]) -> str:
        nonlocal rubrica
        num = m.group(1).rstrip(".").strip()
        rubrica = m.group(2).strip().rstrip(".")
        return f"# Art. {num} — {rubrica}"

    new_body, n = re.subn(
        r"^#{2,4}\s*Art\.\s*([^\n]*?)\s*-\s*([^\n]+)$",
        repl_inline,
        body,
        count=1,
        flags=re.MULTILINE,
    )
    if n:
        return new_body, rubrica

    def repl_multiline(m: re.Match[str]) -> str:
        nonlocal rubrica
        num = m.group(1).rstrip(".").strip()
        candidate = m.group(2).strip().rstrip(".")
        # Se la riga successiva è già un comma numerato o una lista, niente rubrica.
        if re.match(r"^\d+[\.\)]\s", candidate) or candidate.startswith(("- ", "* ")):
            return m.group(0)
        rubrica = candidate
        return f"# Art. {num} — {rubrica}"

    new_body, n = re.subn(
        r"^#{2,4}\s*Art\.\s*(\S+?)\.?\s*\n\s*\n([^\n]+)$",
        repl_multiline,
        body,
        count=1,
        flags=re.MULTILINE,
    )
    if n and rubrica:
        return new_body, rubrica

    new_body = re.sub(
        r"^#{2,4}\s*Art\.\s*([^\n]+?)\.?\s*$",
        lambda m: f"# Art. {m.group(1).rstrip('.').strip()}",
        body,
        count=1,
        flags=re.MULTILINE,
    )
    return new_body, rubrica


def yaml_scalar(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return f'"{escaped}"'


def build_article_md(
    atto: AttoMetadata, num: str, body_md: str, today: str
) -> tuple[str, str]:
    body = strip_ondata_front_matter(body_md)
    body, rubrica = normalize_article_heading(body)
    articolo_urn = f"{atto.urn}~art{num}"
    rubrica_yaml = yaml_scalar(rubrica) if rubrica else "null"
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
vigente: true
aggiornato_al: {today}
fonte: normattiva.it
licenza: CC-BY-4.0
---

"""
    return front + body.strip() + "\n", rubrica


def build_index_md(
    atto: AttoMetadata, articles: list[tuple[str, str]], today: str
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
    for num, rubrica in articles:
        label = f"Art. {num}" + (f" — {rubrica}" if rubrica else "")
        lines.append(f"- [{label}](art-{num}.md)")
    return front + "\n".join(lines) + "\n"


def convert_article_to_md(
    xml_path: Path, atto: AttoMetadata, num: str, today: str
) -> tuple[str, str] | None:
    """Full pipeline per un articolo: ondata + post-processing.

    Ritorna (markdown_finale, rubrica) oppure ``None`` se l'articolo non è
    presente nell'XML.
    """
    result = convert_xml(str(xml_path), article=num, quiet=True)
    if result is None:
        return None
    return build_article_md(atto, num, result.markdown, today)
