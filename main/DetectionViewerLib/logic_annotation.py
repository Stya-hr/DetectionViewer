import json
import logging
import os
from datetime import datetime
from typing import Any

import qt
import slicer
import vtk
from slicer import vtkMRMLScalarVolumeNode
from slicer.i18n import tr as _
from slicer.ScriptedLoadableModule import ScriptedLoadableModuleLogic

class AnnotationLogicMixin:
    def createAnnotationFromDetectionNode(self, detectionNode, label: str):
        bounds = self.nodeBounds(detectionNode)
        annotationNode = self.createAnnotationNode(bounds, label)
        annotationNode.SetAttribute("DetectionViewer.SourceDetectionIndex", detectionNode.GetAttribute("DetectionViewer.Index") or "")
        annotationNode.SetAttribute("DetectionViewer.SourceScore", detectionNode.GetAttribute("DetectionViewer.Score") or "")
        return annotationNode

    def createEmptyAnnotation(self, center: tuple[float, float, float], label: str):
        bounds = self.boundsFromCenterSize(center, self.defaultAnnotationSize())
        return self.createAnnotationNode(bounds, label)

    def defaultAnnotationSize(self) -> tuple[float, float, float]:
        return 10.0, 10.0, 10.0

    def loadAnnotationsFromDetectionPath(self, detectionPath: str) -> list[vtk.vtkObject]:
        detectionData = self.readDetectionData(detectionPath)
        annotationData = self.annotationDataFromDetectionData(detectionData)

        self.clearAnnotations()
        if not annotationData:
            return []

        annotationNodes = []
        for annotation in annotationData:
            annotationNodes.append(self.createAnnotationFromData(annotation))
        return annotationNodes

    def annotationDataFromDetectionData(self, detectionData: dict[str, Any]) -> list[dict[str, Any]]:
        annotationData = detectionData.get("annotation", [])
        if isinstance(annotationData, dict):
            annotationData = annotationData.get("annotations", [])
        if annotationData is None:
            return []
        if not isinstance(annotationData, list):
            raise ValueError("Expected detection JSON 'annotation' to be a list")
        return [annotation for annotation in annotationData if isinstance(annotation, dict)]

    def createAnnotationFromData(self, annotation: dict[str, Any]):
        bounds = self.annotationBoundsRAS(annotation)
        label = str(annotation.get("label") or "0")
        annotationNode = self.createAnnotationNode(bounds, label)

        if annotation.get("index") is not None:
            annotationNode.SetAttribute("DetectionViewer.AnnotationIndex", str(int(annotation["index"])))
        sourceIndex = annotation.get("source_detection_index")
        if sourceIndex is not None:
            annotationNode.SetAttribute("DetectionViewer.SourceDetectionIndex", str(sourceIndex))
        sourceScore = annotation.get("source_score")
        if sourceScore is not None:
            annotationNode.SetAttribute("DetectionViewer.SourceScore", f"{float(sourceScore):.6f}")
        return annotationNode

    def annotationBoundsRAS(self, annotation: dict[str, Any]) -> tuple[float, float, float, float, float, float]:
        if "box_xyzxyz_ras" in annotation:
            values = annotation["box_xyzxyz_ras"]
            if len(values) != 6:
                raise ValueError("Expected 6 values in box_xyzxyz_ras")
            x1, y1, z1, x2, y2, z2 = [float(value) for value in values]
            return min(x1, x2), max(x1, x2), min(y1, y2), max(y1, y2), min(z1, z2), max(z1, z2)

        if "box_cccwhd_ras" in annotation:
            return self.boundsFromCccwhd(annotation["box_cccwhd_ras"])

        if "box_xyzxyz_world" in annotation:
            return self.boundsFromXyzxyz(annotation["box_xyzxyz_world"])

        if "box_cccwhd_world" in annotation:
            return self.boundsFromCccwhd(annotation["box_cccwhd_world"])

        raise ValueError(f"Annotation is missing a supported box field: {annotation}")

    def createAnnotationNode(self, bounds: tuple[float, float, float, float, float, float], label: str):
        annotationIndex = self.nextAnnotationIndex()
        nodeName = slicer.mrmlScene.GenerateUniqueName(f"Annotation {annotationIndex} {label}")
        roiNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsROINode", nodeName)
        roiNode.SetAttribute(self.ANNOTATION_BOX_ATTRIBUTE, "1")
        roiNode.SetAttribute("DetectionViewer.AnnotationIndex", str(annotationIndex))
        roiNode.SetAttribute("DetectionViewer.AnnotationLabel", label)
        self.setRoiBounds(roiNode, bounds)
        roiNode.SetLocked(False)
        roiNode.CreateDefaultDisplayNodes()
        self.configureAnnotationDisplay(roiNode)
        return roiNode

    def updateAnnotationNode(self, annotationNode, label: str) -> None:
        annotationNode.SetAttribute("DetectionViewer.AnnotationLabel", label)
        annotationNode.SetName(
            slicer.mrmlScene.GenerateUniqueName(
                f"Annotation {annotationNode.GetAttribute('DetectionViewer.AnnotationIndex') or ''} {label}"
            )
        )
        self.configureAnnotationDisplay(annotationNode)

    def annotationInfoRows(self, annotationNode) -> list[tuple[str, str]]:
        center = self.annotationNodeCenter(annotationNode)
        size = self.annotationNodeSize(annotationNode)
        xMin, xMax, yMin, yMax, zMin, zMax = self.nodeBounds(annotationNode)
        rows = [
            ("Index", annotationNode.GetAttribute("DetectionViewer.AnnotationIndex") or "-"),
            ("Label", annotationNode.GetAttribute("DetectionViewer.AnnotationLabel") or "-"),
            ("Center RAS", f"({center[0]:.1f}, {center[1]:.1f}, {center[2]:.1f})"),
            ("Size RAS", f"{size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm"),
            ("Diameter", f"{max(size):.1f} mm"),
            ("Bounds RAS", self.formatBounds(xMin, xMax, yMin, yMax, zMin, zMax)),
        ]

        sourceIndex = annotationNode.GetAttribute("DetectionViewer.SourceDetectionIndex")
        if sourceIndex:
            rows.append(("Source detection", sourceIndex))
        sourceScore = annotationNode.GetAttribute("DetectionViewer.SourceScore")
        if sourceScore:
            rows.append(("Source score", f"{float(sourceScore):.3f}"))
        return rows

    def formatBounds(self, xMin: float, xMax: float, yMin: float, yMax: float, zMin: float, zMax: float) -> str:
        return (
            f"X [{xMin:.1f}, {xMax:.1f}], "
            f"Y [{yMin:.1f}, {yMax:.1f}], "
            f"Z [{zMin:.1f}, {zMax:.1f}]"
        )

    def configureAnnotationDisplay(self, annotationNode) -> None:
        displayNode = annotationNode.GetDisplayNode()
        if displayNode is None:
            annotationNode.CreateDefaultDisplayNodes()
            displayNode = annotationNode.GetDisplayNode()
        if displayNode is None:
            return
        color = self.annotationColor()
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
            displayNode.SetOpacity(1.0)
        if hasattr(displayNode, "SetRepresentationToSurface"):
            displayNode.SetRepresentationToSurface()
        if hasattr(displayNode, "SetEdgeVisibility"):
            displayNode.SetEdgeVisibility(True)
        if hasattr(displayNode, "SetLineThickness"):
            displayNode.SetLineThickness(0.35)
        if hasattr(displayNode, "SetSliceIntersectionThickness"):
            displayNode.SetSliceIntersectionThickness(2)
        self.setMarkupHandlesVisible(displayNode, False)
        if hasattr(displayNode, "SetGlyphScale"):
            displayNode.SetGlyphScale(1.0)
        if hasattr(displayNode, "SetTextScale"):
            displayNode.SetTextScale(0.0)
        if hasattr(displayNode, "SetPointLabelsVisibility"):
            displayNode.SetPointLabelsVisibility(False)
        if hasattr(displayNode, "SetPropertiesLabelVisibility"):
            displayNode.SetPropertiesLabelVisibility(False)
        displayNode.SetVisibility(True)
        if hasattr(displayNode, "SetVisibility2D"):
            displayNode.SetVisibility2D(True)
        if hasattr(displayNode, "SetVisibility3D"):
            displayNode.SetVisibility3D(True)

    def setSelectedAnnotationHandles(self, selectedAnnotationNode) -> None:
        for annotationNode in self.annotationNodes():
            displayNode = annotationNode.GetDisplayNode()
            if displayNode is None:
                continue
            handlesVisible = annotationNode == selectedAnnotationNode
            color = self.annotationEditingColor() if handlesVisible else self.annotationColor()
            try:
                displayNode.SetColor(color)
            except TypeError:
                displayNode.SetColor(*color)
            if hasattr(displayNode, "SetSelectedColor"):
                try:
                    displayNode.SetSelectedColor(color)
                except TypeError:
                    displayNode.SetSelectedColor(*color)
            self.setMarkupHandlesVisible(displayNode, handlesVisible)

    def setMarkupHandlesVisible(self, displayNode, visible: bool) -> None:
        if hasattr(displayNode, "SetHandlesInteractive"):
            displayNode.SetHandlesInteractive(visible)

        handled = False
        if hasattr(displayNode, "SetScaleHandleVisibility"):
            displayNode.SetScaleHandleVisibility(visible)
            handled = True
        if hasattr(displayNode, "SetTranslationHandleVisibility"):
            displayNode.SetTranslationHandleVisibility(visible)
            handled = True
        if hasattr(displayNode, "SetRotationHandleVisibility"):
            displayNode.SetRotationHandleVisibility(False)
            handled = True
        if handled:
            return

        if not hasattr(displayNode, "SetHandleVisibility"):
            return

        try:
            displayNode.SetHandleVisibility(visible)
            return
        except TypeError:
            pass

        for handleType in self.markupHandleTypes(displayNode):
            try:
                displayNode.SetHandleVisibility(handleType, visible)
            except TypeError:
                continue

    def markupHandleTypes(self, displayNode) -> list[int]:
        handleTypeNames = (
            "ScaleHandle",
            "TranslationHandle",
            "RotationHandle",
            "InteractionHandle",
        )
        handleTypes = []
        for handleTypeName in handleTypeNames:
            if hasattr(displayNode, handleTypeName):
                handleTypes.append(int(getattr(displayNode, handleTypeName)))
            elif hasattr(slicer.vtkMRMLMarkupsDisplayNode, handleTypeName):
                handleTypes.append(int(getattr(slicer.vtkMRMLMarkupsDisplayNode, handleTypeName)))
        if handleTypes:
            return handleTypes
        return list(range(1, 8))

    def annotationColor(self) -> tuple[float, float, float]:
        return 0.0, 0.8, 0.25

    def annotationEditingColor(self) -> tuple[float, float, float]:
        return 1.0, 0.0, 1.0

    def clearAnnotations(self) -> int:
        nodesToRemove = self.annotationNodes()
        for node in nodesToRemove:
            self.removeAnnotationNode(node)
        return len(nodesToRemove)

    def removeAnnotationNode(self, annotationNode) -> None:
        self.removeAnnotationLabelNodesFor(annotationNode)
        slicer.mrmlScene.RemoveNode(annotationNode)

    def clearAnnotationLabelNodes(self) -> int:
        nodesToRemove = self.annotationLabelNodes()
        for labelNode in nodesToRemove:
            slicer.mrmlScene.RemoveNode(labelNode)
        for annotationNode in self.annotationNodes():
            annotationNode.SetAttribute("DetectionViewer.AnnotationLabelNodeID", "")
        return len(nodesToRemove)

    def removeAnnotationLabelNodesFor(self, annotationNode) -> int:
        annotationNodeId = annotationNode.GetID()
        labelNodeId = annotationNode.GetAttribute("DetectionViewer.AnnotationLabelNodeID")
        nodesToRemove = []
        if labelNodeId:
            labelNode = slicer.mrmlScene.GetNodeByID(labelNodeId)
            if labelNode is not None:
                nodesToRemove.append(labelNode)
        nodesToRemove.extend(
            labelNode
            for labelNode in self.annotationLabelNodes()
            if labelNode.GetAttribute(self.ANNOTATION_LABEL_FOR_ATTRIBUTE) == annotationNodeId
            and labelNode not in nodesToRemove
        )
        for labelNode in nodesToRemove:
            slicer.mrmlScene.RemoveNode(labelNode)
        annotationNode.SetAttribute("DetectionViewer.AnnotationLabelNodeID", "")
        return len(nodesToRemove)

    def annotationLabelNodes(self) -> list[vtk.vtkObject]:
        return [
            node
            for node in slicer.util.getNodesByClass("vtkMRMLMarkupsFiducialNode")
            if node.GetAttribute(self.ANNOTATION_LABEL_ATTRIBUTE) == "1"
        ]

    def annotationNodes(self) -> list[vtk.vtkObject]:
        nodes = [
            node
            for node in slicer.util.getNodesByClass("vtkMRMLMarkupsROINode")
            if node.GetAttribute(self.ANNOTATION_BOX_ATTRIBUTE) == "1"
        ]
        return sorted(nodes, key=lambda node: int(node.GetAttribute("DetectionViewer.AnnotationIndex") or 0))

    def nextAnnotationIndex(self) -> int:
        indexes = [
            int(node.GetAttribute("DetectionViewer.AnnotationIndex") or 0)
            for node in self.annotationNodes()
        ]
        return max(indexes, default=0) + 1

    def annotationDisplayName(self, annotationNode) -> str:
        index = annotationNode.GetAttribute("DetectionViewer.AnnotationIndex") or "-"
        label = annotationNode.GetAttribute("DetectionViewer.AnnotationLabel") or "0"
        sourceIndex = annotationNode.GetAttribute("DetectionViewer.SourceDetectionIndex")
        if sourceIndex:
            return f"A{index} {label} (det {sourceIndex})"
        return f"A{index} {label}"

    def nodeBounds(self, node) -> tuple[float, float, float, float, float, float]:
        if node.IsA("vtkMRMLMarkupsROINode"):
            center = self.roiCenter(node)
            size = self.roiSize(node)
            return self.boundsFromCenterSize(center, size)

        bounds = [0.0] * 6
        try:
            node.GetBounds(bounds)
        except TypeError:
            bounds = list(node.GetBounds())
        return tuple(float(value) for value in bounds)

    def annotationNodeCenter(self, annotationNode) -> tuple[float, float, float]:
        if annotationNode.IsA("vtkMRMLMarkupsROINode"):
            return self.roiCenter(annotationNode)
        xMin, xMax, yMin, yMax, zMin, zMax = self.nodeBounds(annotationNode)
        return (xMin + xMax) / 2.0, (yMin + yMax) / 2.0, (zMin + zMax) / 2.0

    def annotationNodeSize(self, annotationNode) -> tuple[float, float, float]:
        if annotationNode.IsA("vtkMRMLMarkupsROINode"):
            return self.roiSize(annotationNode)
        xMin, xMax, yMin, yMax, zMin, zMax = self.nodeBounds(annotationNode)
        return max(xMax - xMin, 0.1), max(yMax - yMin, 0.1), max(zMax - zMin, 0.1)

    def setRoiBounds(self, roiNode, bounds: tuple[float, float, float, float, float, float]) -> None:
        center = (
            (bounds[0] + bounds[1]) / 2.0,
            (bounds[2] + bounds[3]) / 2.0,
            (bounds[4] + bounds[5]) / 2.0,
        )
        size = (
            max(bounds[1] - bounds[0], 0.1),
            max(bounds[3] - bounds[2], 0.1),
            max(bounds[5] - bounds[4], 0.1),
        )
        if hasattr(roiNode, "SetROIType") and hasattr(slicer.vtkMRMLMarkupsROINode, "ROITypeBox"):
            roiNode.SetROIType(slicer.vtkMRMLMarkupsROINode.ROITypeBox)
        self.setRoiCenter(roiNode, center)
        self.setRoiSize(roiNode, size)

    def setRoiCenter(self, roiNode, center: tuple[float, float, float]) -> None:
        if hasattr(roiNode, "SetCenter"):
            try:
                roiNode.SetCenter(center)
            except TypeError:
                roiNode.SetCenter(*center)
        elif hasattr(roiNode, "SetXYZ"):
            roiNode.SetXYZ(*center)
        else:
            raise RuntimeError("ROI node does not support center editing")

    def setRoiSize(self, roiNode, size: tuple[float, float, float]) -> None:
        if hasattr(roiNode, "SetSize"):
            try:
                roiNode.SetSize(size)
            except TypeError:
                roiNode.SetSize(*size)
        elif hasattr(roiNode, "SetRadiusXYZ"):
            roiNode.SetRadiusXYZ(size[0] / 2.0, size[1] / 2.0, size[2] / 2.0)
        else:
            raise RuntimeError("ROI node does not support size editing")

    def roiCenter(self, roiNode) -> tuple[float, float, float]:
        center = [0.0, 0.0, 0.0]
        if hasattr(roiNode, "GetCenter"):
            try:
                roiNode.GetCenter(center)
                return tuple(float(value) for value in center)
            except TypeError:
                return tuple(float(value) for value in roiNode.GetCenter())
        if hasattr(roiNode, "GetXYZ"):
            roiNode.GetXYZ(center)
            return tuple(float(value) for value in center)
        raise RuntimeError("ROI node does not support center reading")

    def roiSize(self, roiNode) -> tuple[float, float, float]:
        size = [0.0, 0.0, 0.0]
        if hasattr(roiNode, "GetSize"):
            try:
                roiNode.GetSize(size)
                return tuple(max(float(value), 0.1) for value in size)
            except TypeError:
                return tuple(max(float(value), 0.1) for value in roiNode.GetSize())
        if hasattr(roiNode, "GetRadiusXYZ"):
            roiNode.GetRadiusXYZ(size)
            return tuple(max(float(value) * 2.0, 0.1) for value in size)
        raise RuntimeError("ROI node does not support size reading")

    def boundsFromCenterSize(
        self,
        center: tuple[float, float, float],
        size: tuple[float, float, float],
    ) -> tuple[float, float, float, float, float, float]:
        cx, cy, cz = center
        sx, sy, sz = [max(float(value), 0.1) for value in size]
        return (
            cx - sx / 2.0,
            cx + sx / 2.0,
            cy - sy / 2.0,
            cy + sy / 2.0,
            cz - sz / 2.0,
            cz + sz / 2.0,
        )

    def currentSliceCenterRAS(self) -> tuple[float, float, float] | None:
        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            return None
        for sliceName in ("Red", "Yellow", "Green"):
            sliceWidget = layoutManager.sliceWidget(sliceName)
            if sliceWidget is None:
                continue
            sliceNode = sliceWidget.mrmlSliceNode()
            if sliceNode is None or sliceNode.GetSliceToRAS() is None:
                continue
            ras = sliceNode.GetSliceToRAS().MultiplyPoint((0.0, 0.0, 0.0, 1.0))
            return ras[0], ras[1], ras[2]
        return None

    def volumeCenterRAS(self, volumeNode: vtkMRMLScalarVolumeNode | None) -> tuple[float, float, float] | None:
        if volumeNode is None:
            return None
        bounds = [0.0] * 6
        try:
            volumeNode.GetRASBounds(bounds)
        except Exception:
            return None
        if bounds[0] > bounds[1] or bounds[2] > bounds[3] or bounds[4] > bounds[5]:
            return None
        return (
            (bounds[0] + bounds[1]) / 2.0,
            (bounds[2] + bounds[3]) / 2.0,
            (bounds[4] + bounds[5]) / 2.0,
        )

    def detectionJsonHasAnnotation(self, detectionPath: str) -> bool:
        detectionData = self.readDetectionData(detectionPath)
        return "annotation" in detectionData

    def saveAnnotationsToDetectionJson(self, detectionPath: str) -> int:
        detectionData = self.readDetectionData(detectionPath)
        annotations = [self.annotationNodeToDict(node) for node in self.annotationNodes()]
        detectionData["annotation"] = annotations
        with open(detectionPath, "w", encoding="utf-8") as detectionFile:
            json.dump(detectionData, detectionFile, ensure_ascii=False, indent=2)
        return len(annotations)

    def annotationNodeToDict(self, annotationNode) -> dict[str, Any]:
        xMin, xMax, yMin, yMax, zMin, zMax = self.nodeBounds(annotationNode)
        center = self.annotationNodeCenter(annotationNode)
        size = self.annotationNodeSize(annotationNode)
        annotation = {
            "index": int(annotationNode.GetAttribute("DetectionViewer.AnnotationIndex") or 0),
            "label": annotationNode.GetAttribute("DetectionViewer.AnnotationLabel") or "",
            "box_mode": "xyzxyz",
            "box_xyzxyz_ras": [xMin, yMin, zMin, xMax, yMax, zMax],
            "box_cccwhd_ras": [center[0], center[1], center[2], size[0], size[1], size[2]],
            "size_mm": [size[0], size[1], size[2]],
        }
        sourceIndex = annotationNode.GetAttribute("DetectionViewer.SourceDetectionIndex")
        if sourceIndex:
            annotation["source_detection_index"] = int(sourceIndex)
        sourceScore = annotationNode.GetAttribute("DetectionViewer.SourceScore")
        if sourceScore:
            annotation["source_score"] = float(sourceScore)
        return annotation


