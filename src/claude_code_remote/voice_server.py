"""Entry point for running voice wrapper as a subprocess."""
import sys
from claude_code_remote.voice import run

if __name__ == "__main__":
    run(sys.argv[1])
