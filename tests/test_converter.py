from __future__ import annotations

from corpus_leggi_tools.converter import (
    ArticoloMeta,
    build_article_md,
    build_index_md,
    detect_abrogation,
    format_article_display_num,
    normalize_article_heading,
    strip_ondata_front_matter,
    yaml_scalar,
)
from corpus_leggi_tools.metadata import AttoMetadata


def _meta(rubrica: str = "") -> ArticoloMeta:
    return ArticoloMeta(rubrica=rubrica, abrogato=False, abrogato_da=None)


def _demo_atto() -> AttoMetadata:
    return AttoMetadata(
        urn="urn:nir:stato:legge:2024-12-13;203",
        tipo="legge",
        denominazione="LEGGE",
        slug_tipo="legge",
        data="2024-12-13",
        anno=2024,
        numero="203",
        titolo="Disposizioni in materia di lavoro",
        codice_redazionale="24G00218",
        data_gu="20241228",
        data_vigenza="20260416",
        url="https://www.normattiva.it/x",
        url_xml="",
        url_permanente="https://www.normattiva.it/perm",
    )


class TestFormatArticleDisplayNum:
    def test_plain(self) -> None:
        assert format_article_display_num("1") == "1"
        assert format_article_display_num("42") == "42"
        assert format_article_display_num("203") == "203"

    def test_bis(self) -> None:
        assert format_article_display_num("3bis") == "3-bis"
        assert format_article_display_num("14bis") == "14-bis"

    def test_ter(self) -> None:
        assert format_article_display_num("3ter") == "3-ter"

    def test_quater(self) -> None:
        assert format_article_display_num("64quater") == "64-quater"

    def test_sexies(self) -> None:
        assert format_article_display_num("62sexies") == "62-sexies"


class TestStripOndataFrontMatter:
    def test_removes_yaml_block(self) -> None:
        md = "---\nkey: val\n---\n\n# Title\n"
        assert strip_ondata_front_matter(md) == "# Title\n"

    def test_no_front_matter(self) -> None:
        assert strip_ondata_front_matter("# Title") == "# Title"

    def test_malformed_without_closing_returns_untouched(self) -> None:
        md = "---\nkey: val\nno closing delimiter"
        assert strip_ondata_front_matter(md) == md

    def test_multiline_yaml(self) -> None:
        md = "---\na: 1\nb: 2\nc: 3\n---\n\n# Content"
        assert strip_ondata_front_matter(md) == "# Content"


class TestYamlScalar:
    def test_simple(self) -> None:
        assert yaml_scalar("hello") == '"hello"'

    def test_escape_double_quote(self) -> None:
        assert yaml_scalar('she said "hi"') == '"she said \\"hi\\""'

    def test_escape_backslash(self) -> None:
        assert yaml_scalar("back\\slash") == '"back\\\\slash"'

    def test_newline_becomes_space(self) -> None:
        assert yaml_scalar("line1\nline2") == '"line1 line2"'

    def test_empty(self) -> None:
        assert yaml_scalar("") == '""'


class TestNormalizeArticleHeading:
    def test_inline_simple(self) -> None:
        body = "## Art. 13. - Durata del periodo di prova\n\n1. Text."
        new, rubrica = normalize_article_heading(body, "13")
        assert rubrica == "Durata del periodo di prova"
        assert new.startswith("# Art. 13 — Durata del periodo di prova")

    def test_inline_bis(self) -> None:
        body = "## Art. 3-bis. - Identita' digitale\n\n1. Text."
        new, rubrica = normalize_article_heading(body, "3bis")
        assert rubrica == "Identita' digitale"
        assert new.startswith("# Art. 3-bis — Identita' digitale")

    def test_inline_ter(self) -> None:
        body = "## Art. 3-ter. - (((Diritto alla trasparenza).))\n\n1. Text."
        new, rubrica = normalize_article_heading(body, "3ter")
        assert rubrica == "(((Diritto alla trasparenza).))"
        assert new.startswith("# Art. 3-ter —")

    def test_inline_quater(self) -> None:
        body = "## Art. 64-quater. - (Sistema IT-Wallet)\n\n1. Text."
        new, rubrica = normalize_article_heading(body, "64quater")
        assert rubrica == "(Sistema IT-Wallet)"
        assert new.startswith("# Art. 64-quater — (Sistema IT-Wallet)")

    def test_inline_rubric_with_internal_dash(self) -> None:
        body = (
            "## Art. 64-quater. - (Sistema di portafoglio - IT-Wallet)\n\n1. Text."
        )
        new, rubrica = normalize_article_heading(body, "64quater")
        assert rubrica == "(Sistema di portafoglio - IT-Wallet)"
        assert "# Art. 64-quater — (Sistema di portafoglio - IT-Wallet)" in new

    def test_multiline_rubric_on_separate_line(self) -> None:
        body = "## Art. 8.\n\nModifiche alla disciplina dei fondi\n\n1. Text."
        new, rubrica = normalize_article_heading(body, "8")
        assert rubrica == "Modifiche alla disciplina dei fondi"
        assert new.startswith("# Art. 8 — Modifiche alla disciplina dei fondi")

    def test_no_rubrica(self) -> None:
        body = "## Art. 91.\n\n1. Senza rubrica."
        new, rubrica = normalize_article_heading(body, "91")
        assert rubrica == ""
        assert new.startswith("# Art. 91")
        assert "# Art. 91 —" not in new

    def test_strips_trailing_dot_from_rubrica(self) -> None:
        body = "## Art. 7. - Titolo con punto.\n\n1. Text."
        _new, rubrica = normalize_article_heading(body, "7")
        assert rubrica == "Titolo con punto"

    def test_multiline_does_not_mistake_comma_for_rubrica(self) -> None:
        # Se dopo l'heading c'è un comma numerato (1. ...), niente rubrica
        body = "## Art. 99.\n\n1. Primo comma senza rubrica."
        new, rubrica = normalize_article_heading(body, "99")
        assert rubrica == ""
        assert new.startswith("# Art. 99")

    def test_abrogated_article_rubric_kept_with_parens(self) -> None:
        # Per ora gli articoli abrogati hanno rubrica "((ARTICOLO ABROGATO ...))"
        # (cleanup è issue #1). Test fissa il comportamento attuale.
        body = "## Art. 4. - ((ARTICOLO ABROGATO DAL D.LGS. 26 AGOSTO 2016, N. 179))"
        _new, rubrica = normalize_article_heading(body, "4")
        assert rubrica == "((ARTICOLO ABROGATO DAL D.LGS. 26 AGOSTO 2016, N. 179))"


class TestDetectAbrogation:
    def test_abrogato(self) -> None:
        raw = "((ARTICOLO ABROGATO DAL D.LGS. 26 AGOSTO 2016, N. 179))"
        assert detect_abrogation(raw) == (True, "D.LGS. 26 AGOSTO 2016, N. 179")

    def test_soppresso(self) -> None:
        raw = "((ARTICOLO SOPPRESSO DAL D.LGS. 30 DICEMBRE 2010, N. 235))"
        assert detect_abrogation(raw) == (True, "D.LGS. 30 DICEMBRE 2010, N. 235")

    def test_case_insensitive(self) -> None:
        raw = "((articolo abrogato dal D.LGS. 26 AGOSTO 2016, N. 179))"
        matched, _ = detect_abrogation(raw)
        assert matched is True

    def test_trailing_period_tolerated(self) -> None:
        raw = "((ARTICOLO ABROGATO DAL D.LGS. 26 AGOSTO 2016, N. 179))."
        matched, source = detect_abrogation(raw)
        assert matched is True
        assert source == "D.LGS. 26 AGOSTO 2016, N. 179"

    def test_non_abrogation_rubric(self) -> None:
        assert detect_abrogation("Definizioni") == (False, None)
        assert detect_abrogation("(Agenzia per l'Italia digitale)") == (False, None)
        assert detect_abrogation("(((Diritto alla trasparenza).))") == (False, None)

    def test_empty(self) -> None:
        assert detect_abrogation("") == (False, None)


class TestBuildArticleMd:
    def test_basic_structure(self) -> None:
        body = "## Art. 1. - Definizioni\n\n1. Testo."
        md, meta = build_article_md(_demo_atto(), "1", body, "2026-04-16")

        assert meta == ArticoloMeta(rubrica="Definizioni", abrogato=False, abrogato_da=None)
        assert "# Art. 1 — Definizioni" in md
        assert 'numero: "1"' in md
        assert "urn: urn:nir:stato:legge:2024-12-13;203~art1" in md
        assert 'rubrica: "Definizioni"' in md
        assert "vigente: true" in md
        assert "licenza: CC-BY-4.0" in md
        assert "fonte: normattiva.it" in md
        assert "aggiornato_al: 2026-04-16" in md
        assert "abrogato_da:" not in md

    def test_bis_article(self) -> None:
        body = "## Art. 3-bis. - Identita' digitale\n\n1. Testo."
        md, meta = build_article_md(_demo_atto(), "3bis", body, "2026-04-16")

        assert meta.rubrica == "Identita' digitale"
        assert not meta.abrogato
        assert "# Art. 3-bis — Identita' digitale" in md
        assert 'numero: "3bis"' in md
        assert "urn: urn:nir:stato:legge:2024-12-13;203~art3bis" in md

    def test_strips_ondata_front_matter(self) -> None:
        body = "---\nlegal_notice: foo\nurl: bar\n---\n\n## Art. 1. - Def\n\n1. Testo."
        md, _meta = build_article_md(_demo_atto(), "1", body, "2026-04-16")

        assert md.count("---\n") == 2
        assert "legal_notice" not in md

    def test_no_rubrica_yields_null(self) -> None:
        body = "## Art. 91.\n\n1. Senza rubrica."
        md, meta = build_article_md(_demo_atto(), "91", body, "2026-04-16")

        assert meta.rubrica == ""
        assert not meta.abrogato
        assert "rubrica: null" in md

    def test_body_not_modified_beyond_heading(self) -> None:
        body = "## Art. 1. - Definizioni\n\n1. Ai fini del presente codice.\n\n2. Secondo comma."
        md, _meta = build_article_md(_demo_atto(), "1", body, "2026-04-16")

        assert "1. Ai fini del presente codice." in md
        assert "2. Secondo comma." in md

    def test_abrogated_article(self) -> None:
        body = "## Art. 4.\n\n((ARTICOLO ABROGATO DAL D.LGS. 26 AGOSTO 2016, N. 179))"
        md, meta = build_article_md(_demo_atto(), "4", body, "2026-04-16")

        assert meta.abrogato is True
        assert meta.abrogato_da == "D.LGS. 26 AGOSTO 2016, N. 179"
        assert meta.rubrica == ""
        assert "# Art. 4" in md and "ABROGATO" not in md.splitlines()[md.splitlines().index("# Art. 4")]
        assert "vigente: false" in md
        assert 'abrogato_da: "D.LGS. 26 AGOSTO 2016, N. 179"' in md
        assert "rubrica: null" in md
        assert "> **Articolo abrogato**" in md

    def test_soppressed_article(self) -> None:
        body = "## Art. 7.\n\n((ARTICOLO SOPPRESSO DAL D.LGS. 30 DICEMBRE 2010, N. 235))"
        md, meta = build_article_md(_demo_atto(), "7", body, "2026-04-16")

        assert meta.abrogato is True
        assert meta.abrogato_da == "D.LGS. 30 DICEMBRE 2010, N. 235"
        assert "vigente: false" in md

    def test_vigenza_inizio_included_when_provided(self) -> None:
        body = "## Art. 1. - Definizioni\n\n1. Testo."
        md, _meta = build_article_md(
            _demo_atto(), "1", body, "2026-04-16", vigenza_inizio="2018-01-27"
        )
        assert 'vigenza_inizio: "2018-01-27"' in md

    def test_vigenza_inizio_omitted_when_none(self) -> None:
        body = "## Art. 1. - Definizioni\n\n1. Testo."
        md, _meta = build_article_md(_demo_atto(), "1", body, "2026-04-16")
        assert "vigenza_inizio" not in md

    def test_vigenza_inizio_on_abrogated_still_included(self) -> None:
        # Se l'API fornisce una vigenza_inizio anche per articoli abrogati,
        # la scriviamo lo stesso: rappresenta "da quando questa versione del
        # testo (inclusa la riga di abrogazione) è in vigore".
        body = "## Art. 4.\n\n((ARTICOLO ABROGATO DAL D.LGS. 26 AGOSTO 2016, N. 179))"
        md, meta = build_article_md(
            _demo_atto(), "4", body, "2026-04-16", vigenza_inizio="2016-09-14"
        )
        assert meta.abrogato is True
        assert 'vigenza_inizio: "2016-09-14"' in md
        assert "vigente: false" in md


class TestBuildIndexMd:
    def test_basic(self) -> None:
        articles = [("1", _meta("Definizioni")), ("2", _meta("Ambito"))]
        md = build_index_md(_demo_atto(), articles, "2026-04-16")

        assert "numero_articoli: 2" in md
        assert "- [Art. 1 — Definizioni](art-1.md)" in md
        assert "- [Art. 2 — Ambito](art-2.md)" in md
        assert "LEGGE 2024-12-13 — n. 203" in md
        assert "**Disposizioni in materia di lavoro**" in md

    def test_bis_uses_display_form_in_label_but_target_stays_compact(self) -> None:
        articles = [("3bis", _meta("Identita' digitale"))]
        md = build_index_md(_demo_atto(), articles, "2026-04-16")

        assert "- [Art. 3-bis — Identita' digitale](art-3bis.md)" in md

    def test_article_without_rubric(self) -> None:
        articles = [("42", _meta(""))]
        md = build_index_md(_demo_atto(), articles, "2026-04-16")

        assert "- [Art. 42](art-42.md)" in md

    def test_abrogated_article_label(self) -> None:
        articles = [
            ("4", ArticoloMeta(rubrica="", abrogato=True, abrogato_da="D.LGS. 26 AGOSTO 2016, N. 179"))
        ]
        md = build_index_md(_demo_atto(), articles, "2026-04-16")

        assert "- [Art. 4 _(abrogato)_](art-4.md)" in md

    def test_url_permanente_used_when_available(self) -> None:
        md = build_index_md(_demo_atto(), [("1", _meta("Def"))], "2026-04-16")
        assert "(https://www.normattiva.it/perm)" in md

    def test_url_fallback_when_no_permanente(self) -> None:
        atto = _demo_atto()
        atto_no_perm = AttoMetadata(
            **{**atto.__dict__, "url_permanente": ""}  # type: ignore[arg-type]
        )
        md = build_index_md(atto_no_perm, [("1", _meta("Def"))], "2026-04-16")
        assert "(https://www.normattiva.it/x)" in md
