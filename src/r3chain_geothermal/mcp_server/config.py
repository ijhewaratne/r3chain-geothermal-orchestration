"""Fixed, server-side-only assumptions config loading (T5.1A).

`config` is NEVER a tool argument anywhere in this package -- every
`geo_` tool that needs it uses the ONE config resolved here, once, at
server-build time. `R3CHAIN_MCP_CONFIG_PATH` is an operator-level launch
setting (an environment variable read only when the server process
starts), never a per-call parameter a client can influence.

The default config is loaded via `importlib.resources` from a PACKAGED
copy (`mcp_server/data/demo_assumptions.json`), not a repo-relative path
-- a repo-relative path only resolves inside a source checkout and breaks
once this package is installed from a wheel (found during T5.1A's own
clean-wheel verification: a `FileNotFoundError` at server startup,
leaking an absolute installed-site-packages path). The packaged copy is
byte-identical to the repository's own `config/demo_assumptions.json`
(the canonical source every other layer/test uses) -- kept in sync by a
dedicated test (`tests/mcp_server/test_server_contract.py`), since
setuptools packaging requires an actual file under `src/`, not a symlink
that would only work on the author's own machine.
"""
from __future__ import annotations

import json
import os
from importlib import resources
from pathlib import Path
from typing import Any

from ..hashing import canonical_raw_result_sha256
from ..workflow import validate_config_structure

CONFIG_PATH_ENV_VAR = "R3CHAIN_MCP_CONFIG_PATH"
_PACKAGED_CONFIG_PACKAGE = "r3chain_geothermal.mcp_server"
_PACKAGED_CONFIG_RELATIVE_PATH = ("data", "demo_assumptions.json")
"""`data/` is a plain resource subdirectory of the mcp_server PACKAGE, not
a Python package itself (no __init__.py needed) -- importlib.resources
can still address it by navigating from the mcp_server package's own
Traversable root."""


def resolve_fixed_config_path() -> Path | None:
    """The config path this server process will use -- `R3CHAIN_MCP_CONFIG_PATH`
    if set (operator launch-time override), otherwise `None`, meaning
    "use the packaged default" (`load_fixed_server_config()` resolves
    that case via `importlib.resources`, not a plain `Path`, since a
    packaged resource is not guaranteed to be a real filesystem path)."""
    override = os.environ.get(CONFIG_PATH_ENV_VAR)
    return Path(override) if override else None


def load_fixed_server_config(config_path: Path | None = None) -> dict[str, Any]:
    """Loads and structurally validates the fixed config ONCE. Raises
    (at server-build time, never per tool call) if the file is missing,
    is not valid JSON, or fails `validate_config_structure()` -- a broken
    server-side config is a deployment error, not a per-request outcome.

    Resolution order: explicit `config_path` argument (test-only seam) ->
    `R3CHAIN_MCP_CONFIG_PATH` env var -> the packaged default."""
    path = config_path if config_path is not None else resolve_fixed_config_path()
    if path is not None:
        text = path.read_text(encoding="utf-8")
    else:
        resource = resources.files(_PACKAGED_CONFIG_PACKAGE)
        for part in _PACKAGED_CONFIG_RELATIVE_PATH:
            resource = resource.joinpath(part)
        text = resource.read_text(encoding="utf-8")
    config: dict[str, Any] = json.loads(text)
    validate_config_structure(config)
    return config


def config_sha256(config: dict[str, Any]) -> str:
    return canonical_raw_result_sha256(config)
