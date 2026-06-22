import logging
import os
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import qt
import slicer
import vtk
from slicer.i18n import tr as _
from slicer.ScriptedLoadableModule import ScriptedLoadableModuleWidget
from slicer.util import VTKObservationMixin

from .logic import DetectionViewerLogic
from .parameter_node import DetectionViewerParameterNode
from .widget_annotation import AnnotationWidgetMixin
from .widget_dataset import DatasetWidgetMixin
from .widget_view import ViewWidgetMixin


class DetectionViewerProgressDialog:
    """Small wrapper around QProgressDialog that keeps Slicer events flowing."""

    def __init__(self, parent, title: str, labelText: str, maximum: int = 0) -> None:
        self.dialog = qt.QProgressDialog(labelText, "", 0, maximum, parent)
        self.dialog.setWindowTitle(title)
        self.dialog.setWindowModality(qt.Qt.ApplicationModal)
        self.dialog.setCancelButton(None)
        self.dialog.setMinimumDuration(0)
        self.dialog.setAutoClose(False)
        self.dialog.setAutoReset(False)
        self.dialog.setValue(0)

    def __enter__(self):
        self.dialog.show()
        self.processEvents()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.dialog.close()
        self.dialog.deleteLater()
        self.processEvents()

    def update(self, labelText: str | None = None, value: int | None = None, maximum: int | None = None) -> None:
        if maximum is not None:
            self.dialog.setRange(0, maximum)
        if labelText is not None:
            self.dialog.setLabelText(labelText)
        if value is not None:
            self.dialog.setValue(value)
        self.processEvents()

    def processEvents(self) -> None:
        if slicer.app:
            slicer.app.processEvents()


class DetectionViewerWidget(DatasetWidgetMixin, ViewWidgetMixin, AnnotationWidgetMixin, ScriptedLoadableModuleWidget, VTKObservationMixin):
    """Widget for dataset review, detection viewing, and annotation editing."""
    def __init__(self, parent=None) -> None:
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.logic = None
        self._parameterNode = None
        self._parameterNodeGuiTag = None
        self._parameterNodeObserved = False
        self._updatingLocateIndexOptions = False
        self._updatingAnnotationOptions = False
        self._updatingAnnotationEditor = False
        self._observedAnnotationNodeIds = set()
        self._autoRefreshingDetectionBoxes = False
        self._loadedAnnotationPath = None
        self._inputVolumeNode = None
        self._detectionPath = ""
        self._datasetCases = []
        self._filteredDatasetCaseIndices = []
        self._currentDatasetCaseIndex = -1
        self._updatingDatasetCaseTable = False
        self._loadingDatasetCase = False
        self._loadedDatasetVolumeNodeId = None
        self._annotationsDirty = False
        self._sceneClosing = False
        self._sectionUiWidgets = []

    def setup(self) -> None:
        ScriptedLoadableModuleWidget.setup(self)

        uiWidget = slicer.util.loadUI(self.resourcePath("UI/DetectionViewer.ui"))
        self.layout.addWidget(uiWidget)
        self.ui = SimpleNamespace()
        self.registerSectionWidgets(uiWidget)
        self._sectionsLayout = uiWidget.findChild(qt.QVBoxLayout, "sectionsLayout")
        if self._sectionsLayout is None:
            raise RuntimeError("Main UI is missing sectionsLayout")
        uiWidget.setMRMLScene(slicer.mrmlScene)
        self.loadSectionUis()

        self.logic = DetectionViewerLogic()
        self.logic.clearAnnotationLabelNodes()

        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

        self.validateRequiredUi()
        self.ui.browseDatasetButton.connect("clicked(bool)", self.onBrowseDatasetButton)
        self.ui.scanDatasetButton.connect("clicked(bool)", self.onScanDatasetButton)
        self.ui.datasetRootLineEdit.connect("editingFinished()", self.onDatasetRootEditingFinished)
        self.setupDatasetFilters()
        self.ui.caseFilterLineEdit.connect("textChanged(QString)", self.onDatasetFilterChanged)
        self.ui.doneFilterComboBox.connect("currentIndexChanged(int)", self.onDatasetFilterChanged)
        self.ui.datasetCaseTable.connect("cellClicked(int,int)", self.onDatasetCaseClicked)
        self.ui.previousCaseButton.connect("clicked(bool)", self.onPreviousCaseButton)
        self.ui.nextCaseButton.connect("clicked(bool)", self.onNextCaseButton)
        self.ui.nextNotDoneCaseButton.connect("clicked(bool)", self.onNextNotDoneCaseButton)
        self.ui.toggleDoneButton.connect("clicked(bool)", self.onToggleDoneButton)
        self.ui.minScoreSpinBox.connect("valueChanged(double)", self.autoRefreshDetectionBoxes)
        self.ui.maxDetectionsSpinBox.connect("valueChanged(int)", self.autoRefreshDetectionBoxes)
        self.ui.detectLpsRadioButton.connect("toggled(bool)", self.autoRefreshDetectionBoxes)
        self.ui.detectRasRadioButton.connect("toggled(bool)", self.autoRefreshDetectionBoxes)
        self.ui.refreshDisplayButton.connect("clicked(bool)", self.onRefreshDisplayButton)
        self.ui.locateIndexComboBox.connect("currentIndexChanged(int)", self.onLocateIndexChanged)
        self.ui.previousBoxButton.connect("clicked(bool)", self.onPreviousBoxButton)
        self.ui.nextBoxButton.connect("clicked(bool)", self.onNextBoxButton)
        self.ui.showDetectionBoxesCheckBox.connect("toggled(bool)", self.onShowDetectionBoxesChanged)
        self.ui.locateAutoFovCheckBox.connect("toggled(bool)", self.onLocateFovControlChanged)
        self.ui.locateFovZoomSpinBox.connect("valueChanged(double)", self.onLocateFovControlChanged)
        self.ui.copyViewedDetectionButton.connect("clicked(bool)", self.onAddSelectedDetectionButton)
        self.ui.annotationSelectorComboBox.connect("currentIndexChanged(int)", self.onAnnotationSelectionChanged)
        self.ui.addAnnotationButton.connect("clicked(bool)", self.onAddEmptyAnnotationButton)
        self.ui.updateAnnotationButton.connect("clicked(bool)", self.onUpdateAnnotationButton)
        self.ui.deleteAnnotationButton.connect("clicked(bool)", self.onDeleteAnnotationButton)
        self.ui.saveAnnotationsButton.connect("clicked(bool)", self.onSaveAnnotationsButton)
        self.setupCurrentCaseStatusLabel()
        self.setupDatasetCaseTable()
        self.setupLocateInfoTable()
        self.setupAnnotationInfoTable()
        self.refreshAnnotationOptions()
        self.updateCurrentCaseSummary()

        self.initializeParameterNode()

    def validateRequiredUi(self) -> None:
        requiredNames = [
            "statusLabel",
            "browseDatasetButton",
            "scanDatasetButton",
            "datasetRootLineEdit",
            "caseFilterLineEdit",
            "doneFilterComboBox",
            "datasetCaseTable",
            "previousCaseButton",
            "nextCaseButton",
            "nextNotDoneCaseButton",
            "toggleDoneButton",
            "currentCaseLabel",
            "minScoreSpinBox",
            "maxDetectionsSpinBox",
            "detectLpsRadioButton",
            "detectRasRadioButton",
            "refreshDisplayButton",
            "locateIndexComboBox",
            "previousBoxButton",
            "nextBoxButton",
            "showDetectionBoxesCheckBox",
            "locateAutoFovCheckBox",
            "locateFovZoomSpinBox",
            "copyViewedDetectionButton",
            "annotationSelectorComboBox",
            "addAnnotationButton",
            "updateAnnotationButton",
            "deleteAnnotationButton",
            "saveAnnotationsButton",
            "annotationLabelLineEdit",
            "locateInfoTable",
            "annotationInfoTable",
        ]
        missingNames = [name for name in requiredNames if not hasattr(self.ui, name)]
        if missingNames:
            raise RuntimeError("Missing UI widgets: " + ", ".join(missingNames))

    def loadSectionUis(self) -> None:
        self._sectionsLayout.setSpacing(8)
        datasetWidget = self.loadSectionUi("Dataset")
        datasetWidget.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Maximum)
        self._sectionsLayout.addWidget(datasetWidget, 0)

        separator = qt.QFrame()
        separator.objectName = "datasetWorkflowSeparator"
        separator.setFrameShape(qt.QFrame.HLine)
        separator.setFrameShadow(qt.QFrame.Plain)
        separator.setFixedHeight(1)
        separator.setStyleSheet("QFrame#datasetWorkflowSeparator { background: #8a8f98; border: 0; }")
        self._sectionsLayout.addWidget(separator, 0)

        tabWidget = qt.QTabWidget()
        tabWidget.objectName = "workflowTabWidget"
        tabWidget.setDocumentMode(True)
        tabWidget.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Expanding)
        setattr(self.ui, "workflowTabWidget", tabWidget)
        self._sectionsLayout.addWidget(tabWidget, 1)

        for sectionName, title in (
            ("View", _("View")),
            ("Annotations", _("Annotation")),
            ("Settings", _("Settings")),
        ):
            sectionWidget = self.loadSectionUi(sectionName)
            if sectionName == "Settings":
                sectionWidget.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Maximum)
            tabWidget.addTab(sectionWidget, title)

    def loadSectionUi(self, sectionName: str):
        sectionWidget = slicer.util.loadUI(self.resourcePath(f"UI/{sectionName}.ui"))
        if hasattr(sectionWidget, "setMRMLScene"):
            sectionWidget.setMRMLScene(slicer.mrmlScene)
        self.registerSectionWidgets(sectionWidget)
        self._sectionUiWidgets.append(sectionWidget)
        return sectionWidget

    def registerSectionWidgets(self, sectionWidget) -> None:
        widgets = [sectionWidget]
        widgets.extend(sectionWidget.findChildren(qt.QWidget))
        for child in widgets:
            objectName = child.objectName
            if callable(objectName):
                objectName = objectName()
            if objectName:
                setattr(self.ui, str(objectName), child)

    def progressDialog(self, labelText: str, maximum: int = 0):
        parent = slicer.util.mainWindow() or self.parent
        return DetectionViewerProgressDialog(parent, _("Detection Viewer"), labelText, maximum)

    def cleanup(self) -> None:
        self.removeObservers()
        self._observedAnnotationNodeIds.clear()
        self._parameterNodeObserved = False

    def enter(self) -> None:
        self.initializeParameterNode()

    def exit(self) -> None:
        if self._parameterNode:
            if self._parameterNodeGuiTag is not None:
                self._parameterNode.disconnectGui(self._parameterNodeGuiTag)
            self._parameterNodeGuiTag = None
            self.removeParameterNodeObserver()

    def onSceneStartClose(self, caller, event) -> None:
        self._sceneClosing = True
        self._observedAnnotationNodeIds.clear()
        self._loadedDatasetVolumeNodeId = None
        self._annotationsDirty = False
        self.setParameterNode(None)

    def onSceneEndClose(self, caller, event) -> None:
        self._sceneClosing = False
        if self.parent.isEntered:
            self.initializeParameterNode()

    def initializeParameterNode(self) -> None:
        self.setParameterNode(self.logic.getParameterNode())

    def setParameterNode(self, inputParameterNode: DetectionViewerParameterNode | None) -> None:
        if self._parameterNode:
            if self._parameterNodeGuiTag is not None:
                self._parameterNode.disconnectGui(self._parameterNodeGuiTag)
            self.removeParameterNodeObserver()

        self._parameterNode = inputParameterNode

        if self._parameterNode:
            self._parameterNodeGuiTag = self._parameterNode.connectGui(self.ui)
            self.addObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self._checkCanApply)
            self._parameterNodeObserved = True
            self._checkCanApply()

    def removeParameterNodeObserver(self) -> None:
        if self._parameterNode and self._parameterNodeObserved:
            if self.hasObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self._checkCanApply):
                self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self._checkCanApply)
            self._parameterNodeObserved = False

    def _checkCanApply(self, caller=None, event=None) -> None:
        self.autoRefreshDetectionBoxes()

    def inputVolumeNode(self):
        return self._inputVolumeNode

    def setInputVolumeNode(self, volumeNode) -> None:
        self._inputVolumeNode = volumeNode
        if self._parameterNode and volumeNode is not None:
            self._parameterNode.inputVolume = volumeNode

    def currentDetectionPath(self) -> str:
        return self._detectionPath

    def setDetectionPath(self, detectionPath: str) -> None:
        self._detectionPath = detectionPath or ""
