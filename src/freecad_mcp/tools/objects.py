"""MCP tools for creating, inspecting, editing, and deleting FreeCAD objects."""

from typing import Any

from mcp.types import ImageContent, TextContent

from .. import server_state
from ..mcp_compat import Context
from ..operations import (
    create_object_operation,
    delete_object_operation,
    edit_object_operation,
    get_object_operation,
    get_objects_operation,
)
from .types import ViewName


def create_object(
    ctx: Context,
    doc_name: str,
    obj_type: str,
    obj_name: str,
    analysis_name: str | None = None,
    obj_properties: dict[str, Any] = None,
    include_screenshot: bool = True,
    view_name: ViewName = "Isometric",
) -> list[TextContent | ImageContent]:
    """Create a new object in FreeCAD.
    Object type is starts with "Part::" or "Draft::" or "PartDesign::" or "Fem::".

    Args:
        doc_name: The name of the document to create the object in.
        obj_type: The type of the object to create (e.g. 'Part::Box', 'Part::Cylinder', 'Draft::Circle', 'PartDesign::Body', etc.).
        obj_name: The name of the object to create.
        obj_properties: The properties of the object to create.
        include_screenshot: Whether to return a screenshot of the model (default True).
            Set to False to save tokens when visual feedback is not needed,
            e.g. for intermediate steps in a longer sequence of changes.
        view_name: The view orientation of the returned screenshot (default "Isometric").
            Pick the view that best shows the change being made.

    Returns:
        A message indicating the success or failure of the object creation and a screenshot of the object.

    Examples:
        If you want to create a cylinder with a height of 30 and a radius of 10, you can use the following data.
        ```json
        {
            "doc_name": "MyCylinder",
            "obj_name": "Cylinder",
            "obj_type": "Part::Cylinder",
            "obj_properties": {
                "Height": 30,
                "Radius": 10,
                "Placement": {
                    "Base": {
                        "x": 10,
                        "y": 10,
                        "z": 0
                    },
                    "Rotation": {
                        "Axis": {
                            "x": 0,
                            "y": 0,
                            "z": 1
                        },
                        "Angle": 45
                    }
                },
                "ViewObject": {
                    "ShapeColor": [0.5, 0.5, 0.5, 1.0]
                }
            }
        }
        ```

        If you want to create a circle with a radius of 10, you can use the following data.
        ```json
        {
            "doc_name": "MyCircle",
            "obj_name": "Circle",
            "obj_type": "Draft::Circle",
        }
        ```

        If you want to create a FEM analysis, you can use the following data.
        ```json
        {
            "doc_name": "MyFEMAnalysis",
            "obj_name": "FemAnalysis",
            "obj_type": "Fem::AnalysisPython",
        }
        ```

        If you want to create a FEM constraint, you can use the following data.
        ```json
        {
            "doc_name": "MyFEMConstraint",
            "obj_name": "FemConstraint",
            "obj_type": "Fem::ConstraintFixed",
            "analysis_name": "MyFEMAnalysis",
            "obj_properties": {
                "References": [
                    {
                        "object_name": "MyObject",
                        "face": "Face1"
                    }
                ]
            }
        }
        ```

        If you want to create a FEM mechanical material, you can use the following data.
        ```json
        {
            "doc_name": "MyFEMAnalysis",
            "obj_name": "FemMechanicalMaterial",
            "obj_type": "Fem::MaterialCommon",
            "analysis_name": "MyFEMAnalysis",
            "obj_properties": {
                "Material": {
                    "Name": "MyMaterial",
                    "Density": "7900 kg/m^3",
                    "YoungModulus": "210 GPa",
                    "PoissonRatio": 0.3
                }
            }
        }
        ```

        If you want to create a FEM mesh, you can use the following data.
        The `Shape` property is required (legacy `Part` is also accepted).
        On FreeCAD 1.x the size limits are `CharacteristicLengthMax/Min`;
        the legacy `ElementSizeMax/Min` keys are also accepted.
        ```json
        {
            "doc_name": "MyFEMMesh",
            "obj_name": "FemMesh",
            "obj_type": "Fem::FemMeshGmsh",
            "analysis_name": "MyFEMAnalysis",
            "obj_properties": {
                "Shape": "MyObject",
                "CharacteristicLengthMax": 10,
                "CharacteristicLengthMin": 0.1
            }
        }
        ```
    """
    return create_object_operation(
        server_state.get_freecad_connection(),
        server_state.state.only_text_feedback,
        doc_name,
        obj_type,
        obj_name,
        analysis_name,
        obj_properties,
        include_screenshot,
        view_name,
    )


def edit_object(
    ctx: Context,
    doc_name: str,
    obj_name: str,
    obj_properties: dict[str, Any],
    include_screenshot: bool = True,
    view_name: ViewName = "Isometric",
) -> list[TextContent | ImageContent]:
    """Edit an object in FreeCAD.
    This tool is used when the `create_object` tool cannot handle the object creation.

    Args:
        doc_name: The name of the document to edit the object in.
        obj_name: The name of the object to edit.
        obj_properties: The properties of the object to edit.
        include_screenshot: Whether to return a screenshot of the model (default True).
            Set to False to save tokens when visual feedback is not needed,
            e.g. for intermediate steps in a longer sequence of changes.
        view_name: The view orientation of the returned screenshot (default "Isometric").
            Pick the view that best shows the change being made.

    Returns:
        A message indicating the success or failure of the object editing and a screenshot of the object.
    """
    return edit_object_operation(
        server_state.get_freecad_connection(),
        server_state.state.only_text_feedback,
        doc_name,
        obj_name,
        obj_properties,
        include_screenshot,
        view_name,
    )


def delete_object(
    ctx: Context,
    doc_name: str,
    obj_name: str,
    include_screenshot: bool = True,
    view_name: ViewName = "Isometric",
) -> list[TextContent | ImageContent]:
    """Delete an object in FreeCAD.

    Args:
        doc_name: The name of the document to delete the object from.
        obj_name: The name of the object to delete.
        include_screenshot: Whether to return a screenshot of the model (default True).
            Set to False to save tokens when visual feedback is not needed,
            e.g. for intermediate steps in a longer sequence of changes.
        view_name: The view orientation of the returned screenshot (default "Isometric").
            Pick the view that best shows the change being made.

    Returns:
        A message indicating the success or failure of the object deletion and a screenshot of the object.
    """
    return delete_object_operation(
        server_state.get_freecad_connection(),
        server_state.state.only_text_feedback,
        doc_name,
        obj_name,
        include_screenshot,
        view_name,
    )


def get_objects(
    ctx: Context,
    doc_name: str,
    include_screenshot: bool = True,
    view_name: ViewName = "Isometric",
) -> list[TextContent | ImageContent]:
    """Get all objects in a document.
    You can use this tool to get the objects in a document to see what you can check or edit.

    Args:
        doc_name: The name of the document to get the objects from.
        include_screenshot: Whether to return a screenshot of the document (default True).
            Set to False to save tokens when only the object data is needed.
        view_name: The view orientation of the returned screenshot (default "Isometric").

    Returns:
        A list of objects in the document and a screenshot of the document.
    """
    return get_objects_operation(
        server_state.get_freecad_connection(),
        server_state.state.only_text_feedback,
        doc_name,
        include_screenshot,
        view_name,
    )


def get_object(
    ctx: Context,
    doc_name: str,
    obj_name: str,
    include_screenshot: bool = True,
    view_name: ViewName = "Isometric",
) -> list[TextContent | ImageContent]:
    """Get an object from a document.
    You can use this tool to get the properties of an object to see what you can check or edit.

    Args:
        doc_name: The name of the document to get the object from.
        obj_name: The name of the object to get.
        include_screenshot: Whether to return a screenshot of the document (default True).
            Set to False to save tokens when only the object data is needed.
        view_name: The view orientation of the returned screenshot (default "Isometric").

    Returns:
        The object and a screenshot of the object.
    """
    return get_object_operation(
        server_state.get_freecad_connection(),
        server_state.state.only_text_feedback,
        doc_name,
        obj_name,
        include_screenshot,
        view_name,
    )
