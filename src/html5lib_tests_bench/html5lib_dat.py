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
    scripting_enabled: bool


def _finalize_test(
    *,
    source_file: str,
    index: int,
    saw_data: bool,
    data_lines: list[str],
    document_lines: list[str],
    fragment_lines: list[str],
    scripting_enabled: bool,
) -> Html5libDatTest | None:
    # html5lib-tests uses an empty `#data` block to represent empty input.
    # Only skip entries that never started a test (i.e. no `#data` seen).
    if not saw_data:
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
        scripting_enabled=scripting_enabled,
    )


def parse_html5lib_dat_text(text: str, *, source_file: str = "<memory>") -> list[Html5libDatTest]:
    """Parse a html5lib-tests `.dat` file.

    This is intentionally a small parser that focuses on `#data`, `#document`,
    and `#document-fragment` blocks. Other sections are ignored.

    Returns a list of tests in the order they appear.
    """

    tests: list[Html5libDatTest] = []

    section: str | None = None
    saw_data = False
    data_lines: list[str] = []
    document_lines: list[str] = []
    fragment_lines: list[str] = []

    test_index = 0
    default_scripting_enabled = False
    current_test_scripting_enabled = default_scripting_enabled

    def flush() -> None:
        nonlocal test_index, saw_data, data_lines, document_lines, fragment_lines, current_test_scripting_enabled
        t = _finalize_test(
            source_file=source_file,
            index=test_index,
            saw_data=saw_data,
            data_lines=data_lines,
            document_lines=document_lines,
            fragment_lines=fragment_lines,
            scripting_enabled=current_test_scripting_enabled,
        )
        if t is not None:
            tests.append(t)
            test_index += 1
        saw_data = False
        data_lines = []
        document_lines = []
        fragment_lines = []

    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if line.startswith("#"):
            key = line[1:].strip().lower()

            if key == "script-on":
                if data_lines:
                    current_test_scripting_enabled = True
                else:
                    default_scripting_enabled = True
                section = None
                continue
            if key == "script-off":
                if data_lines:
                    current_test_scripting_enabled = False
                else:
                    default_scripting_enabled = False
                section = None
                continue

            # A new #data starts a new test.
            if key == "data":
                if saw_data:
                    flush()
                current_test_scripting_enabled = default_scripting_enabled
                saw_data = True
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
