"""Run the pipeline manually and dump the payload to stdout.

Usage:
    .venv/bin/python run.py              # incremental (uses cache)
    .venv/bin/python run.py --full       # force full scan, ignore cache
"""

import asyncio
import sys
from pathlib import Path

from agents_md_mcp.server import _run_pipeline

force_full = "--full" in sys.argv
result = asyncio.run(_run_pipeline(Path(__file__).parent, force_full_scan=force_full))
print(result)
