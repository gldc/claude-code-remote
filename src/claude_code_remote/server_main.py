"""Entry point for running server as a subprocess (daemon mode)."""

import argparse
from claude_code_remote.server import run_server

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--no-auth", action="store_true")
    args = parser.parse_args()
    run_server(host=args.host, port=args.port, skip_auth=args.no_auth)
