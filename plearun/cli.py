"""Command-line interface: python3 plearun_cli.py REPORT RECORDS_DIR"""

from __future__ import annotations

import json
import sys

from .pipeline import analyze

USAGE = "usage: plearun_cli.py [--llm] REPORT RECORDS_DIR"


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    use_llm = False
    positional = []
    for argument in argv:
        if argument == "--llm":
            use_llm = True
        elif argument in ("-h", "--help"):
            print(USAGE)
            return 0
        else:
            positional.append(argument)
    if len(positional) != 2:
        print(USAGE, file=sys.stderr)
        return 2

    report_path, records_dir = positional
    try:
        result, clock = analyze(report_path, records_dir, use_llm=use_llm)
    except OSError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(f"clock model: {clock.describe()}", file=sys.stderr)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0
