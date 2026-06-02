"""
WSGI entrypoint for production deployments.

The config file path is read from the HOMESHARE_CONFIG_FILE environment variable.
"""

import os
import sys

from homeshare.app import create_app
from homeshare.config import ConfigError, load_config

_config_path = os.environ.get("HOMESHARE_CONFIG_FILE")
if not _config_path:
    print(
        "Error: HOMESHARE_CONFIG_FILE environment variable is not set", file=sys.stderr
    )
    sys.exit(1)

try:
    _config = load_config(_config_path)
except ConfigError as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)

application = create_app(_config)
