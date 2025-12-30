# justhtml-html5lib-tests-bench

Runs the `html5lib-tests` parsing test corpus against real browser engines (via Playwright) and captures the resulting DOM tree.

## Latest results

Latest run (tree-construction, pass/(pass+fail)) — 2025-12-30:

| Engine | Tests Passed | Agreement | Notes |
|--------|-------------|-----------|-------|
| Chromium | 1763/1770 | 99.6% | 7 differing trees |
| WebKit | 1741/1770 | 98.4% | 29 differing trees |
| Firefox | 1727/1770 | 97.6% | 43 differing trees |

Skipped: all engines skipped 12 scripting-enabled cases (`#script-on`).

This is meant for answering questions like:

- “Do Chromium/Firefox/WebKit build the same DOM tree for this input?”
- “Which tests differ between engines, and how?”

## Quickstart

```bash
cd justhtml-html5lib-tests-bench
python -m pip install -e ".[test]"
python -m playwright install chromium
pytest
```

## Linting / formatting (pre-commit)

This repo is set up with `pre-commit` hooks for:

- Python: Ruff (minimal lint + formatting)
- JavaScript + JSON: Biome

Setup:

```bash
python -m pip install -e ".[dev,test]"
pre-commit install
pre-commit run --all-files
```

Note: the Biome hook requires a working Node.js installation.

## Running

Point the CLI at one or more `html5lib-tests` `.dat` files (typically in `tree-construction/`):

```bash
html5lib-tests-bench path/to/html5lib-tests/tree-construction/adoption01.dat \
  --browser chromium \
  --json-out .html5lib-tests-bench/results.json
```

By default, the runner compares the browser’s serialized DOM tree to the test’s expected tree when present.

Helpful flags:

- `--browser all`: run Chromium + Firefox + WebKit
- `--max-tests N`: limit for quick iteration
- `--no-compare`: only record the actual tree (no pass/fail)

## Inspecting differences

To print diffs during a run, use `--print-fails`. For full diffs without truncation, pass `--max-diff-lines 0` and redirect to a file:

```bash
html5lib-tests-bench --browser chromium --print-fails --max-diff-lines 0 \
  /path/to/html5lib-tests/tree-construction/*.dat \
  /path/to/html5lib-tests/tree-construction/scripted/*.dat \
  > .html5lib-tests-bench/chromium-diffs.txt 2>&1
```

To list just the failing `file#index` lines:

```bash
grep '^FAIL \[' .html5lib-tests-bench/chromium-diffs.txt
```

## Notes

- Network is blocked for deterministic results; external request attempts are recorded.
- This repo does **not** vendor `html5lib-tests` itself; you provide paths to the `.dat` files.

These numbers come from running the upstream `html5lib-tests/tree-construction` fixtures and comparing the browser’s serialized DOM tree against the expected tree output in the `.dat` files.
