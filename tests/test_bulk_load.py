from __future__ import annotations

import argparse
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from corpus_leggi_tools.bulk_load import (
    _validate_tipo,
    _zip_filename,
    bulk_import,
    build_parser,
    pick_best_xml,
)


class TestValidateTipo:
    def test_valid(self) -> None:
        assert _validate_tipo("PLE") == "PLE"
        assert _validate_tipo("PDL") == "PDL"
        assert _validate_tipo("PLL") == "PLL"
        assert _validate_tipo("PPR") == "PPR"

    def test_invalid_raises(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError, match="non valido"):
            _validate_tipo("XXX")

    def test_lowercase_invalid(self) -> None:
        # Codici IPZS sono uppercase, minuscolo non è accettato
        with pytest.raises(argparse.ArgumentTypeError):
            _validate_tipo("ple")


class TestPickBestXml:
    def test_prefers_vigenza_over_originale(self, tmp_path: Path) -> None:
        originale = tmp_path / "20050516_005G0104_ORIGINALE_V0.xml"
        vigenza = tmp_path / "20050516_005G0104_VIGENZA_20260320_V52.xml"
        originale.touch()
        vigenza.touch()
        assert pick_best_xml([originale, vigenza]) == vigenza

    def test_picks_vmax(self, tmp_path: Path) -> None:
        v1 = tmp_path / "20050516_X_VIGENZA_20200101_V1.xml"
        v10 = tmp_path / "20050516_X_VIGENZA_20250101_V10.xml"
        v52 = tmp_path / "20050516_X_VIGENZA_20260101_V52.xml"
        for p in (v1, v10, v52):
            p.touch()
        # Input in ordine casuale per verificare che il sort funzioni
        assert pick_best_xml([v10, v1, v52]) == v52

    def test_fallback_to_originale_when_no_vigenza(self, tmp_path: Path) -> None:
        originale = tmp_path / "20240101_24G00218_ORIGINALE_V0.xml"
        originale.touch()
        assert pick_best_xml([originale]) == originale

    def test_none_when_no_match(self, tmp_path: Path) -> None:
        # File che non matcha né VIGENZA né ORIGINALE
        weird = tmp_path / "README.txt"
        weird.touch()
        assert pick_best_xml([weird]) is None

    def test_empty_list(self) -> None:
        assert pick_best_xml([]) is None

    def test_mixed_ignores_unknown(self, tmp_path: Path) -> None:
        vigenza = tmp_path / "20050516_X_VIGENZA_20260101_V5.xml"
        weird = tmp_path / "junk.xml"
        vigenza.touch()
        weird.touch()
        assert pick_best_xml([vigenza, weird]) == vigenza


class TestZipFilename:
    def test_basic(self) -> None:
        assert _zip_filename("PLE", 2020, 2024) == "PLE_2020-2024.zip"

    def test_single_year(self) -> None:
        assert _zip_filename("PDL", 2024, 2024) == "PDL_2024-2024.zip"


class TestBulkImport:
    def _make_fake_zip(self, tmp_path: Path, atto_dirs: list[str]) -> Path:
        """Crea uno ZIP con strutture di cartelle atto (contenuto XML fittizio)."""
        zip_path = tmp_path / "fake.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for atto_dir in atto_dirs:
                zf.writestr(
                    f"{atto_dir}/20240101_XX_VIGENZA_20240101_V1.xml",
                    "<fake/>",
                )
        return zip_path

    def test_missing_zip_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="ZIP non trovato"):
            bulk_import(tmp_path / "nonexistent.zip", tmp_path / "ds")

    def test_extracts_and_processes_each_atto(self, tmp_path: Path) -> None:
        zip_path = self._make_fake_zip(
            tmp_path,
            ["LEGGE_20240101_1", "LEGGE_20240201_2", "LEGGE_20240301_3"],
        )
        dataset = tmp_path / "dataset"

        # Mock process_atto_from_xml perché il suo contenuto XML è fake
        with (
            patch(
                "corpus_leggi_tools.bulk_load.process_atto_from_xml",
                return_value=(1, 0),
            ) as m_proc,
            patch("corpus_leggi_tools.bulk_load.RepoWriter") as m_writer_cls,
        ):
            m_writer = m_writer_cls.return_value
            m_writer.stats = {"written": 3, "skipped": 0}
            rc = bulk_import(zip_path, dataset)

        assert rc == 0
        assert m_proc.call_count == 3
        # Extract dir creata accanto allo ZIP
        assert (tmp_path / "fake_extracted").is_dir()
        m_writer.save_manifest.assert_called_once()

    def test_limit_caps_atti(self, tmp_path: Path) -> None:
        zip_path = self._make_fake_zip(
            tmp_path, ["LEGGE_20240101_1", "LEGGE_20240201_2", "LEGGE_20240301_3"]
        )
        dataset = tmp_path / "dataset"
        with (
            patch(
                "corpus_leggi_tools.bulk_load.process_atto_from_xml",
                return_value=(1, 0),
            ) as m_proc,
            patch("corpus_leggi_tools.bulk_load.RepoWriter") as m_writer_cls,
        ):
            m_writer = m_writer_cls.return_value
            m_writer.stats = {"written": 0, "skipped": 0}
            bulk_import(zip_path, dataset, limit=2)
        assert m_proc.call_count == 2

    def test_single_atto_error_does_not_stop(self, tmp_path: Path) -> None:
        zip_path = self._make_fake_zip(
            tmp_path, ["LEGGE_20240101_1", "LEGGE_20240201_2"]
        )
        dataset = tmp_path / "dataset"
        with (
            patch(
                "corpus_leggi_tools.bulk_load.process_atto_from_xml",
                side_effect=[RuntimeError("boom"), (1, 0)],
            ) as m_proc,
            patch("corpus_leggi_tools.bulk_load.RepoWriter") as m_writer_cls,
        ):
            m_writer = m_writer_cls.return_value
            m_writer.stats = {"written": 1, "skipped": 0}
            rc = bulk_import(zip_path, dataset)
        # Un errore → exit code non zero ma entrambi gli atti sono stati tentati
        assert rc == 1
        assert m_proc.call_count == 2
        m_writer.save_manifest.assert_called_once()

    def test_skip_when_no_xml_matching(self, tmp_path: Path) -> None:
        # Cartella atto con solo file non matcher
        zip_path = tmp_path / "weird.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("LEGGE_20240101_1/README.txt", "nothing useful")
        dataset = tmp_path / "dataset"
        with (
            patch(
                "corpus_leggi_tools.bulk_load.process_atto_from_xml"
            ) as m_proc,
            patch("corpus_leggi_tools.bulk_load.RepoWriter") as m_writer_cls,
        ):
            m_writer = m_writer_cls.return_value
            m_writer.stats = {"written": 0, "skipped": 0}
            rc = bulk_import(zip_path, dataset)
        assert rc == 0
        m_proc.assert_not_called()


class TestCliParser:
    def test_export_requires_args(self) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["export"])  # missing required args

    def test_export_accepts_minimal_args(self, tmp_path: Path) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "export",
                "--tipo",
                "PLE",
                "--from-year",
                "2020",
                "--to-year",
                "2024",
                "--output",
                str(tmp_path / "out.zip"),
            ]
        )
        assert args.command == "export"
        assert args.tipo == "PLE"
        assert args.from_year == 2020
        assert args.to_year == 2024
        assert args.classe == "2"  # default

    def test_import_accepts_minimal_args(self, tmp_path: Path) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "import",
                "--dataset-root",
                str(tmp_path / "ds"),
                "--zip",
                str(tmp_path / "foo.zip"),
            ]
        )
        assert args.command == "import"
        assert args.limit is None

    def test_run_accepts_minimal_args(self, tmp_path: Path) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "run",
                "--tipo",
                "PLL",
                "--from-year",
                "2024",
                "--to-year",
                "2024",
                "--dataset-root",
                str(tmp_path / "ds"),
            ]
        )
        assert args.command == "run"
        assert args.tipo == "PLL"
        assert args.force_redownload is False

    def test_run_force_redownload_flag(self, tmp_path: Path) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "run",
                "--tipo",
                "PLE",
                "--from-year",
                "2020",
                "--to-year",
                "2024",
                "--dataset-root",
                str(tmp_path / "ds"),
                "--force-redownload",
            ]
        )
        assert args.force_redownload is True

    def test_invalid_tipo_rejected(self, tmp_path: Path) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "export",
                    "--tipo",
                    "FAKE",
                    "--from-year",
                    "2020",
                    "--to-year",
                    "2024",
                    "--output",
                    str(tmp_path / "x.zip"),
                ]
            )
