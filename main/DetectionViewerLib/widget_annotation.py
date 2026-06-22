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

class AnnotationWidgetMixin:
    def onAnnotationSelectionChanged(self, index: int) -> None:
        if self._updatingAnnotationOptions or index < 0:
            return
        annotationNode = self.selectedAnnotationNode()
        if annotationNode is not None:
            self.logic.clearDetectionHighlight()
        self.logic.setSelectedAnnotationHandles(annotationNode)
        self.setAnnotationEditorFromNode(annotationNode)

    def onAddSelectedDetectionButton(self) -> None:
        currentText = self.ui.locateIndexComboBox.currentText.strip()
        if not currentText:
            self.ui.statusLabel.text = _("Select a detection index in View first")
            return

        detectionNode = self.logic.findDetectionBoxByIndex(int(currentText))
        if detectionNode is None:
            self.ui.statusLabel.text = _("Selected detection is not displayed")
            return

        annotationNode = self.logic.createAnnotationFromDetectionNode(detectionNode, self.annotationEditorLabel())
        self.refreshAnnotationOptions(annotationNode)
        self.setAnnotationEditorFromNode(annotationNode)
        self.markAnnotationsDirty()
        self.ui.statusLabel.text = _("Copied detection {0} to annotations").format(currentText)

    def onAddEmptyAnnotationButton(self) -> None:
        center = self.logic.currentSliceCenterRAS()
        if center is None:
            center = self.logic.volumeCenterRAS(self.inputVolumeNode())
        if center is None:
            self.ui.statusLabel.text = _("No valid view or volume for adding annotation")
            return

        annotationNode = self.logic.createEmptyAnnotation(center, self.annotationEditorLabel())
        self.refreshAnnotationOptions(annotationNode)
        self.setAnnotationEditorFromNode(annotationNode)
        self.markAnnotationsDirty()
        self.ui.statusLabel.text = _("Added empty annotation")

    def onUpdateAnnotationButton(self) -> None:
        annotationNode = self.selectedAnnotationNode()
        if annotationNode is None:
            self.ui.statusLabel.text = _("Select an annotation first")
            return

        self.logic.updateAnnotationNode(annotationNode, self.annotationEditorLabel())
        self.refreshAnnotationOptions(annotationNode)
        self.setAnnotationEditorFromNode(annotationNode)
        self.markAnnotationsDirty()
        self.ui.statusLabel.text = _("Updated annotation")

    def onDeleteAnnotationButton(self) -> None:
        annotationNode = self.selectedAnnotationNode()
        if annotationNode is None:
            self.ui.statusLabel.text = _("Select an annotation first")
            return

        self.unobserveAnnotationNode(annotationNode)
        self.logic.removeAnnotationNode(annotationNode)
        self.refreshAnnotationOptions()
        self.markAnnotationsDirty()
        self.ui.statusLabel.text = _("Deleted annotation")

    def onSaveAnnotationsButton(self) -> None:
        count = self.saveCurrentAnnotations()
        if count is not None:
            self.ui.statusLabel.text = _("Saved {0} annotations to detection JSON").format(count)

    def saveCurrentAnnotations(self) -> int | None:
        detectionPath = self.currentDetectionPath()
        if not os.path.isfile(detectionPath):
            self.ui.statusLabel.text = _("Select a detection JSON first")
            return None

        if self.logic.detectionJsonHasAnnotation(detectionPath):
            answer = qt.QMessageBox.question(
                self.parent,
                _("Overwrite annotations"),
                _("This detection JSON already contains annotation. Overwrite it?"),
                qt.QMessageBox.Yes | qt.QMessageBox.No,
                qt.QMessageBox.No,
            )
            if answer != qt.QMessageBox.Yes:
                self.ui.statusLabel.text = _("Annotation save canceled")
                return None

        with slicer.util.tryWithErrorDisplay(_("Failed to save annotations."), waitCursor=True):
            with self.progressDialog(_("Saving annotations...")) as progress:
                progress.update(labelText=_("Writing annotations to detection JSON...\n{0}").format(detectionPath))
                count = self.logic.saveAnnotationsToDetectionJson(detectionPath)
                progress.update(labelText=_("Updating dataset index..."))
                self._loadedAnnotationPath = os.path.abspath(detectionPath)
                self._annotationsDirty = False
                self.updateCurrentDatasetCaseAfterSave(count)
                self.updateCurrentCaseSummary()
                return count

    def annotationEditorLabel(self) -> str:
        label = self.ui.annotationLabelLineEdit.text.strip()
        return label if label else "0"

    def selectedAnnotationNode(self):
        index = self.ui.annotationSelectorComboBox.currentIndex
        if index < 0:
            return None
        nodeId = self.ui.annotationSelectorComboBox.itemData(index)
        if not nodeId:
            return None
        return slicer.mrmlScene.GetNodeByID(str(nodeId))

    def refreshAnnotationOptions(self, selectedNode=None) -> None:
        selectedNodeId = selectedNode.GetID() if selectedNode is not None else None
        if selectedNodeId is None and self.ui.annotationSelectorComboBox.currentIndex >= 0:
            currentData = self.ui.annotationSelectorComboBox.itemData(self.ui.annotationSelectorComboBox.currentIndex)
            selectedNodeId = str(currentData) if currentData else None

        annotationNodes = self.logic.annotationNodes()
        self._updatingAnnotationOptions = True
        try:
            self.ui.annotationSelectorComboBox.clear()
            self.ui.annotationSelectorComboBox.addItem("")
            for annotationNode in annotationNodes:
                self.ui.annotationSelectorComboBox.addItem(self.logic.annotationDisplayName(annotationNode))
                self.ui.annotationSelectorComboBox.setItemData(
                    self.ui.annotationSelectorComboBox.count - 1,
                    annotationNode.GetID(),
                )

            if selectedNodeId:
                for index in range(self.ui.annotationSelectorComboBox.count):
                    if str(self.ui.annotationSelectorComboBox.itemData(index)) == selectedNodeId:
                        self.ui.annotationSelectorComboBox.setCurrentIndex(index)
                        break
        finally:
            self._updatingAnnotationOptions = False

        selectedAnnotationNode = self.selectedAnnotationNode()
        if selectedAnnotationNode is not None:
            self.logic.clearDetectionHighlight()
        self.logic.setSelectedAnnotationHandles(selectedAnnotationNode)
        self.setAnnotationEditorFromNode(selectedAnnotationNode)

    def setAnnotationEditorFromNode(self, annotationNode) -> None:
        if annotationNode is None:
            self.clearAnnotationInfoTable()
            return
        self._updatingAnnotationEditor = True
        try:
            annotationNodeId = annotationNode.GetID()
            if annotationNodeId and annotationNodeId not in self._observedAnnotationNodeIds:
                self.addObserver(annotationNode, vtk.vtkCommand.ModifiedEvent, self.onSelectedAnnotationModified)
                self._observedAnnotationNodeIds.add(annotationNodeId)
        except Exception:
            logging.debug("Could not observe selected annotation node", exc_info=True)
        try:
            label = annotationNode.GetAttribute("DetectionViewer.AnnotationLabel") or "0"
            self.ui.annotationLabelLineEdit.text = label
            self.setAnnotationInfoRows(self.logic.annotationInfoRows(annotationNode))
        finally:
            self._updatingAnnotationEditor = False

    def onSelectedAnnotationModified(self, caller=None, event=None) -> None:
        if self._updatingAnnotationEditor or caller != self.selectedAnnotationNode():
            return
        self.logic.setSelectedAnnotationHandles(caller)
        self.setAnnotationEditorFromNode(caller)
        self.markAnnotationsDirty()

    def markAnnotationsDirty(self) -> None:
        self._annotationsDirty = True
        self.updateCurrentCaseSummary()

    def setupAnnotationInfoTable(self) -> None:
        table = self.ui.annotationInfoTable
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Field", "Value"])
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(qt.QAbstractItemView.SelectRows)
        table.setAlternatingRowColors(True)

    def clearAnnotationInfoTable(self) -> None:
        self.ui.annotationInfoTable.setRowCount(0)

    def setAnnotationInfoRows(self, rows: list[tuple[str, str]]) -> None:
        table = self.ui.annotationInfoTable
        table.setRowCount(len(rows))
        for rowIndex, (field, value) in enumerate(rows):
            table.setItem(rowIndex, 0, qt.QTableWidgetItem(field))
            table.setItem(rowIndex, 1, qt.QTableWidgetItem(value))
        table.resizeRowsToContents()

    def unobserveAnnotationNode(self, annotationNode) -> None:
        annotationNodeId = annotationNode.GetID()
        if annotationNodeId not in self._observedAnnotationNodeIds:
            return
        try:
            if self.hasObserver(annotationNode, vtk.vtkCommand.ModifiedEvent, self.onSelectedAnnotationModified):
                self.removeObserver(annotationNode, vtk.vtkCommand.ModifiedEvent, self.onSelectedAnnotationModified)
        except Exception:
            logging.debug("Could not remove annotation observer", exc_info=True)
        self._observedAnnotationNodeIds.discard(annotationNodeId)

    def unobserveAnnotationNodes(self) -> None:
        for annotationNode in self.logic.annotationNodes():
            self.unobserveAnnotationNode(annotationNode)

