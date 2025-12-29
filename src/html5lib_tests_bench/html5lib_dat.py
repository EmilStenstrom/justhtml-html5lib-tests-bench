from __future__ import annotations

import codecs
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Html5libDatTest:
    source_file: str
    index: int
    data: str
    expected_tree: str | None
    fragment_context: str | None


def _finalize_test(
    *,
    source_file: str,
    index: int,
    data_lines: list[str],
    document_lines: list[str],
    fragment_lines: list[str],
) -> Html5libDatTest | None:
    if not data_lines:
        return None

    data = "\n".join(data_lines)

    fragment_context: str | None = None
    expected_tree: str | None = None

    if fragment_lines:
        fragment_context = fragment_lines[0].strip() or None
        # In html5lib-tests, fragment tests generally specify the fragment
        # context under `#document-fragment`, but the expected tree under
        # `#document`.
        expected_tree_lines = document_lines if document_lines else fragment_lines[1:]
        expected_tree = "\n".join(expected_tree_lines).strip("\n") if expected_tree_lines else ""
    elif document_lines:
        expected_tree = "\n".join(document_lines).strip("\n")

    return Html5libDatTest(
        source_file=source_file,
        index=index,
        data=data,
        expected_tree=expected_tree,
        fragment_context=fragment_context,
    )


def parse_html5lib_dat_text(text: str, *, source_file: str = "<memory>") -> list[Html5libDatTest]:
    """Parse a html5lib-tests `.dat` file.

    This is intentionally a small parser that focuses on `#data`, `#document`,
    and `#document-fragment` blocks. Other sections are ignored.

    Returns a list of tests in the order they appear.
    """

    tests: list[Html5libDatTest] = []

    section: str | None = None
    data_lines: list[str] = []
    document_lines: list[str] = []
    fragment_lines: list[str] = []

    test_index = 0

    def flush() -> None:
        nonlocal test_index, data_lines, document_lines, fragment_lines
        t = _finalize_test(
            source_file=source_file,
            index=test_index,
            data_lines=data_lines,
            document_lines=document_lines,
            fragment_lines=fragment_lines,
        )
        if t is not None:
            tests.append(t)
            test_index += 1
        data_lines = []
        document_lines = []
        fragment_lines = []

    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if line.startswith("#"):
            key = line[1:].strip().lower()
            # A new #data starts a new test.
            if key == "data":
                if data_lines:
                    flush()
                section = "data"
                continue
            if key in {"document", "document-fragment"}:
                section = key
                continue
            # Ignore other sections.
            section = None
            continue

        if section == "data":
            data_lines.append(line)
        elif section == "document":
            document_lines.append(line)
        elif section == "document-fragment":
            fragment_lines.append(line)

    flush()

    return tests


def parse_html5lib_dat_file(path: str | Path) -> list[Html5libDatTest]:
    p = Path(path)

    data = p.read_bytes()

    if data.startswith(codecs.BOM_UTF8):
        text = data.decode("utf-8-sig")
    elif data.startswith(codecs.BOM_UTF16_LE) or data.startswith(codecs.BOM_UTF16_BE):
        text = data.decode("utf-16")
    else:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            # Some files in html5lib-tests (notably the encoding corpus) contain
            # raw bytes that are not valid UTF-8. Decoding as latin-1 preserves
            # a 1:1 mapping from byte->codepoint.
            text = data.decode("latin-1")

    return parse_html5lib_dat_text(text, source_file=str(p))
