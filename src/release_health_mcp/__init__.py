"""Release Health MCP server."""


def main() -> None:
    from .server import main as _main

    _main()
