from __future__ import annotations

import argparse
import difflib
import json
import sys
import time
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any
from typing import Literal

from .harness import BrowserHarness
from .harness import BrowserName
from .html5lib_dat import Html5libDatTest
from .html5lib_dat import parse_html5lib_dat_file


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="html5lib-tests-bench",
        description="Run html5lib-tests .dat parsing tests in real browsers and capture the resulting DOM tree.",
    )
    p.add_argument(
        "paths",
        nargs="+",
        help="One or more html5lib-tests .dat files (e.g. tree-construction/*.dat)",
    )
    p.add_argument(
        "--browser",
        choices=["chromium", "firefox", "webkit", "all"],
        default="chromium",
        help="Browser engine to run in (default: chromium)",
    )
    p.add_argument(
        "--json-out",
        default=None,
        help="Write full results to a JSON file",
    )
    p.add_argument(
        "--max-tests",
        type=int,
        default=0,
        help="Stop after N tests (0 = no limit)",
    )
    p.add_argument(
        "--no-compare",
        action="store_true",
        help="Do not compare against expected tree, just record actual tree",
    )
    p.add_argument(
        "--print-errors",
        action="store_true",
        help="Print full exception details for erroring tests (to stderr)",
    )
    p.add_argument(
        "--print-fails",
        action="store_true",
        help="Print a unified diff for failing comparisons (to stderr)",
    )
    p.add_argument(
        "--max-diff-lines",
        type=int,
        default=200,
        help="Max lines of unified diff to print per failure (0 = unlimited). Default: 200.",
    )
    return p.parse_args(argv)


def _browsers_from_arg(arg: str) -> list[BrowserName]:
    if arg == "all":
        return ["chromium", "firefox", "webkit"]
    return [arg]  # type: ignore[list-item]


def _load_tests(paths: list[str]) -> list[Html5libDatTest]:
    out: list[Html5libDatTest] = []
    for p in paths:
        out.extend(parse_html5lib_dat_file(p))
    return out


def _normalize_expected_tree(s: str) -> str:
    # Keep it simple and deterministic.
    return "\n".join(line.rstrip() for line in s.strip("\n").splitlines())


def main(argv: list[str] | None = None) -> int:
    started = time.perf_counter()
    ns = _parse_args(argv)

    tests = _load_tests(ns.paths)
    if not tests:
        print("No tests found")
        return 1

    browsers = _browsers_from_arg(ns.browser)

    try:
        import playwright  # type: ignore[import-not-found]

        playwright_version = str(getattr(playwright, "__version__", ""))
    except Exception:
        playwright_version = ""

    results: list[dict[str, Any]] = []
    summary: dict[str, dict[str, int]] = {b: {"pass": 0, "fail": 0, "error": 0, "skip": 0} for b in browsers}
    browser_versions: dict[str, str] = {}
    browser_launch_errors: dict[str, str] = {}

    limit = int(ns.max_tests or 0)

    for browser in browsers:
        try:
            with BrowserHarness(browser=browser, headless=True) as h:
                browser_versions[browser] = h.browser_version
                for idx, t in enumerate(tests):
                    if limit and idx >= limit:
                        break

                    rec: dict[str, Any] = {
                        "browser": browser,
                        "browser_version": h.browser_version,
                        "source_file": t.source_file,
                        "index": t.index,
                        "fragment_context": t.fragment_context,
                        "scripting_enabled": t.scripting_enabled,
                    }

                    # html5lib-tests includes script-on cases. For this benchmark we want to
                    # focus on parser differences without executing scripts.
                    if t.scripting_enabled:
                        rec["outcome"] = "skip"
                        rec["skip_reason"] = "scripting_enabled"
                        summary[browser]["skip"] += 1
                        results.append(rec)
                        continue

                    try:
                        if t.fragment_context:
                            r = h.run_fragment(fragment_context=t.fragment_context, html=t.data)
                        else:
                            # Render as a full document.
                            r = h.run_document(html=t.data, scripting_enabled=t.scripting_enabled)

                        rec["actual_tree"] = r.tree
                        if r.external_requests:
                            rec["external_requests"] = r.external_requests

                        if ns.no_compare or t.expected_tree is None:
                            rec["outcome"] = "recorded"
                        else:
                            expected = _normalize_expected_tree(t.expected_tree)
                            actual = _normalize_expected_tree(r.tree)
                            if actual == expected:
                                rec["outcome"] = "pass"
                                summary[browser]["pass"] += 1
                            else:
                                rec["outcome"] = "fail"
                                summary[browser]["fail"] += 1
                                rec["expected_tree"] = expected

                                if ns.print_fails:
                                    loc = f"{t.source_file}#{t.index}"
                                    ctx = f" fragment_context={t.fragment_context!r}" if t.fragment_context else ""
                                    print(f"FAIL [{browser}] {loc}{ctx}", file=sys.stderr)
                                    diff = difflib.unified_diff(
                                        expected.splitlines(),
                                        actual.splitlines(),
                                        fromfile="expected",
                                        tofile="actual",
                                        lineterm="",
                                    )
                                    max_lines = int(ns.max_diff_lines or 0)
                                    n = 0
                                    for line in diff:
                                        if max_lines and n >= max_lines:
                                            print("... (diff truncated)", file=sys.stderr)
                                            break
                                        print(line, file=sys.stderr)
                                        n += 1
                                    print("", file=sys.stderr)
                    except Exception as exc:
                        rec["outcome"] = "error"
                        rec["error"] = f"{type(exc).__name__}: {exc}"
                        summary[browser]["error"] += 1

                        if ns.print_errors:
                            loc = f"{t.source_file}#{t.index}"
                            ctx = f" fragment_context={t.fragment_context!r}" if t.fragment_context else ""
                            print(
                                f"ERROR [{browser}] {loc}{ctx}: {type(exc).__name__}: {exc}",
                                file=sys.stderr,
                            )
                            print(traceback.format_exc().rstrip("\n"), end="\n\n", file=sys.stderr)

                    results.append(rec)
        except Exception as exc:
            # Common case: Playwright browsers not installed (run: python -m playwright install).
            browser_versions.setdefault(browser, "")
            browser_launch_errors[browser] = f"{type(exc).__name__}: {exc}"
            summary[browser]["error"] += 1
            results.append(
                {
                    "browser": browser,
                    "browser_version": browser_versions[browser],
                    "outcome": "error",
                    "error": browser_launch_errors[browser],
                    "source_file": None,
                    "index": None,
                    "fragment_context": None,
                    "scripting_enabled": None,
                }
            )

    out_obj = {
        "schema": "html5libtestsbench.results.v1",
        "meta": {
            "browsers": browsers,
            "browser_versions": browser_versions,
            "browser_launch_errors": browser_launch_errors,
            "playwright_version": playwright_version,
            "paths": ns.paths,
            "max_tests": limit,
            "compare": not ns.no_compare,
        },
        "summary": summary,
        "results": results,
    }

    if ns.json_out:
        Path(ns.json_out).write_text(json.dumps(out_obj, indent=2, sort_keys=True), encoding="utf-8")

    # Print a compact summary
    for b in browsers:
        s = summary[b]
        v = browser_versions.get(b, "")
        suffix = f" {v}" if v else ""
        if b in browser_launch_errors:
            print(f"{b}{suffix}: ERROR launching browser ({browser_launch_errors[b]})")
        else:
            print(f"{b}{suffix}: pass={s['pass']} fail={s['fail']} error={s['error']} skipped={s['skip']}")

    elapsed_s = time.perf_counter() - started
    print(f"elapsed_seconds: {elapsed_s:.3f}")

    if ns.json_out:
        out_obj["meta"]["elapsed_seconds"] = elapsed_s

    # Non-zero exit if any errors (or fails when comparing)
    if any(summary[b]["error"] for b in browsers):
        return 2
    if (not ns.no_compare) and any(summary[b]["fail"] for b in browsers):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
