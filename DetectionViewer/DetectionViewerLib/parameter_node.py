from slicer import vtkMRMLScalarVolumeNode
from slicer.parameterNodeWrapper import parameterNodeWrapper


@parameterNodeWrapper
class DetectionViewerParameterNode:
    """Parameters stored with the Slicer scene."""

    inputVolume: vtkMRMLScalarVolumeNode
