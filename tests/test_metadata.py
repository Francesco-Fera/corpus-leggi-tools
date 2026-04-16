from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from corpus_leggi_tools.metadata import (
    URN_TYPE_TO_DENOM,
    AttoMetadata,
    atto_directory,
    clean_title,
    eid_to_article_num,
    extract_act_title,
    list_article_eids,
    parse_urn,
)


AKN_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<akomaNtoso xmlns="http://docs.oasis-open.org/legaldocml/ns/akn/3.0">
  <act>
    <preface>
      <docTitle>Titolo di    test   con   spazi</docTitle>
    </preface>
    <body>
      <article eId="art_1"><num>Art. 1</num></article>
      <article eId="art_2"><num>Art. 2</num></article>
      <article eId="art_2-bis"><num>Art. 2-bis</num></article>
      <article eId="art_64-quater"><num>Art. 64-quater</num></article>
    </body>
  </act>
</akomaNtoso>
"""


def _demo_atto(**overrides: object) -> AttoMetadata:
    defaults: dict[str, object] = {
        "urn": "urn:nir:stato:legge:2024-12-13;203",
        "tipo": "legge",
        "denominazione": "LEGGE",
        "slug_tipo": "legge",
        "data": "2024-12-13",
        "anno": 2024,
        "numero": "203",
        "titolo": "Disposizioni in materia di lavoro",
        "codice_redazionale": "24G00218",
        "data_gu": "20241228",
        "data_vigenza": "20260416",
        "url": "",
        "url_xml": "",
        "url_permanente": "",
    }
    defaults.update(overrides)
    return AttoMetadata(**defaults)  # type: ignore[arg-type]


class TestParseUrn:
    def test_legge(self) -> None:
        assert parse_urn("urn:nir:stato:legge:2024-12-13;203") == (
            "legge",
            "2024-12-13",
            "203",
        )

    def test_decreto_legislativo(self) -> None:
        assert parse_urn("urn:nir:stato:decreto.legislativo:2005-03-07;82") == (
            "decreto.legislativo",
            "2005-03-07",
            "82",
        )

    def test_decreto_legge(self) -> None:
        assert parse_urn("urn:nir:stato:decreto.legge:2024-12-27;208") == (
            "decreto.legge",
            "2024-12-27",
            "208",
        )

    def test_with_article_suffix_is_stripped(self) -> None:
        assert parse_urn("urn:nir:stato:legge:2024-12-13;203~art5") == (
            "legge",
            "2024-12-13",
            "203",
        )

    def test_with_vigenza_suffix_is_stripped(self) -> None:
        assert parse_urn("urn:nir:stato:legge:2024-12-13;203!vig=2025-01-01") == (
            "legge",
            "2024-12-13",
            "203",
        )

    def test_with_originale_suffix_is_stripped(self) -> None:
        assert parse_urn("urn:nir:stato:legge:2024-12-13;203@originale") == (
            "legge",
            "2024-12-13",
            "203",
        )

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="URN non valido"):
            parse_urn("not-a-urn")

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="URN non valido"):
            parse_urn("")


class TestCleanTitle:
    def test_removes_codice_redazionale(self) -> None:
        assert (
            clean_title("Disposizioni in materia di lavoro. (24G00218)", "24G00218")
            == "Disposizioni in materia di lavoro"
        )

    def test_no_codice(self) -> None:
        assert clean_title("Titolo pulito", "") == "Titolo pulito"

    def test_empty_title(self) -> None:
        assert clean_title("", "24G00218") == ""

    def test_codice_not_in_title_leaves_untouched(self) -> None:
        assert clean_title("Altro titolo senza codice", "24G00218") == (
            "Altro titolo senza codice"
        )

    def test_strips_trailing_dot_even_without_codice(self) -> None:
        assert clean_title("Titolo.", "") == "Titolo"

    def test_handles_codice_with_extra_spaces(self) -> None:
        assert (
            clean_title("Titolo (  24G00218  ).", "24G00218") == "Titolo"
        )


class TestEidToArticleNum:
    def test_simple(self) -> None:
        assert eid_to_article_num("art_1") == "1"
        assert eid_to_article_num("art_42") == "42"

    def test_bis(self) -> None:
        assert eid_to_article_num("art_3-bis") == "3bis"
        assert eid_to_article_num("art_14-bis") == "14bis"

    def test_ter(self) -> None:
        assert eid_to_article_num("art_3-ter") == "3ter"

    def test_quater(self) -> None:
        assert eid_to_article_num("art_64-quater") == "64quater"

    def test_sexies(self) -> None:
        assert eid_to_article_num("art_62-sexies") == "62sexies"


class TestAttoDirectory:
    def test_legge(self) -> None:
        atto = _demo_atto()
        assert atto_directory(atto) == "leggi/legge/2024/legge_20241228_203"

    def test_decreto_legislativo(self) -> None:
        atto = _demo_atto(
            tipo="decreto.legislativo",
            denominazione="DECRETO LEGISLATIVO",
            slug_tipo="decreto-legislativo",
            data="2005-03-07",
            anno=2005,
            numero="82",
            data_gu="20050516",
        )
        assert (
            atto_directory(atto)
            == "leggi/decreto-legislativo/2005/decreto-legislativo_20050516_82"
        )


class TestUrnTypeMapping:
    def test_known_types(self) -> None:
        assert URN_TYPE_TO_DENOM["legge"] == ("LEGGE", "legge")
        assert URN_TYPE_TO_DENOM["decreto.legislativo"] == (
            "DECRETO LEGISLATIVO",
            "decreto-legislativo",
        )
        assert URN_TYPE_TO_DENOM["decreto.presidente.repubblica"][1] == (
            "decreto-presidente-repubblica"
        )
        assert URN_TYPE_TO_DENOM["decreto.presidente.consiglio.ministri"][1] == "dpcm"

    def test_denominazione_maiuscolo(self) -> None:
        for denom, _ in URN_TYPE_TO_DENOM.values():
            assert denom == denom.upper(), f"denominazione non maiuscola: {denom!r}"

    def test_dpr_both_urn_forms_map_to_same_dir(self) -> None:
        # Normattiva restituisce 'decreto.del.presidente.della.repubblica' nei
        # meta AKN ma accetta 'decreto.presidente.repubblica' come handle URL.
        # Entrambe devono mappare allo stesso slug/denominazione.
        assert (
            URN_TYPE_TO_DENOM["decreto.presidente.repubblica"]
            == URN_TYPE_TO_DENOM["decreto.del.presidente.della.repubblica"]
        )

    def test_dpcm_both_urn_forms_map_to_same_dir(self) -> None:
        assert (
            URN_TYPE_TO_DENOM["decreto.presidente.consiglio.ministri"]
            == URN_TYPE_TO_DENOM["decreto.del.presidente.del.consiglio.dei.ministri"]
        )


class TestXMLExtraction:
    def test_list_article_eids_in_order(self) -> None:
        root = ET.fromstring(AKN_SAMPLE)
        assert list_article_eids(root) == [
            "art_1",
            "art_2",
            "art_2-bis",
            "art_64-quater",
        ]

    def test_extract_act_title_normalizes_whitespace(self) -> None:
        root = ET.fromstring(AKN_SAMPLE)
        assert extract_act_title(root) == "Titolo di test con spazi"

    def test_extract_act_title_missing_returns_empty(self) -> None:
        empty_akn = """<akomaNtoso xmlns="http://docs.oasis-open.org/legaldocml/ns/akn/3.0"><act><body/></act></akomaNtoso>"""
        root = ET.fromstring(empty_akn)
        assert extract_act_title(root) == ""
