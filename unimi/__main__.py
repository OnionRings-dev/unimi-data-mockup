"""Comandi: collect, build e check."""
import argparse
import sqlite3

from .build import OUTPUT, build, check
from .collect import Collector


def main():
    parser = argparse.ArgumentParser(description="Database UniMi, senza eventi degli orari")
    commands = parser.add_subparsers(dest="command", required=True)
    collect = commands.add_parser("collect", help="Acquisisce e conserva le fonti mancanti")
    collect.add_argument("--workers", type=int, choices=range(1, 9), default=4)
    collect.add_argument("--retry-failed", action="store_true")
    collect.add_argument("--indexes-only", action="store_true", help="Rimanda le schede di insegnamenti e persone")
    builder = commands.add_parser("build", help="Ricostruisce il database offline")
    builder.add_argument("--output", default=str(OUTPUT))
    checker = commands.add_parser("check", help="Controlla integrità e relazioni del database")
    checker.add_argument("--database", default=str(OUTPUT))
    args = parser.parse_args()
    if args.command == "collect":
        Collector(args.workers, args.retry_failed).collect(details=not args.indexes_only)
    elif args.command == "build":
        build(args.output)
    else:
        with sqlite3.connect(f"file:{args.database}?mode=ro", uri=True) as db:
            check(db)
        print("Integrità e chiavi esterne: OK")


if __name__ == "__main__":
    main()
