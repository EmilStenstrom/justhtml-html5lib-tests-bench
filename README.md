# justhtml-html5lib-tests-bench

Runs the `html5lib-tests` parsing test corpus against real browser engines (via Playwright) and captures the resulting DOM tree.

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

## Notes

- Network is blocked for deterministic results; external request attempts are recorded.
- This repo does **not** vendor `html5lib-tests` itself; you provide paths to the `.dat` files.
