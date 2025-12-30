from __future__ import annotations

import textwrap
from pathlib import Path

from html5lib_tests_bench.html5lib_dat import parse_html5lib_dat_text
from html5lib_tests_bench.html5lib_dat import parse_html5lib_dat_file


def test_parse_basic_document_test() -> None:
    text = textwrap.dedent(
        """
        #data
        <html><head></head><body>Hi</body></html>
        #document
        | <!DOCTYPE html>
        | <html>
        |   <head>
        |   <body>
        |     \"Hi\"
        """
    ).strip("\n")

    tests = parse_html5lib_dat_text(text, source_file="x.dat")
    assert len(tests) == 1
    t = tests[0]
    assert "<html>" in t.data
    assert t.fragment_context is None
    assert t.expected_tree is not None
    assert "<html>" in t.expected_tree


def test_parse_fragment_test_context_line() -> None:
    text = textwrap.dedent(
        """
        #data
        <b>Hi</b>
        #document-fragment
        div
        | <b>
        |   \"Hi\"
        """
    ).strip("\n")

    tests = parse_html5lib_dat_text(text, source_file="x.dat")
    assert len(tests) == 1
    t = tests[0]
    assert t.fragment_context == "div"
    assert t.expected_tree is not None
    assert "<b>" in t.expected_tree


def test_parse_fragment_context_with_expected_in_document_section() -> None:
    # Matches html5lib-tests' common structure: fragment context lives in
    # `#document-fragment`, but expected tree is under `#document`.
    text = textwrap.dedent(
        """
        #data
        <nobr>X
        #document-fragment
        svg path
        #document
        | <nobr>
        |   \"X\"
        """
    ).strip("\n")

    tests = parse_html5lib_dat_text(text, source_file="x.dat")
    assert len(tests) == 1
    t = tests[0]
    assert t.fragment_context == "svg path"
    assert t.expected_tree is not None
    assert "<nobr>" in t.expected_tree


def test_parse_multiple_tests() -> None:
    text = textwrap.dedent(
        """
        #data
        One
        #document
        | <html>

        #data
        Two
        #document
        | <html>
        """
    ).strip("\n")

    tests = parse_html5lib_dat_text(text, source_file="x.dat")
    assert [t.data for t in tests] == ["One", "Two"]
    assert [t.index for t in tests] == [0, 1]


def test_parse_file_latin1_fallback(tmp_path: Path) -> None:
    # Include a raw 0xFE byte to mirror html5lib-tests/encoding/*.dat.
    raw = b'#data\n<script>alert("\xfe")</script>\n#document\n| <html>\n'
    p = tmp_path / "encoding.dat"
    p.write_bytes(raw)

    tests = parse_html5lib_dat_file(p)
    assert len(tests) == 1
    assert "\u00fe" in tests[0].data
