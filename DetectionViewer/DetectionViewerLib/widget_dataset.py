import logging
import os
import html
from datetime import datetime
from typing import Any

import qt
import slicer
import vtk
from slicer.i18n import tr as _
from slicer.ScriptedLoadableModule import ScriptedLoadableModuleWidget
from slicer.util import VTKObservationMixin

class DatasetWidgetMixin:
    def setupCurrentCaseStatusLabel(self) -> None:
        self.ui.currentCaseLabel.setTextFormat(qt.Qt.RichText)
        self.ui.currentCaseLabel.setWordWrap(False)
        self.ui.currentCaseLabel.setStyleSheet("QLabel { padding: 2px 0; }")

    def onBrowseDatasetButton(self) -> None:
        startPath = self.ui.datasetRootLineEdit.text.strip()
        if not startPath:
            startPath = os.path.expanduser("~")
        directoryPath = qt.QFileDialog.getExistingDirectory(
            self.parent,
            _("Select dataset root"),
            startPath,
        )
        if directoryPath:
            self.ui.datasetRootLineEdit.text = directoryPath
            self.loadDatasetRoot(forceScan=False)

    def onScanDatasetButton(self) -> None:
        self.loadDatasetRoot(forceScan=True)

    def onDatasetRootEditingFinished(self) -> None:
        self.loadDatasetRoot(forceScan=False)

    def loadDatasetRoot(self, forceScan: bool = False) -> None:
        rootPath = self.ui.datasetRootLineEdit.text.strip()
        if not rootPath:
            self.ui.statusLabel.text = _("Select a dataset root first")
            return
        if not os.path.isdir(rootPath):
            self.ui.statusLabel.text = _("Dataset root not found")
            return

        actionText = _("scan dataset") if forceScan else _("load dataset")
        with slicer.util.tryWithErrorDisplay(_("Failed to {0}.").format(actionText), waitCursor=True):
            progressTitle = _("Scanning dataset...") if forceScan else _("Loading dataset...")
            with self.progressDialog(progressTitle) as progress:
                def updateScanProgress(visitedDirectoryCount: int, foundCaseCount: int, directoryPath: str) -> None:
                    progress.update(
                        labelText=_("Scanning dataset... {0} cases found, {1} folders checked\n{2}").format(
                            foundCaseCount,
                            visitedDirectoryCount,
                            directoryPath,
                        )
                    )

                if forceScan:
                    datasetCases = self.logic.scanDataset(rootPath, progressCallback=updateScanProgress)
                    statusText = _("Scanned {0} dataset cases").format(len(datasetCases))
                else:
                    progress.update(labelText=_("Loading dataset index..."))
                    datasetCases = self.logic.loadDatasetFromIndex(rootPath)
                    if datasetCases:
                        statusText = _("Loaded {0} dataset cases from index").format(len(datasetCases))
                    else:
                        progress.update(labelText=_("No usable index found. Scanning dataset..."))
                        datasetCases = self.logic.scanDataset(rootPath, progressCallback=updateScanProgress)
                        statusText = _("No usable dataset index found; scanned {0} cases").format(len(datasetCases))
                progress.update(labelText=_("Updating dataset table..."))
                self._datasetCases = datasetCases
                self._currentDatasetCaseIndex = -1
                self.refreshDatasetCaseTable()
                self.updateCurrentCaseSummary()
                self.ui.statusLabel.text = statusText

    def setupDatasetFilters(self) -> None:
        self.ui.doneFilterComboBox.clear()
        self.ui.doneFilterComboBox.addItem(_("All"))
        self.ui.doneFilterComboBox.addItem(_("Not Done"))
        self.ui.doneFilterComboBox.addItem(_("Done"))

    def onDatasetFilterChanged(self, caller=None) -> None:
        self.refreshDatasetCaseTable()

    def filteredDatasetCaseIndices(self) -> list[int]:
        caseText = self.ui.caseFilterLineEdit.text.strip().lower()
        doneFilterIndex = self.ui.doneFilterComboBox.currentIndex
        filteredIndices = []
        for caseIndex, case in enumerate(self._datasetCases):
            caseId = str(case.get("display_id") or case.get("case_id", ""))
            if caseText and caseText not in caseId.lower():
                continue
            caseDone = bool(case.get("done", False))
            if doneFilterIndex == 2 and not caseDone:
                continue
            if doneFilterIndex == 1 and caseDone:
                continue
            filteredIndices.append(caseIndex)
        return filteredIndices

    def setupDatasetCaseTable(self) -> None:
        table = self.ui.datasetCaseTable
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(["Done", "Case", "Monai", "Annotation", "Last saved"])
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(qt.QAbstractItemView.SelectRows)
        table.setSelectionMode(qt.QAbstractItemView.SingleSelection)
        table.setAlternatingRowColors(True)
        table.setColumnWidth(0, 56)
        table.setColumnWidth(1, 150)
        table.setColumnWidth(2, 48)
        table.setColumnWidth(3, 78)
        table.setColumnWidth(4, 140)

    def refreshDatasetCaseTable(self) -> None:
        table = self.ui.datasetCaseTable
        self._updatingDatasetCaseTable = True
        try:
            self._filteredDatasetCaseIndices = self.filteredDatasetCaseIndices()
            table.setRowCount(len(self._filteredDatasetCaseIndices))
            selectedRow = -1
            for rowIndex, caseIndex in enumerate(self._filteredDatasetCaseIndices):
                case = self._datasetCases[caseIndex]
                values = [
                    "✓" if case.get("done", False) else "✗",
                    case.get("display_id") or case.get("case_id", ""),
                    str(case.get("raw_count", 0)),
                    str(case.get("annotation_count", 0)),
                    case.get("last_saved", ""),
                ]
                for columnIndex, value in enumerate(values):
                    item = qt.QTableWidgetItem(str(value))
                    if columnIndex == 0:
                        item.setTextAlignment(qt.Qt.AlignCenter)
                    table.setItem(rowIndex, columnIndex, item)
                if caseIndex == self._currentDatasetCaseIndex:
                    selectedRow = rowIndex
            if selectedRow >= 0:
                table.selectRow(selectedRow)
            else:
                table.clearSelection()
        finally:
            self._updatingDatasetCaseTable = False
        self.updateCurrentCaseSummary()

    def onDatasetCaseClicked(self, row: int, column: int) -> None:
        if self._updatingDatasetCaseTable:
            return
        if row < 0 or row >= len(self._filteredDatasetCaseIndices):
            return
        self.loadDatasetCase(self._filteredDatasetCaseIndices[row])

    def currentFilteredDatasetRow(self) -> int:
        try:
            return self._filteredDatasetCaseIndices.index(self._currentDatasetCaseIndex)
        except ValueError:
            return -1

    def onPreviousCaseButton(self) -> None:
        if not self._datasetCases:
            self.ui.statusLabel.text = _("Scan a dataset first")
            return
        if not self._filteredDatasetCaseIndices:
            self.ui.statusLabel.text = _("No cases match the current filter")
            return
        currentRow = self.currentFilteredDatasetRow()
        nextRow = len(self._filteredDatasetCaseIndices) - 1 if currentRow <= 0 else currentRow - 1
        self.loadDatasetCase(self._filteredDatasetCaseIndices[nextRow])

    def onNextCaseButton(self) -> None:
        if not self._datasetCases:
            self.ui.statusLabel.text = _("Scan a dataset first")
            return
        if not self._filteredDatasetCaseIndices:
            self.ui.statusLabel.text = _("No cases match the current filter")
            return
        currentRow = self.currentFilteredDatasetRow()
        nextRow = 0 if currentRow < 0 or currentRow >= len(self._filteredDatasetCaseIndices) - 1 else currentRow + 1
        self.loadDatasetCase(self._filteredDatasetCaseIndices[nextRow])

    def onNextNotDoneCaseButton(self) -> None:
        if not self._datasetCases:
            self.ui.statusLabel.text = _("Scan a dataset first")
            return
        if not self._filteredDatasetCaseIndices:
            self.ui.statusLabel.text = _("No cases match the current filter")
            return
        currentRow = self.currentFilteredDatasetRow()
        startRow = currentRow if currentRow >= 0 else -1
        for offset in range(1, len(self._filteredDatasetCaseIndices) + 1):
            candidateRow = (startRow + offset) % len(self._filteredDatasetCaseIndices)
            candidateIndex = self._filteredDatasetCaseIndices[candidateRow]
            if not self._datasetCases[candidateIndex].get("done", False):
                self.loadDatasetCase(candidateIndex)
                return
        self.ui.statusLabel.text = _("All visible cases are done")

    def onToggleDoneButton(self) -> None:
        if not self.currentDatasetCase():
            self.ui.statusLabel.text = _("Load a dataset case first")
            return
        case = self.currentDatasetCase()
        done = not case.get("done", False)
        self.setCurrentDatasetCaseDone(done)
        self.ui.statusLabel.text = _("Current case marked done") if done else _("Current case marked not done")

    def currentDatasetCase(self) -> dict[str, Any] | None:
        if 0 <= self._currentDatasetCaseIndex < len(self._datasetCases):
            return self._datasetCases[self._currentDatasetCaseIndex]
        return None

    def loadDatasetCase(self, caseIndex: int) -> None:
        if caseIndex < 0 or caseIndex >= len(self._datasetCases):
            return
        if caseIndex == self._currentDatasetCaseIndex:
            return
        if not self.confirmCaseSwitch():
            return

        case = self._datasetCases[caseIndex]
        volumePath = case.get("volume_path", "")
        detectionPath = case.get("detection_path", "")
        if not os.path.isfile(volumePath):
            self.ui.statusLabel.text = _("Case volume not found")
            return
        if not os.path.isfile(detectionPath):
            self.ui.statusLabel.text = _("Case detection JSON not found")
            return

        with slicer.util.tryWithErrorDisplay(_("Failed to load dataset case."), waitCursor=True):
            with self.progressDialog(_("Loading case...")) as progress:
                self._loadingDatasetCase = True
                try:
                    progress.update(labelText=_("Clearing previous case..."))
                    self.clearLoadedDatasetCaseNodes()
                    progress.update(labelText=_("Loading volume...\n{0}").format(volumePath))
                    volumeNode = self.logic.loadVolume(volumePath)
                    self._loadedDatasetVolumeNodeId = volumeNode.GetID()
                    self.setInputVolumeNode(volumeNode)
                    self.setDetectionPath(detectionPath)
                    self._loadedAnnotationPath = None
                finally:
                    self._loadingDatasetCase = False

                self._currentDatasetCaseIndex = caseIndex
                self.refreshDatasetCaseTable()
                progress.update(labelText=_("Refreshing detection boxes..."))
                self.autoRefreshDetectionBoxes(progress=progress)
                self._annotationsDirty = False
                self.updateCurrentCaseSummary()

    def confirmCaseSwitch(self) -> bool:
        if not self._annotationsDirty:
            return True
        answer = qt.QMessageBox.question(
            self.parent,
            _("Unsaved annotations"),
            _("Save annotations before switching cases?"),
            qt.QMessageBox.Save | qt.QMessageBox.Discard | qt.QMessageBox.Cancel,
            qt.QMessageBox.Save,
        )
        if answer == qt.QMessageBox.Cancel:
            return False
        if answer == qt.QMessageBox.Save:
            return self.saveCurrentAnnotations() is not None
        return True

    def clearLoadedDatasetCaseNodes(self) -> None:
        self.logic.clearDetectionBoxes()
        self.unobserveAnnotationNodes()
        self.logic.clearAnnotations()
        self.refreshAnnotationOptions()
        self.refreshLocateIndexOptions([])
        self.clearLocateInfoTable()
        self.clearAnnotationInfoTable()
        self._loadedAnnotationPath = None
        self.setDetectionPath("")
        self.setInputVolumeNode(None)

        if self._loadedDatasetVolumeNodeId:
            volumeNode = slicer.mrmlScene.GetNodeByID(self._loadedDatasetVolumeNodeId)
            if volumeNode is not None:
                slicer.mrmlScene.RemoveNode(volumeNode)
            self._loadedDatasetVolumeNodeId = None

    def setCurrentDatasetCaseDone(self, done: bool) -> None:
        case = self.currentDatasetCase()
        if case is None:
            return
        case["done"] = bool(done)
        case["annotation_count"] = len(self.logic.annotationNodes())
        self.logic.updateDatasetCaseDone(
            self.datasetIndexRootForCase(case),
            case["case_id"],
            case["done"],
            case["annotation_count"],
            case=case,
        )
        self.refreshDatasetCaseTable()
        self.updateCurrentCaseSummary()

    def updateCurrentDatasetCaseAfterSave(self, count: int) -> None:
        case = self.currentDatasetCase()
        if case is None:
            return
        case["annotation_count"] = count
        case["last_saved"] = datetime.now().isoformat(timespec="seconds")
        self.logic.updateDatasetCaseDone(
            self.datasetIndexRootForCase(case),
            case["case_id"],
            case.get("done", False),
            count,
            case["last_saved"],
            case=case,
        )
        self.refreshDatasetCaseTable()
        self.updateCurrentCaseSummary()

    def datasetIndexRootForCase(self, case: dict[str, Any]) -> str:
        indexRoot = case.get("index_root")
        if indexRoot:
            return indexRoot
        detectionPath = case.get("detection_path", "")
        if detectionPath:
            return self.logic.datasetIndexRootForDetectionPath(detectionPath)
        return self.ui.datasetRootLineEdit.text.strip()

    def updateCurrentCaseSummary(self) -> None:
        case = self.currentDatasetCase()
        if case is None:
            self.ui.currentCaseLabel.text = self.currentCaseStatusHtml(
                _("Empty"),
                self.statusIndicatorHtml("#8a8f98", _("Empty")),
                self.statusIndicatorHtml("#c62828" if self._annotationsDirty else "#8a8f98", _("Unsaved") if self._annotationsDirty else _("Empty")),
                0,
            )
            self.ui.currentCaseLabel.toolTip = _(
                "No case is loaded. Annotation status turns red if unsaved annotation edits exist."
            )
            self.ui.toggleDoneButton.text = _("Mark Done")
            self.ui.toggleDoneButton.toolTip = _("Load a case before marking it done.")
            return
        caseDone = bool(case.get("done", False))
        annotationCount = len(self.logic.annotationNodes())
        self.ui.currentCaseLabel.text = self.currentCaseStatusHtml(
            case.get("display_id") or case.get("case_id", "-"),
            self.statusIndicatorHtml("#2e7d32" if caseDone else "#c62828", _("Done") if caseDone else _("UnDone")),
            self.statusIndicatorHtml(
                "#c62828" if self._annotationsDirty else "#2e7d32",
                _("Unsaved") if self._annotationsDirty else _("Saved"),
            ),
            annotationCount,
        )
        self.ui.currentCaseLabel.toolTip = _(
            "Left side shows the current case and annotation box count. "
            "Right side shows review and annotation save states."
        )
        self.ui.toggleDoneButton.text = _("Mark Not Done") if caseDone else _("Mark Done")
        self.ui.toggleDoneButton.toolTip = (
            _("Mark the current case as not done in the dataset index. This does not save annotation edits.")
            if caseDone
            else _("Mark the current case as done in the dataset index. This does not save annotation edits.")
        )

    def currentCaseStatusHtml(
        self,
        caseText: str,
        reviewHtml: str,
        annotationHtml: str,
        annotationCount: int,
    ) -> str:
        return (
            '<table width="100%" cellspacing="0" cellpadding="0">'
            "<tr>"
            '<td align="left">{caseText}&nbsp;&nbsp;&nbsp;Box {annotationCount}</td>'
            '<td align="right">{reviewHtml}&nbsp;&nbsp;&nbsp;{annotationHtml}</td>'
            "</tr>"
            "</table>"
        ).format(
            caseText=html.escape(str(caseText)),
            reviewHtml=reviewHtml,
            annotationHtml=annotationHtml,
            annotationCount=annotationCount,
        )

    def statusIndicatorHtml(self, color: str, text: str) -> str:
        return '<span style="color:{0}; font-size:14px;">&#9679;</span>&nbsp;{1}'.format(
            color,
            html.escape(str(text)),
        )
