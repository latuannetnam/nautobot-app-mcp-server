#!/usr/bin/env python3
"""
Wrapper for the Django management command: import_production_data.

This file exists so the script can be called from the host:
    docker exec nautobot-app-mcp-server-nautobot-1 \
        python /source/scripts/import_production_data.py [--dry-run]

Inside the container, prefer the direct management command:
    poetry run nautobot-server import_production_data [--dry-run]
"""

import subprocess
import sys
from pathlib import Path

# This script is designed to run inside the Nautobot container.
# The management command is the canonical implementation.
cmd = [
    "poetry",
    "run",
    "nautobot-server",
    "import_production_data",
    *sys.argv[1:],
]

project_root = Path(__file__).parent.parent
result = subprocess.run(cmd, cwd=project_root)
sys.exit(result.returncode)
