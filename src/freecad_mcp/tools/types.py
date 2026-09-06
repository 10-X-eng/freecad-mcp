"""Shared type definitions for FreeCAD MCP tools."""

from typing import Literal


ViewName = Literal[
    "Isometric",
    "Front",
    "Top",
    "Right",
    "Back",
    "Left",
    "Bottom",
    "Dimetric",
    "Trimetric",
]
