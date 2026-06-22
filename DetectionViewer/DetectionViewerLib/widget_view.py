import logging
import os
from datetime import datetime
from typing import Any

import qt
import slicer
import vtk
from slicer.i18n import tr as _
from slicer.ScriptedLoadableModule import ScriptedLoadableModuleWidget
from slicer.util import VTKObservationMixin

class ViewWidgetMixin:
    def onRefreshDisplayButton(self) -> None:
        self._loadedAnnotationPath = None
        with self.progressDialog(_("Refreshing display...")) as progress:
            self.autoRefreshDetectionBoxes(progress=progress)

    def autoRefreshDetectionBoxes(self, caller=None, event=None, progress=None) -> None:
        if self._autoRefreshingDetectionBoxes or self._sceneClosing or self._loadingDatasetCase:
            return

        self._autoRefreshingDetectionBoxes = True
        try:
            inputVolume = self.inputVolumeNode()
            detectionPath = self.currentDetectionPath()
            if inputVolume and (not detectionPath or not os.path.isfile(detectionPath)):
                if progress:
                    progress.update(labelText=_("Finding detection JSON next to volume..."))
                detectedPath = self.logic.findDetectionJsonForVolumeNode(inputVolume)
                if detectedPath:
                    self.setDetectionPath(detectedPath)
                    detectionPath = detectedPath

            if not inputVolume or not os.path.isfile(detectionPath):
                if progress:
                    progress.update(labelText=_("Clearing display..."))
                self.logic.clearDetectionBoxes()
                self.unobserveAnnotationNodes()
                self.logic.clearAnnotations()
                self._loadedAnnotationPath = None
                self.refreshAnnotationOptions()
                self.refreshLocateIndexOptions([])
                self.clearLocateInfoTable()
                if not inputVolume:
                    self.ui.statusLabel.text = _("Select an input volume")
                elif detectionPath:
                    self.ui.statusLabel.text = _("Detection JSON not found")
                else:
                    self.ui.statusLabel.text = _("Select a detection JSON")
                return

            maxDetections = int(self.ui.maxDetectionsSpinBox.value)
            minScore = float(self.ui.minScoreSpinBox.value)
            if progress:
                progress.update(labelText=_("Creating detection boxes..."), value=0, maximum=0)

            def updateDetectionProgress(currentCount: int, totalCount: int) -> None:
                if not progress:
                    return
                maximum = max(totalCount, 1)
                value = currentCount if totalCount > 0 else 1
                progress.update(
                    labelText=_("Creating detection boxes... {0}/{1}").format(currentCount, totalCount),
                    value=value,
                    maximum=maximum,
                )

            createdNodes = self.logic.createDetectionBoxes(
                detectionPath,
                inputVolume,
                minScore=minScore,
                maxDetections=maxDetections if maxDetections > 0 else None,
                lpsToRas=self.ui.detectLpsRadioButton.checked,
                progressCallback=updateDetectionProgress if progress else None,
            )
            self.ui.statusLabel.text = _("Displayed {0} detection boxes").format(len(createdNodes))
            if progress:
                progress.update(labelText=_("Updating view controls..."))
            self.logic.setDetectionBoxesVisible(self.ui.showDetectionBoxesCheckBox.checked)
            self.refreshLocateIndexOptions(createdNodes)
            self.clearLocateInfoTable()
            if self._loadedAnnotationPath != os.path.abspath(detectionPath):
                if progress:
                    progress.update(labelText=_("Loading annotations..."))
                self.unobserveAnnotationNodes()
                annotationNodes = self.logic.loadAnnotationsFromDetectionPath(detectionPath)
                self._loadedAnnotationPath = os.path.abspath(detectionPath)
                self.refreshAnnotationOptions(annotationNodes[0] if annotationNodes else None)
                self._annotationsDirty = False
                if annotationNodes:
                    self.ui.statusLabel.text = _("Displayed {0} detection boxes; loaded {1} annotations").format(
                        len(createdNodes),
                        len(annotationNodes),
                    )
        except Exception as exc:
            logging.exception("Failed to auto-refresh detection boxes")
            self.logic.clearDetectionBoxes()
            self.refreshLocateIndexOptions([])
            self.clearLocateInfoTable()
            self.ui.statusLabel.text = _("Failed to display detection boxes: {0}").format(exc)
        finally:
            self._autoRefreshingDetectionBoxes = False

    def onLocateIndexChanged(self, index: int) -> None:
        if self._updatingLocateIndexOptions or index < 0:
            return
        self.locateSelectedBox()

    def onPreviousBoxButton(self) -> None:
        count = self.ui.locateIndexComboBox.count
        if count <= 1:
            self.ui.statusLabel.text = _("No detection boxes are displayed")
            return
        currentIndex = self.ui.locateIndexComboBox.currentIndex
        nextIndex = count - 1 if currentIndex <= 1 else currentIndex - 1
        self._updatingLocateIndexOptions = True
        self.ui.locateIndexComboBox.setCurrentIndex(nextIndex)
        self._updatingLocateIndexOptions = False
        self.locateSelectedBox()

    def onNextBoxButton(self) -> None:
        count = self.ui.locateIndexComboBox.count
        if count <= 1:
            self.ui.statusLabel.text = _("No detection boxes are displayed")
            return
        currentIndex = self.ui.locateIndexComboBox.currentIndex
        nextIndex = 1 if currentIndex <= 0 or currentIndex >= count - 1 else currentIndex + 1
        self._updatingLocateIndexOptions = True
        self.ui.locateIndexComboBox.setCurrentIndex(nextIndex)
        self._updatingLocateIndexOptions = False
        self.locateSelectedBox()

    def locateSelectedBox(self) -> None:
        currentText = self.ui.locateIndexComboBox.currentText.strip()
        if currentText == "":
            self.logic.clearDetectionHighlight()
            self.clearLocateInfoTable()
            self.ui.statusLabel.text = _("No detection box selected for view")
            return

        if self.ui.locateIndexComboBox.count <= 1:
            self.ui.statusLabel.text = _("No detection boxes are displayed")
            return

        detectionIndex = int(currentText)
        boxNode = self.logic.findDetectionBoxByIndex(detectionIndex)
        if boxNode is None:
            self.ui.statusLabel.text = _("Detection index {0} is not displayed").format(detectionIndex)
            return

        self.logic.centerViewsOnBoxes(
            [boxNode],
            fitToBounds=self.ui.locateAutoFovCheckBox.checked,
            fovZoomFactor=float(self.ui.locateFovZoomSpinBox.value),
        )
        self.logic.highlightDetectionBox(boxNode)
        self.setLocateInfoRows(self.logic.detectionBoxInfoRows(boxNode))
        self.ui.statusLabel.text = _("Viewing detection index {0}").format(detectionIndex)

    def onLocateFovControlChanged(self, value=None) -> None:
        if self.ui.locateIndexComboBox.currentText.strip():
            self.locateSelectedBox()

    def onShowDetectionBoxesChanged(self, checked: bool) -> None:
        self.logic.setDetectionBoxesVisible(checked)

    def setupLocateInfoTable(self) -> None:
        table = self.ui.locateInfoTable
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Field", "Value"])
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(qt.QAbstractItemView.SelectRows)
        table.setAlternatingRowColors(True)

    def clearLocateInfoTable(self) -> None:
        self.ui.locateInfoTable.setRowCount(0)

    def setLocateInfoRows(self, rows: list[tuple[str, str]]) -> None:
        table = self.ui.locateInfoTable
        table.setRowCount(len(rows))
        for rowIndex, (field, value) in enumerate(rows):
            table.setItem(rowIndex, 0, qt.QTableWidgetItem(field))
            table.setItem(rowIndex, 1, qt.QTableWidgetItem(value))
        table.resizeRowsToContents()

    def refreshLocateIndexOptions(self, boxNodes) -> None:
        indexes = sorted(
            {
                int(node.GetAttribute("DetectionViewer.Index"))
                for node in boxNodes
                if node.GetAttribute("DetectionViewer.Index") is not None
            }
        )

        self._updatingLocateIndexOptions = True
        try:
            self.ui.locateIndexComboBox.clear()
            self.ui.locateIndexComboBox.addItem("")
            for detectionIndex in indexes:
                self.ui.locateIndexComboBox.addItem(str(detectionIndex))
        finally:
            self._updatingLocateIndexOptions = False

