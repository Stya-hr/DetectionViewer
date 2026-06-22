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

class ViewLogicMixin:
    def centerViewsOnBoxes(
        self,
        boxNodes: list[vtk.vtkObject],
        fitToBounds: bool = False,
        fovZoomFactor: float = 1.0,
    ) -> None:
        if not boxNodes:
            return
        bounds = self.boundsForNodes(boxNodes)
        if bounds is not None:
            xMin, xMax, yMin, yMax, zMin, zMax = bounds
            center = ((xMin + xMax) / 2.0, (yMin + yMax) / 2.0, (zMin + zMax) / 2.0)
            self.jumpSlicesToLocation(center)
            if fitToBounds:
                self.fitSliceViewsToBounds(bounds, fovZoomFactor)

    def boundsForNodes(self, nodes: list[vtk.vtkObject]) -> tuple[float, float, float, float, float, float] | None:
        validBounds = []
        for node in nodes:
            nodeBounds = [0.0] * 6
            try:
                node.GetBounds(nodeBounds)
            except TypeError:
                nodeBounds = list(node.GetBounds())
            except AttributeError:
                continue
            if nodeBounds[0] <= nodeBounds[1] and nodeBounds[2] <= nodeBounds[3] and nodeBounds[4] <= nodeBounds[5]:
                validBounds.append(nodeBounds)

        if not validBounds:
            return None

        return (
            min(bounds[0] for bounds in validBounds),
            max(bounds[1] for bounds in validBounds),
            min(bounds[2] for bounds in validBounds),
            max(bounds[3] for bounds in validBounds),
            min(bounds[4] for bounds in validBounds),
            max(bounds[5] for bounds in validBounds),
        )

    def jumpSlicesToLocation(self, rasPoint: tuple[float, float, float]) -> None:
        x, y, z = rasPoint
        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            return

        for sliceName in ("Red", "Yellow", "Green"):
            sliceWidget = layoutManager.sliceWidget(sliceName)
            if sliceWidget is None:
                continue
            sliceNode = sliceWidget.mrmlSliceNode()
            if sliceNode is None or not hasattr(sliceNode, "JumpSliceByCentering"):
                continue
            sliceNode.JumpSliceByCentering(x, y, z)

    def fitSliceViewsToBounds(
        self,
        bounds: tuple[float, float, float, float, float, float],
        fovZoomFactor: float = 1.0,
    ) -> None:
        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            return
        for sliceName in ("Red", "Yellow", "Green"):
            sliceWidget = layoutManager.sliceWidget(sliceName)
            if sliceWidget is None:
                continue

            sliceNode = sliceWidget.mrmlSliceNode()
            if sliceNode is None:
                continue
            boxWidth, boxHeight = self.boxSizeInSliceXY(bounds, sliceNode)
            if boxWidth is None or boxHeight is None:
                continue
            widthPx, heightPx = self.sliceViewPixelSize(sliceWidget)
            fovWidth, fovHeight = self.fieldOfViewForBox(
                boxWidth,
                boxHeight,
                widthPx,
                heightPx,
                fovZoomFactor,
            )
            currentFov = sliceNode.GetFieldOfView()
            sliceNode.SetFieldOfView(fovWidth, fovHeight, currentFov[2])

    def sliceViewPixelSize(self, sliceWidget) -> tuple[int, int]:
        sliceView = sliceWidget.sliceView()
        size = sliceView.size() if callable(getattr(sliceView, "size", None)) else sliceView.size
        width = size.width() if callable(getattr(size, "width", None)) else self.widgetDimension(sliceView, "width")
        height = size.height() if callable(getattr(size, "height", None)) else self.widgetDimension(sliceView, "height")
        return max(int(width), 1), max(int(height), 1)

    def widgetDimension(self, widget, name: str) -> int:
        value = getattr(widget, name)
        return value() if callable(value) else value

    def boxSizeInSliceXY(
        self,
        bounds: tuple[float, float, float, float, float, float],
        sliceNode,
    ) -> tuple[float | None, float | None]:
        xyToRas = sliceNode.GetXYToRAS()
        if xyToRas is None:
            return None, None

        xAxis = self.normalizedMatrixColumn(xyToRas, 0)
        yAxis = self.normalizedMatrixColumn(xyToRas, 1)
        if xAxis is None or yAxis is None:
            return None, None

        xMin, xMax, yMin, yMax, zMin, zMax = bounds
        xProjections = []
        yProjections = []
        for x in (xMin, xMax):
            for y in (yMin, yMax):
                for z in (zMin, zMax):
                    rasPoint = (x, y, z)
                    xProjections.append(self.dot(rasPoint, xAxis))
                    yProjections.append(self.dot(rasPoint, yAxis))

        return (
            max(max(xProjections) - min(xProjections), 1.0),
            max(max(yProjections) - min(yProjections), 1.0),
        )

    def normalizedMatrixColumn(self, matrix, column: int) -> tuple[float, float, float] | None:
        vector = (
            float(matrix.GetElement(0, column)),
            float(matrix.GetElement(1, column)),
            float(matrix.GetElement(2, column)),
        )
        length = vtk.vtkMath.Norm(vector)
        if length <= 0.0:
            return None
        return vector[0] / length, vector[1] / length, vector[2] / length

    def dot(self, left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
        return left[0] * right[0] + left[1] * right[1] + left[2] * right[2]

    def fieldOfViewForBox(
        self,
        boxWidth: float,
        boxHeight: float,
        viewWidthPx: int,
        viewHeightPx: int,
        zoomFactor: float = 1.0,
    ) -> tuple[float, float]:
        margin = 4.0
        minFovMm = 10.0
        zoomFactor = max(float(zoomFactor), 0.1)

        targetWidth = max(boxWidth * margin / zoomFactor, minFovMm)
        targetHeight = max(boxHeight * margin / zoomFactor, minFovMm)
        viewAspect = max(viewWidthPx / viewHeightPx, 0.01)
        targetAspect = targetWidth / targetHeight

        if targetAspect > viewAspect:
            fovWidth = targetWidth
            fovHeight = targetWidth / viewAspect
        else:
            fovHeight = targetHeight
            fovWidth = targetHeight * viewAspect

        fovWidth = max(fovWidth, minFovMm)
        fovHeight = max(fovHeight, minFovMm)
        return fovWidth, fovHeight


