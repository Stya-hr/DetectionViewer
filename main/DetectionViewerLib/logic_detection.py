import json
import logging
import os
from datetime import datetime
from typing import Any, Callable

import qt
import slicer
import vtk
from slicer import vtkMRMLScalarVolumeNode
from slicer.i18n import tr as _
from slicer.ScriptedLoadableModule import ScriptedLoadableModuleLogic

class DetectionBoxLogicMixin:
    def readDetectionData(self, detectionPath: str) -> dict[str, Any]:
        if not os.path.isfile(detectionPath):
            raise FileNotFoundError(f"Detection JSON not found: {detectionPath}")
        with open(detectionPath, "r", encoding="utf-8-sig") as detectionFile:
            return json.load(detectionFile)

    def detectionsFromData(
        self,
        detectionData: dict[str, Any],
        minScore: float = 0.0,
        maxDetections: int | None = None,
    ) -> list[dict[str, Any]]:
        detections = detectionData.get("raw_detections")
        if detections is None:
            detections = detectionData.get("detections", [])

        filteredDetections = [
            detection
            for detection in detections
            if float(detection.get("score", 1.0)) >= minScore
        ]
        if maxDetections is not None:
            filteredDetections = filteredDetections[:maxDetections]
        return filteredDetections

    def createDetectionBoxes(
        self,
        detectionPath: str,
        inputVolume: vtkMRMLScalarVolumeNode | None = None,
        minScore: float = 0.0,
        maxDetections: int | None = None,
        lpsToRas: bool = False,
        progressCallback: Callable[[int, int], None] | None = None,
    ) -> list[vtk.vtkObject]:
        detectionData = self.readDetectionData(detectionPath)
        detections = self.detectionsFromData(detectionData, minScore, maxDetections)

        self.clearDetectionBoxes()
        if progressCallback:
            progressCallback(0, len(detections))

        createdNodes = []
        for displayIndex, detection in enumerate(detections, start=1):
            bounds = self.detectionBoundsRAS(detection, inputVolume=inputVolume, lpsToRas=lpsToRas)
            boxNode = self.createBoxNode(bounds, detection, displayIndex)
            createdNodes.append(boxNode)
            if progressCallback and (displayIndex == len(detections) or displayIndex % 25 == 0):
                progressCallback(displayIndex, len(detections))

        logging.info("Created %d detection box nodes from %s", len(createdNodes), detectionPath)
        return createdNodes

    def detectionBoundsRAS(
        self,
        detection: dict[str, Any],
        inputVolume: vtkMRMLScalarVolumeNode | None = None,
        lpsToRas: bool = False,
    ) -> tuple[float, float, float, float, float, float]:
        if "box_xyzxyz_world" in detection:
            bounds = self.boundsFromXyzxyz(detection["box_xyzxyz_world"])
            return self.boundsLpsToRas(bounds) if lpsToRas else bounds

        if "box_cccwhd_world" in detection:
            bounds = self.boundsFromCccwhd(detection["box_cccwhd_world"])
            return self.boundsLpsToRas(bounds) if lpsToRas else bounds

        if "box_xyzxyz_ijk" in detection:
            if inputVolume is None:
                raise ValueError("IJK detections require an input volume")
            return self.ijkBoundsToRas(self.boundsFromXyzxyz(detection["box_xyzxyz_ijk"]), inputVolume)

        if "box_cccwhd_ijk" in detection:
            if inputVolume is None:
                raise ValueError("IJK detections require an input volume")
            return self.ijkBoundsToRas(self.boundsFromCccwhd(detection["box_cccwhd_ijk"]), inputVolume)

        raise ValueError(f"Detection is missing a supported box field: {detection}")

    def boundsFromXyzxyz(self, values: list[float]) -> tuple[float, float, float, float, float, float]:
        if len(values) != 6:
            raise ValueError(f"Expected 6 box values, got {len(values)}")
        x1, y1, z1, x2, y2, z2 = [float(value) for value in values]
        return min(x1, x2), max(x1, x2), min(y1, y2), max(y1, y2), min(z1, z2), max(z1, z2)

    def boundsFromCccwhd(self, values: list[float]) -> tuple[float, float, float, float, float, float]:
        if len(values) != 6:
            raise ValueError(f"Expected 6 box values, got {len(values)}")
        cx, cy, cz, width, height, depth = [float(value) for value in values]
        return (
            cx - width / 2.0,
            cx + width / 2.0,
            cy - height / 2.0,
            cy + height / 2.0,
            cz - depth / 2.0,
            cz + depth / 2.0,
        )

    def boundsLpsToRas(
        self,
        bounds: tuple[float, float, float, float, float, float],
    ) -> tuple[float, float, float, float, float, float]:
        xMin, xMax, yMin, yMax, zMin, zMax = bounds
        return -xMax, -xMin, -yMax, -yMin, zMin, zMax

    def ijkBoundsToRas(
        self,
        ijkBounds: tuple[float, float, float, float, float, float],
        inputVolume: vtkMRMLScalarVolumeNode,
    ) -> tuple[float, float, float, float, float, float]:
        ijkToRas = vtk.vtkMatrix4x4()
        inputVolume.GetIJKToRASMatrix(ijkToRas)
        xMin, xMax, yMin, yMax, zMin, zMax = ijkBounds
        rasPoints = []
        for i in (xMin, xMax):
            for j in (yMin, yMax):
                for k in (zMin, zMax):
                    rasPoints.append(ijkToRas.MultiplyPoint((i, j, k, 1.0))[:3])
        xs = [point[0] for point in rasPoints]
        ys = [point[1] for point in rasPoints]
        zs = [point[2] for point in rasPoints]
        return min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)

    def cubePolyDataFromBounds(self, bounds: tuple[float, float, float, float, float, float]):
        xMin, xMax, yMin, yMax, zMin, zMax = bounds
        cubeSource = vtk.vtkCubeSource()
        cubeSource.SetBounds(xMin, xMax, yMin, yMax, zMin, zMax)
        cubeSource.Update()

        cubePolyData = vtk.vtkPolyData()
        cubePolyData.DeepCopy(cubeSource.GetOutput())
        return cubePolyData

    def createBoxNode(
        self,
        bounds: tuple[float, float, float, float, float, float],
        detection: dict[str, Any],
        displayIndex: int,
    ):
        score = float(detection.get("score", 0.0))
        originalIndex = detection.get("index", displayIndex)
        nodeName = slicer.mrmlScene.GenerateUniqueName(f"Detection {originalIndex} score {score:.3f}")
        modelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", nodeName)
        modelNode.SetAndObservePolyData(self.cubePolyDataFromBounds(bounds))
        modelNode.SetAttribute(self.GENERATED_BOX_ATTRIBUTE, "1")
        modelNode.SetAttribute("DetectionViewer.Score", f"{score:.6f}")
        modelNode.SetAttribute("DetectionViewer.Index", str(originalIndex))
        modelNode.SetAttribute("DetectionViewer.Label", str(detection.get("label", "")))
        if detection.get("diameter_mm") is not None:
            modelNode.SetAttribute("DetectionViewer.DiameterMm", f"{float(detection['diameter_mm']):.3f}")
        if detection.get("size_mm") is not None:
            modelNode.SetAttribute(
                "DetectionViewer.SizeMm",
                ", ".join(f"{float(value):.3f}" for value in detection["size_mm"]),
            )

        modelNode.CreateDefaultDisplayNodes()
        self.configureBoxDisplay(modelNode, score)
        return modelNode

    def configureBoxDisplay(self, boxNode, score: float) -> None:
        displayNode = boxNode.GetDisplayNode()
        if displayNode is None:
            boxNode.CreateDefaultDisplayNodes()
            displayNode = boxNode.GetDisplayNode()
        if displayNode is None:
            return

        color = self.defaultBoxColor()
        try:
            displayNode.SetColor(color)
        except TypeError:
            displayNode.SetColor(*color)
        if hasattr(displayNode, "SetSelectedColor"):
            try:
                displayNode.SetSelectedColor(color)
            except TypeError:
                displayNode.SetSelectedColor(*color)
        if hasattr(displayNode, "SetFillVisibility"):
            displayNode.SetFillVisibility(False)
        if hasattr(displayNode, "SetOpacity"):
            displayNode.SetOpacity(0.18)
        if hasattr(displayNode, "SetRepresentationToSurface"):
            displayNode.SetRepresentationToSurface()
        if hasattr(displayNode, "SetEdgeVisibility"):
            displayNode.SetEdgeVisibility(True)
        if hasattr(displayNode, "SetLineThickness"):
            displayNode.SetLineThickness(0.35)
        if hasattr(displayNode, "SetSliceIntersectionThickness"):
            displayNode.SetSliceIntersectionThickness(2)
        if hasattr(displayNode, "SetGlyphScale"):
            displayNode.SetGlyphScale(0.0)
        if hasattr(displayNode, "SetTextScale"):
            displayNode.SetTextScale(0.0)
        if hasattr(displayNode, "SetHandlesInteractive"):
            displayNode.SetHandlesInteractive(False)
        displayNode.SetVisibility(True)
        if hasattr(displayNode, "SetVisibility2D"):
            displayNode.SetVisibility2D(True)
        if hasattr(displayNode, "SetVisibility3D"):
            displayNode.SetVisibility3D(True)

    def defaultBoxColor(self) -> tuple[float, float, float]:
        return 1.0, 0.9, 0.0

    def clearDetectionBoxes(self) -> int:
        nodesToRemove = self.generatedDetectionBoxNodes()
        for node in nodesToRemove:
            slicer.mrmlScene.RemoveNode(node)
        return len(nodesToRemove)

    def generatedDetectionBoxNodes(self) -> list[vtk.vtkObject]:
        nodes = []
        for className in ("vtkMRMLModelNode", "vtkMRMLMarkupsROINode"):
            nodes.extend(
                node
                for node in slicer.util.getNodesByClass(className)
                if node.GetAttribute(self.GENERATED_BOX_ATTRIBUTE) == "1"
            )
        return nodes

    def setDetectionBoxesVisible(self, visible: bool) -> None:
        for node in self.generatedDetectionBoxNodes():
            displayNode = node.GetDisplayNode()
            if displayNode is None:
                continue
            displayNode.SetVisibility(visible)
            if hasattr(displayNode, "SetVisibility2D"):
                displayNode.SetVisibility2D(visible)
            if hasattr(displayNode, "SetVisibility3D"):
                displayNode.SetVisibility3D(visible)

    def findDetectionBoxByIndex(self, detectionIndex: int):
        requestedIndex = str(detectionIndex)
        for node in self.generatedDetectionBoxNodes():
            if node.GetAttribute("DetectionViewer.Index") == requestedIndex:
                return node
        return None

    def highlightDetectionBox(self, targetNode) -> None:
        for node in self.generatedDetectionBoxNodes():
            displayNode = node.GetDisplayNode()
            if displayNode is None:
                continue
            if node == targetNode:
                color = self.highlightColor()
            else:
                color = self.defaultBoxColor()
            try:
                displayNode.SetColor(color)
            except TypeError:
                displayNode.SetColor(*color)
            if hasattr(displayNode, "SetSelectedColor"):
                try:
                    displayNode.SetSelectedColor(color)
                except TypeError:
                    displayNode.SetSelectedColor(*color)

    def clearDetectionHighlight(self) -> None:
        color = self.defaultBoxColor()
        for node in self.generatedDetectionBoxNodes():
            displayNode = node.GetDisplayNode()
            if displayNode is None:
                continue
            try:
                displayNode.SetColor(color)
            except TypeError:
                displayNode.SetColor(*color)
            if hasattr(displayNode, "SetSelectedColor"):
                try:
                    displayNode.SetSelectedColor(color)
                except TypeError:
                    displayNode.SetSelectedColor(*color)

    def highlightColor(self) -> tuple[float, float, float]:
        return 1.0, 0.0, 0.0

    def detectionBoxInfoRows(self, boxNode) -> list[tuple[str, str]]:
        bounds = [0.0] * 6
        try:
            boxNode.GetBounds(bounds)
        except TypeError:
            bounds = list(boxNode.GetBounds())

        xMin, xMax, yMin, yMax, zMin, zMax = bounds
        center = ((xMin + xMax) / 2.0, (yMin + yMax) / 2.0, (zMin + zMax) / 2.0)
        size = (xMax - xMin, yMax - yMin, zMax - zMin)

        rows = [
            ("Index", boxNode.GetAttribute("DetectionViewer.Index") or "-"),
            ("Score", f"{float(boxNode.GetAttribute('DetectionViewer.Score') or 0.0):.3f}"),
        ]
        label = boxNode.GetAttribute("DetectionViewer.Label")
        if label not in (None, ""):
            rows.append(("Label", label))

        rows.append(("Center RAS", f"({center[0]:.1f}, {center[1]:.1f}, {center[2]:.1f})"))
        rows.append(("Size RAS", f"{size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm"))

        diameter = boxNode.GetAttribute("DetectionViewer.DiameterMm")
        if diameter:
            rows.append(("Diameter", f"{float(diameter):.1f} mm"))

        originalSize = boxNode.GetAttribute("DetectionViewer.SizeMm")
        if originalSize:
            rows.append(("JSON size", f"{originalSize} mm"))

        return rows

