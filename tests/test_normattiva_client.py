from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from corpus_leggi_tools.normattiva_client import (
    DENOM_TO_URN_TYPE,
    TIPO_PROV_CODES,
    AttoAggiornato,
    _extract_token,
    async_export_to_zip,
    async_search_confirm,
    async_search_poll,
    async_search_start,
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


class TestTipoProvCodes:
    def test_known_codes(self) -> None:
        assert TIPO_PROV_CODES["PLE"] == "legge"
        assert TIPO_PROV_CODES["PLL"] == "decreto.legislativo"
        assert TIPO_PROV_CODES["PDL"] == "decreto.legge"
        assert TIPO_PROV_CODES["PPR"] == "decreto.presidente.repubblica"
        assert TIPO_PROV_CODES["COS"] == "costituzione"

    def test_values_consistent_with_denom_mapping(self) -> None:
        # Ogni urn_type in TIPO_PROV_CODES deve esistere come target di
        # DENOM_TO_URN_TYPE (nessuna orfana).
        denom_targets = set(DENOM_TO_URN_TYPE.values())
        for code, urn_type in TIPO_PROV_CODES.items():
            assert urn_type in denom_targets, (
                f"{code} → {urn_type!r} non presente in DENOM_TO_URN_TYPE values"
            )


class TestExtractToken:
    def test_plain_string(self) -> None:
        assert _extract_token("abc-123-uuid") == "abc-123-uuid"

    def test_top_level_token_key(self) -> None:
        assert _extract_token({"token": "xyz"}) == "xyz"

    def test_nested_in_data_dict(self) -> None:
        assert _extract_token({"data": {"token": "deep"}}) == "deep"

    def test_data_as_string(self) -> None:
        assert _extract_token({"data": "uuid-here"}) == "uuid-here"

    def test_alternative_keys(self) -> None:
        assert _extract_token({"taskId": "t"}) == "t"
        assert _extract_token({"uuid": "u"}) == "u"

    def test_not_found_returns_none(self) -> None:
        assert _extract_token({"foo": "bar"}) is None
        assert _extract_token("") is None
        assert _extract_token(None) is None


class TestAsyncSearchStart:
    def test_payload_structure(self) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {"token": "tok-123"}
        with patch("corpus_leggi_tools.normattiva_client.requests.post") as m_post:
            m_post.return_value = mock_response
            token = async_search_start(
                {"filtriMap": {"codice_tipo_provvedimento": "PLE"}},
                data_vigenza="2026-04-16",
            )
        assert token == "tok-123"
        _call_args, call_kwargs = m_post.call_args
        payload = call_kwargs["json"]
        assert payload["formato"] == "AKN"
        assert payload["tipoRicerca"] == "A"
        assert payload["modalita"] == "C"
        assert payload["dataVigenza"] == "2026-04-16"
        assert payload["parametriRicerca"] == {
            "filtriMap": {"codice_tipo_provvedimento": "PLE"}
        }

    def test_default_data_vigenza_today(self) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {"token": "t"}
        with patch("corpus_leggi_tools.normattiva_client.requests.post") as m_post:
            m_post.return_value = mock_response
            async_search_start({})
        payload = m_post.call_args.kwargs["json"]
        # Deve essere una data ISO valida di oggi
        parsed = date.fromisoformat(payload["dataVigenza"])
        assert (date.today() - parsed).days <= 1

    def test_missing_token_raises(self) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "ok"}
        with patch("corpus_leggi_tools.normattiva_client.requests.post") as m_post:
            m_post.return_value = mock_response
            with pytest.raises(RuntimeError, match="token non trovato"):
                async_search_start({})


class TestAsyncSearchConfirm:
    def test_sends_token_in_body(self) -> None:
        mock_response = MagicMock()
        with patch("corpus_leggi_tools.normattiva_client.requests.put") as m_put:
            m_put.return_value = mock_response
            async_search_confirm("tok-456")
        call_kwargs = m_put.call_args.kwargs
        assert call_kwargs["json"] == {"token": "tok-456"}
        mock_response.raise_for_status.assert_called_once()


class TestAsyncSearchPoll:
    def test_returns_location_on_303(self) -> None:
        redirect_response = MagicMock(
            status_code=303, headers={"x-ipzs-location": "https://dl/file.zip"}
        )
        with patch("corpus_leggi_tools.normattiva_client.requests.get") as m_get:
            m_get.return_value = redirect_response
            with patch("corpus_leggi_tools.normattiva_client.time.sleep"):
                url = async_search_poll("tok", quiet=True)
        assert url == "https://dl/file.zip"
        # allow_redirects=False è essenziale per catturare l'header
        assert m_get.call_args.kwargs["allow_redirects"] is False

    def test_loops_on_200_until_303(self) -> None:
        r200 = MagicMock(status_code=200, headers={})
        r303 = MagicMock(
            status_code=303, headers={"x-ipzs-location": "https://dl/x.zip"}
        )
        with patch("corpus_leggi_tools.normattiva_client.requests.get") as m_get:
            m_get.side_effect = [r200, r200, r303]
            with patch("corpus_leggi_tools.normattiva_client.time.sleep"):
                url = async_search_poll("tok", quiet=True)
        assert url == "https://dl/x.zip"
        assert m_get.call_count == 3

    def test_fallback_location_header(self) -> None:
        r303 = MagicMock(status_code=303, headers={"Location": "https://dl/y.zip"})
        with patch("corpus_leggi_tools.normattiva_client.requests.get") as m_get:
            m_get.return_value = r303
            with patch("corpus_leggi_tools.normattiva_client.time.sleep"):
                url = async_search_poll("tok", quiet=True)
        assert url == "https://dl/y.zip"

    def test_303_without_location_raises(self) -> None:
        r303 = MagicMock(status_code=303, headers={})
        with patch("corpus_leggi_tools.normattiva_client.requests.get") as m_get:
            m_get.return_value = r303
            with patch("corpus_leggi_tools.normattiva_client.time.sleep"):
                with pytest.raises(RuntimeError, match="x-ipzs-location"):
                    async_search_poll("tok", quiet=True)

    def test_timeout_raises(self) -> None:
        r200 = MagicMock(status_code=200, headers={})
        # Simula time.monotonic: 0, 0.01, 1000 → oltrepassa max_wait=5s
        with patch("corpus_leggi_tools.normattiva_client.requests.get") as m_get:
            m_get.return_value = r200
            with patch("corpus_leggi_tools.normattiva_client.time.sleep"):
                with patch(
                    "corpus_leggi_tools.normattiva_client.time.monotonic",
                    side_effect=[0.0, 0.01, 1000.0, 1000.0],
                ):
                    with pytest.raises(TimeoutError, match="scaduto"):
                        async_search_poll("tok", max_wait=5.0, quiet=True)


class TestAsyncExportToZip:
    def test_full_flow_composes_steps(self, tmp_path: Path) -> None:
        out_zip = tmp_path / "export.zip"
        with (
            patch(
                "corpus_leggi_tools.normattiva_client.async_search_start",
                return_value="tok",
            ) as m_start,
            patch(
                "corpus_leggi_tools.normattiva_client.async_search_confirm"
            ) as m_conf,
            patch(
                "corpus_leggi_tools.normattiva_client.async_search_poll",
                return_value="https://dl/x.zip",
            ) as m_poll,
            patch(
                "corpus_leggi_tools.normattiva_client.download_file",
                return_value=out_zip,
            ) as m_dl,
        ):
            result = async_export_to_zip(
                {"filtriMap": {"codice_tipo_provvedimento": "PLE"}},
                out_zip,
                quiet=True,
            )
        assert result == out_zip
        m_start.assert_called_once()
        m_conf.assert_called_once_with("tok", timeout=60.0)
        m_poll.assert_called_once()
        m_dl.assert_called_once_with("https://dl/x.zip", out_zip, timeout=600.0)
