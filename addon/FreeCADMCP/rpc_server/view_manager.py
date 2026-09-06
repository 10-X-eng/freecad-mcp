"""Capture the active 3D view without changing modeling state or the camera."""

import FreeCADGui

from rpc_server.gui_dispatch import _flush_gui_events


def save_view(path: str, width: int, height: int) -> None:
    gui_doc = FreeCADGui.activeDocument()
    if gui_doc is None:
        raise RuntimeError("No active FreeCAD document")
    view = gui_doc.activeView()
    if not hasattr(view, "saveImage"):
        raise RuntimeError("The active view cannot be captured as a 3D image")
    _flush_gui_events()
    try:
        view.saveImage(path, width, height, "Current", "Framebuffer")
    except TypeError:
        view.saveImage(path, width, height, "Current")
