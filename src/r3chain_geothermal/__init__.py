"""R3-CHAIN geothermal orchestration package.

Deliberately independent of the PyDoublet and pandapipesAI repositories
(ADR-001 D7) -- consumes plain dicts/JSON, never imports pydoublet or
pandapipesai. See docs/decisions/ADR-002-pydoublet-temperature-source.md for
the PyDoublet temperature-field contract this package implements.
"""

__version__ = "0.1.0"
