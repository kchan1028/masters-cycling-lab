import argparse
import json
from pathlib import Path

from masters_cycling_lab.main import create_app


def write_openapi(path: Path) -> None:
    schema = create_app().openapi()
    path.write_text(json.dumps(schema, indent=2) + "\n")
    print(f"Wrote {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mcl", description="Masters Cycling Lab command line tools")
    commands = parser.add_subparsers(dest="command", required=True)

    openapi = commands.add_parser("openapi", help="write the API's OpenAPI schema as JSON")
    openapi.add_argument("output", type=Path)

    args = parser.parse_args(argv)
    if args.command == "openapi":
        write_openapi(args.output)
    return 0
