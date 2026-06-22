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

from .logic_annotation import AnnotationLogicMixin
from .logic_dataset import DatasetLogicMixin
from .logic_detection import DetectionBoxLogicMixin
from .logic_view import ViewLogicMixin
from .parameter_node import DetectionViewerParameterNode


class DetectionViewerLogic(
    DatasetLogicMixin,
    DetectionBoxLogicMixin,
    AnnotationLogicMixin,
    ViewLogicMixin,
    ScriptedLoadableModuleLogic,
):
    """Logic for dataset review, detection boxes, annotations, and view navigation."""

    GENERATED_BOX_ATTRIBUTE = "DetectionViewer.GeneratedBox"
    ANNOTATION_BOX_ATTRIBUTE = "DetectionViewer.AnnotationBox"
    ANNOTATION_LABEL_ATTRIBUTE = "DetectionViewer.AnnotationLabelNode"
    ANNOTATION_LABEL_FOR_ATTRIBUTE = "DetectionViewer.AnnotationLabelFor"
    DATASET_INDEX_FILE_NAME = ".detection_viewer_index.json"
    DATASET_INDEX_SCHEMA_VERSION = 2
    VOLUME_EXTENSIONS = (".nii.gz", ".nii", ".nrrd", ".mha", ".mhd")

    def __init__(self) -> None:
        ScriptedLoadableModuleLogic.__init__(self)

    def getParameterNode(self):
        return DetectionViewerParameterNode(super().getParameterNode())

    def defaultTestCasePath(self) -> str:
        modulePath = os.path.abspath(os.path.dirname(__file__))
        candidatePaths = [
            os.path.join(modulePath, "..", "test", "00016-0800237946"),
            os.path.join(modulePath, "..", "..", "test", "00016-0800237946"),
        ]
        for candidatePath in candidatePaths:
            normalizedPath = os.path.abspath(candidatePath)
            if os.path.isdir(normalizedPath):
                return normalizedPath
        return os.path.abspath(candidatePaths[-1])

    def findTestData(self) -> tuple[str, str]:
        testCasePath = self.defaultTestCasePath()
        if not os.path.isdir(testCasePath):
            raise FileNotFoundError(f"Test data directory not found: {testCasePath}")

        detectionPath = os.path.join(testCasePath, "detection.json")
        if not os.path.isfile(detectionPath):
            raise FileNotFoundError(f"Detection JSON not found: {detectionPath}")

        volumeCandidates = [
            os.path.join(testCasePath, fileName)
            for fileName in os.listdir(testCasePath)
            if fileName.lower().endswith((".nii", ".nii.gz", ".nrrd", ".mha", ".mhd"))
        ]
        if not volumeCandidates:
            raise FileNotFoundError(f"No supported volume file found in: {testCasePath}")

        return volumeCandidates[0], detectionPath

    def loadVolume(self, volumePath: str) -> vtkMRMLScalarVolumeNode:
        if not os.path.isfile(volumePath):
            raise FileNotFoundError(f"Volume file not found: {volumePath}")

        volumeNode = slicer.util.loadVolume(volumePath)
        if isinstance(volumeNode, bool):
            loaded, volumeNode = slicer.util.loadVolume(volumePath, returnNode=True)
            if not loaded:
                volumeNode = None
        if volumeNode is None:
            raise RuntimeError(f"Failed to load volume: {volumePath}")
        return volumeNode

    def findDetectionJsonNextToVolume(self, volumePath: str) -> str | None:
        volumeDirectory = os.path.dirname(os.path.abspath(volumePath))
        preferredPath = os.path.join(volumeDirectory, "detection.json")
        if os.path.isfile(preferredPath):
            return preferredPath

        jsonPaths = [
            os.path.join(volumeDirectory, fileName)
            for fileName in os.listdir(volumeDirectory)
            if fileName.lower().endswith(".json")
        ]
        if len(jsonPaths) == 1:
            return jsonPaths[0]
        return None

    def findDetectionJsonForVolumeNode(self, volumeNode: vtkMRMLScalarVolumeNode) -> str | None:
        storageNode = volumeNode.GetStorageNode()
        if storageNode is None:
            return None
        volumePath = storageNode.GetFileName()
        if not volumePath:
            return None
        return self.findDetectionJsonNextToVolume(volumePath)


