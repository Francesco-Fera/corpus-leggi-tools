from __future__ import annotations

from datetime import date

import pytest

from corpus_leggi_tools.normattiva_client import (
    DENOM_TO_URN_TYPE,
    AttoAggiornato,
    build_url_from_urn,
    build_urn_from_updated,
    search_updated,
)


def _make_atto(**overrides: object) -> AttoAggiornato:
    defaults: AttoAggiornato = {
        "codice_redazionale": "24G00218",
        "denominazione_atto": "LEGGE",
        "numero_provvedimento": "203",
        "anno_provvedimento": 2024,
        "mese_provvedimento": 12,
        "giorno_provvedimento": 13,
        "data_ultima_modifica": "2025-04-15",
        "titolo": "Disposizioni in materia di lavoro",
    }
    defaults.update(overrides)  # type: ignore[typeddict-item]
    return defaults


class TestBuildUrlFromUrn:
    def test_basic(self) -> None:
        assert (
            build_url_from_urn("urn:nir:stato:legge:2024-12-13;203")
            == "https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:legge:2024-12-13;203"
        )


class TestBuildUrnFromUpdated:
    def test_legge(self) -> None:
        assert (
            build_urn_from_updated(_make_atto())
            == "urn:nir:stato:legge:2024-12-13;203"
        )

    def test_decreto_legge(self) -> None:
        atto = _make_atto(
            denominazione_atto="DECRETO-LEGGE",
            numero_provvedimento="208",
            anno_provvedimento=2024,
            mese_provvedimento=12,
            giorno_provvedimento=27,
        )
        assert (
            build_urn_from_updated(atto)
            == "urn:nir:stato:decreto.legge:2024-12-27;208"
        )

    def test_decreto_legislativo(self) -> None:
        atto = _make_atto(
            denominazione_atto="DECRETO LEGISLATIVO",
            numero_provvedimento="82",
            anno_provvedimento=2005,
            mese_provvedimento=3,
            giorno_provvedimento=7,
        )
        assert (
            build_urn_from_updated(atto)
            == "urn:nir:stato:decreto.legislativo:2005-03-07;82"
        )

    def test_dpcm(self) -> None:
        atto = _make_atto(
            denominazione_atto="DECRETO DEL PRESIDENTE DEL CONSIGLIO DEI MINISTRI",
            numero_provvedimento="50",
            anno_provvedimento=2023,
            mese_provvedimento=5,
            giorno_provvedimento=15,
        )
        assert (
            build_urn_from_updated(atto)
            == "urn:nir:stato:decreto.presidente.consiglio.ministri:2023-05-15;50"
        )

    def test_zero_padding_month_day(self) -> None:
        atto = _make_atto(
            anno_provvedimento=2024,
            mese_provvedimento=1,
            giorno_provvedimento=5,
        )
        # Il padding deve produrre "2024-01-05", non "2024-1-5"
        assert "2024-01-05" in build_urn_from_updated(atto)

    def test_unknown_denomination_raises(self) -> None:
        atto = _make_atto(denominazione_atto="TIPO INESISTENTE")
        with pytest.raises(KeyError, match="denominazione atto non mappata"):
            build_urn_from_updated(atto)


class TestDenomMapping:
    def test_all_keys_uppercase(self) -> None:
        for denom in DENOM_TO_URN_TYPE:
            assert denom == denom.upper(), f"denom con lowercase: {denom!r}"

    def test_values_valid_urn_type_chars(self) -> None:
        # I tipi URN NIR usano solo lowercase + punti
        import re

        for urn_type in DENOM_TO_URN_TYPE.values():
            assert re.match(r"^[a-z.]+$", urn_type), f"urn_type invalido: {urn_type!r}"


class TestSearchUpdatedValidation:
    def test_from_after_to_raises(self) -> None:
        with pytest.raises(ValueError, match="successivo"):
            search_updated(date(2026, 4, 16), date(2026, 4, 15))

    def test_interval_over_12_months_raises(self) -> None:
        with pytest.raises(ValueError, match="12 mesi"):
            search_updated(date(2024, 1, 1), date(2025, 6, 1))
