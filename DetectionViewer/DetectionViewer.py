import os
import sys

from slicer.i18n import tr as _
from slicer.i18n import translate
from slicer.ScriptedLoadableModule import ScriptedLoadableModule, ScriptedLoadableModuleTest

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
if MODULE_DIR not in sys.path:
    sys.path.insert(0, MODULE_DIR)

from DetectionViewerLib.logic import DetectionViewerLogic as DetectionViewerLogicBase
from DetectionViewerLib.parameter_node import DetectionViewerParameterNode
from DetectionViewerLib.widget import DetectionViewerWidget as DetectionViewerWidgetBase


class DetectionViewer(ScriptedLoadableModule):
    """3D Slicer scripted module for detection box visualization."""

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = _("Detection Viewer")
        self.parent.categories = [translate("qSlicerAbstractCoreModule", "Annotation")]
        self.parent.dependencies = []
        self.parent.contributors = ["DetectionViewer contributors"]
        self.parent.helpText = _("""Visualize detection boxes from JSON files on a loaded CT volume.""")
        self.parent.acknowledgementText = _("""This module was created as a 3D Slicer extension.""")


class DetectionViewerWidget(DetectionViewerWidgetBase):
    pass


class DetectionViewerLogic(DetectionViewerLogicBase):
    pass


class DetectionViewerTest(ScriptedLoadableModuleTest):
    pass
