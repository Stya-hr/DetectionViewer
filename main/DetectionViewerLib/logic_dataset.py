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

class DatasetLogicMixin:
    def scanDataset(
        self,
        rootPath: str,
        progressCallback: Callable[[int, int, str], None] | None = None,
    ) -> list[dict[str, Any]]:
        rootPath = os.path.abspath(os.path.expanduser(rootPath))
        cases = []
        indexDataCache = {}
        scannedCasesByIndexRoot = {}
        visitedDirectoryCount = 0

        for directoryPath, directoryNames, fileNames in os.walk(rootPath):
            visitedDirectoryCount += 1
            directoryNames[:] = [
                directoryName
                for directoryName in directoryNames
                if not directoryName.startswith(".")
            ]
            if progressCallback and visitedDirectoryCount % 25 == 0:
                progressCallback(visitedDirectoryCount, len(cases), directoryPath)
            if "detection.json" not in fileNames:
                continue

            detectionPath = os.path.join(directoryPath, "detection.json")
            indexRootPath = self.datasetIndexRootForDetectionPath(detectionPath)
            if indexRootPath not in indexDataCache:
                indexDataCache[indexRootPath] = self.readDatasetIndex(indexRootPath)
            storedCases = indexDataCache[indexRootPath].get("cases", {})
            caseId = self.caseIdForDetectionPath(indexRootPath, detectionPath)
            displayCaseId = self.displayCaseIdForDetectionPath(rootPath, detectionPath)
            storedCase = storedCases.get(caseId, {})
            relativeDirectory = os.path.relpath(directoryPath, indexRootPath)
            rawCount = 0
            annotationCount = 0
            done = bool(storedCase.get("done", False))
            lastSaved = storedCase.get("last_saved", "")
            try:
                detectionData = self.readDetectionData(detectionPath)
                rawCount = len(self.detectionsFromData(detectionData, minScore=float("-inf")))
                annotationCount = len(self.annotationDataFromDetectionData(detectionData))
            except Exception as exc:
                logging.warning("Failed to read detection summary for %s: %s", detectionPath, exc)

            volumePath = self.findVolumeNextToDetection(detectionPath)
            volumeFile = os.path.basename(volumePath) if volumePath else ""

            case = {
                "case_id": caseId,
                "display_id": displayCaseId,
                "index_root": indexRootPath,
                "done": done,
                "relative_dir": relativeDirectory,
                "detection_file": os.path.basename(detectionPath),
                "volume_file": volumeFile,
                "volume_path": volumePath or "",
                "detection_path": detectionPath,
                "raw_count": rawCount,
                "annotation_count": annotationCount,
                "last_saved": lastSaved,
            }
            cases.append(case)
            scannedCasesByIndexRoot.setdefault(indexRootPath, {})[caseId] = case
            if progressCallback:
                progressCallback(visitedDirectoryCount, len(cases), directoryPath)

        cases.sort(key=lambda case: case.get("display_id", case["case_id"]))
        if progressCallback:
            progressCallback(visitedDirectoryCount, len(cases), rootPath)
        self.writeScannedDatasetIndexes(rootPath, scannedCasesByIndexRoot)
        return cases

    def loadDatasetFromIndex(self, rootPath: str) -> list[dict[str, Any]]:
        rootPath = os.path.abspath(os.path.expanduser(rootPath))
        cases = []
        for indexRootPath in self.findDatasetIndexRoots(rootPath):
            cases.extend(self.loadDatasetCasesFromIndexRoot(indexRootPath, rootPath))
        cases.sort(key=lambda case: case.get("display_id", case["case_id"]))
        return cases

    def loadDatasetCasesFromIndexRoot(self, indexRootPath: str, selectedRootPath: str) -> list[dict[str, Any]]:
        indexRootPath = os.path.abspath(os.path.expanduser(indexRootPath))
        selectedRootPath = os.path.abspath(os.path.expanduser(selectedRootPath))
        indexData = self.readDatasetIndex(indexRootPath)
        cases = []
        for caseId, caseData in indexData.get("cases", {}).items():
            relativeDirectory = caseData.get("relative_dir", "")
            detectionFile = caseData.get("detection_file", "")
            volumeFile = caseData.get("volume_file", "")
            if not relativeDirectory or not detectionFile:
                continue
            relativeDirectory = os.path.normpath(str(relativeDirectory))
            if os.path.isabs(relativeDirectory) or os.path.dirname(relativeDirectory) not in ("", "."):
                continue
            caseDirectory = os.path.normpath(os.path.join(indexRootPath, relativeDirectory))
            if not self.pathContains(selectedRootPath, caseDirectory):
                continue
            detectionPath = os.path.join(caseDirectory, detectionFile)
            volumePath = os.path.join(caseDirectory, volumeFile) if volumeFile else ""
            cases.append(
                {
                    "case_id": str(caseId),
                    "display_id": self.displayCaseIdForDetectionPath(selectedRootPath, detectionPath),
                    "index_root": indexRootPath,
                    "done": bool(caseData.get("done", False)),
                    "relative_dir": relativeDirectory,
                    "detection_file": str(detectionFile),
                    "volume_file": str(volumeFile),
                    "volume_path": volumePath,
                    "detection_path": detectionPath,
                    "raw_count": int(caseData.get("raw_count", 0) or 0),
                    "annotation_count": int(caseData.get("annotation_count", 0) or 0),
                    "last_saved": str(caseData.get("last_saved", "") or ""),
                }
            )
        cases.sort(key=lambda case: case.get("display_id", case["case_id"]))
        return cases

    def findDatasetIndexRoots(self, rootPath: str) -> list[str]:
        rootPath = os.path.abspath(os.path.expanduser(rootPath))
        indexRoots = []
        if os.path.isfile(self.datasetIndexPath(rootPath)):
            indexRoots.append(rootPath)

        for directoryPath, directoryNames, fileNames in os.walk(rootPath):
            directoryNames[:] = [
                directoryName
                for directoryName in directoryNames
                if not directoryName.startswith(".")
            ]
            if self.DATASET_INDEX_FILE_NAME in fileNames:
                indexRoots.append(os.path.abspath(directoryPath))

        uniqueIndexRoots = []
        seen = set()
        for indexRoot in indexRoots:
            normalizedPath = os.path.normcase(os.path.abspath(indexRoot))
            if normalizedPath in seen:
                continue
            seen.add(normalizedPath)
            uniqueIndexRoots.append(os.path.abspath(indexRoot))
        return uniqueIndexRoots

    def writeScannedDatasetIndexes(self, selectedRootPath: str, scannedCasesByIndexRoot: dict[str, dict[str, dict[str, Any]]]) -> None:
        selectedRootPath = os.path.abspath(os.path.expanduser(selectedRootPath))
        for indexRootPath, scannedCases in scannedCasesByIndexRoot.items():
            replaceIndex = self.pathContains(selectedRootPath, indexRootPath)
            if replaceIndex:
                indexCases = {}
            else:
                indexCases = dict(self.readDatasetIndex(indexRootPath).get("cases", {}))

            for caseId, case in scannedCases.items():
                indexCases[caseId] = self.datasetIndexEntryFromCase(case)
            self.writeDatasetIndex(indexRootPath, {"cases": indexCases})

    def datasetIndexEntryFromCase(self, case: dict[str, Any]) -> dict[str, Any]:
        return {
            "done": case.get("done", False),
            "relative_dir": case.get("relative_dir", ""),
            "detection_file": case.get("detection_file", "detection.json"),
            "volume_file": case.get("volume_file", ""),
            "raw_count": case.get("raw_count", 0),
            "annotation_count": case.get("annotation_count", 0),
            "last_saved": case.get("last_saved", ""),
        }

    def datasetIndexPath(self, rootPath: str) -> str:
        return os.path.join(os.path.abspath(os.path.expanduser(rootPath)), self.DATASET_INDEX_FILE_NAME)

    def readDatasetIndex(self, rootPath: str) -> dict[str, Any]:
        indexPath = self.datasetIndexPath(rootPath)
        if not os.path.isfile(indexPath):
            return self.emptyDatasetIndex()
        with open(indexPath, "r", encoding="utf-8-sig") as indexFile:
            indexData = json.load(indexFile)
        if not isinstance(indexData, dict):
            return self.emptyDatasetIndex()
        if indexData.get("schema_version") != self.DATASET_INDEX_SCHEMA_VERSION:
            return self.emptyDatasetIndex()
        if not isinstance(indexData.get("cases"), dict):
            indexData["cases"] = {}
        return self.sanitizeDatasetIndex(indexData)

    def writeDatasetIndex(self, rootPath: str, indexData: dict[str, Any]) -> None:
        indexData = self.sanitizeDatasetIndex(indexData)
        indexData["updated_at"] = datetime.now().isoformat(timespec="seconds")
        with open(self.datasetIndexPath(rootPath), "w", encoding="utf-8") as indexFile:
            json.dump(indexData, indexFile, ensure_ascii=False, indent=2)

    def emptyDatasetIndex(self) -> dict[str, Any]:
        return {"schema_version": self.DATASET_INDEX_SCHEMA_VERSION, "cases": {}}

    def sanitizeDatasetIndex(self, indexData: dict[str, Any]) -> dict[str, Any]:
        sanitizedCases = {}
        for caseId, caseData in indexData.get("cases", {}).items():
            if not isinstance(caseData, dict):
                continue
            relativeDirectory = str(caseData.get("relative_dir", "") or "")
            detectionFile = str(caseData.get("detection_file", "") or "")
            volumeFile = str(caseData.get("volume_file", "") or "")
            if not relativeDirectory or not detectionFile:
                continue
            sanitizedCase = {
                "done": bool(caseData.get("done", False)),
                "relative_dir": relativeDirectory,
                "detection_file": detectionFile,
                "volume_file": volumeFile,
                "raw_count": int(caseData.get("raw_count", 0) or 0),
                "annotation_count": int(caseData.get("annotation_count", 0) or 0),
            }
            lastSaved = caseData.get("last_saved")
            if lastSaved:
                sanitizedCase["last_saved"] = str(lastSaved)
            sanitizedCases[str(caseId)] = sanitizedCase
        return {"schema_version": self.DATASET_INDEX_SCHEMA_VERSION, "cases": sanitizedCases}

    def updateDatasetCaseDone(
        self,
        rootPath: str,
        caseId: str,
        done: bool,
        annotationCount: int,
        lastSaved: str | None = None,
        case: dict[str, Any] | None = None,
    ) -> None:
        if not rootPath or not os.path.isdir(rootPath):
            return
        indexData = self.readDatasetIndex(rootPath)
        cases = indexData.setdefault("cases", {})
        caseData = cases.setdefault(caseId, {})
        if case is not None:
            caseData.update(self.datasetIndexEntryFromCase(case))
        caseData["done"] = bool(done)
        caseData["annotation_count"] = int(annotationCount)
        if lastSaved is not None:
            caseData["last_saved"] = lastSaved
        self.writeDatasetIndex(rootPath, indexData)

    def caseIdForDetectionPath(self, rootPath: str, detectionPath: str) -> str:
        relativeDirectory = os.path.relpath(os.path.dirname(os.path.abspath(detectionPath)), rootPath)
        if relativeDirectory == ".":
            return os.path.splitext(os.path.basename(detectionPath))[0]
        return relativeDirectory.replace(os.sep, "/")

    def displayCaseIdForDetectionPath(self, rootPath: str, detectionPath: str) -> str:
        caseDirectory = os.path.dirname(os.path.abspath(detectionPath))
        rootPath = os.path.abspath(os.path.expanduser(rootPath))
        if self.pathContains(rootPath, caseDirectory):
            relativeDirectory = os.path.relpath(caseDirectory, rootPath)
            if relativeDirectory == ".":
                return self.caseIdForDetectionPath(self.datasetIndexRootForDetectionPath(detectionPath), detectionPath)
            return relativeDirectory.replace(os.sep, "/")
        return self.caseIdForDetectionPath(self.datasetIndexRootForDetectionPath(detectionPath), detectionPath)

    def datasetIndexRootForDetectionPath(self, detectionPath: str) -> str:
        caseDirectory = os.path.dirname(os.path.abspath(detectionPath))
        return os.path.dirname(caseDirectory)

    def pathContains(self, parentPath: str, childPath: str) -> bool:
        parentPath = os.path.abspath(os.path.expanduser(parentPath))
        childPath = os.path.abspath(os.path.expanduser(childPath))
        try:
            return os.path.commonpath([parentPath, childPath]) == parentPath
        except ValueError:
            return False

    def findVolumeNextToDetection(self, detectionPath: str) -> str | None:
        directoryPath = os.path.dirname(os.path.abspath(detectionPath))
        if not os.path.isdir(directoryPath):
            return None
        candidates = []
        for fileName in os.listdir(directoryPath):
            filePath = os.path.join(directoryPath, fileName)
            if os.path.isfile(filePath) and self.isSupportedVolumeFile(filePath):
                candidates.append(filePath)
        candidates.sort()
        return candidates[0] if candidates else None

    def isSupportedVolumeFile(self, filePath: str) -> bool:
        lowerPath = filePath.lower()
        return any(lowerPath.endswith(extension) for extension in self.VOLUME_EXTENSIONS)
