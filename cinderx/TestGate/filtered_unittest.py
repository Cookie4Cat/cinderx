#!/usr/bin/env python3
"""Run unittest modules with an ignorefile and exit without finalization."""

from __future__ import annotations

import argparse
import fnmatch
import os
from pathlib import Path
import sys
import unittest


def read_patterns(path: Path) -> list[str]:
    patterns: list[str] = []
    if not path.exists():
        return patterns
    with path.open(encoding="utf-8") as pattern_file:
        for raw_line in pattern_file:
            line = raw_line.strip()
            if line and not line.startswith("#"):
                patterns.append(line)
    return patterns


def test_id(test: unittest.TestCase) -> str:
    try:
        return test.id()
    except Exception:
        return str(test)


def should_skip(test: unittest.TestCase, patterns: list[str]) -> bool:
    name = test_id(test)
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)


def filter_suite(
    suite: unittest.TestSuite, patterns: list[str]
) -> tuple[unittest.TestSuite, int]:
    filtered = unittest.TestSuite()
    skipped = 0
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            child, child_skipped = filter_suite(item, patterns)
            skipped += child_skipped
            if child.countTestCases():
                filtered.addTest(child)
        elif should_skip(item, patterns):
            skipped += 1
        else:
            filtered.addTest(item)
    return filtered, skipped


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ignorefile", required=True)
    parser.add_argument("tests", nargs="+")
    args = parser.parse_args(argv)

    patterns = read_patterns(Path(args.ignorefile))
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    for test in args.tests:
        suite.addTests(loader.loadTestsFromName(test))
    suite, skipped = filter_suite(suite, patterns)

    print(f"filtered_unittest: skipped {skipped} tests by ignorefile")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    sys.stdout.flush()
    sys.stderr.flush()

    os._exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main(sys.argv[1:])
