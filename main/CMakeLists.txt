#-----------------------------------------------------------------------------
set(MODULE_NAME DetectionViewer)

#-----------------------------------------------------------------------------
set(MODULE_PYTHON_SCRIPTS
  ${MODULE_NAME}.py
  DetectionViewerLib/__init__.py
  DetectionViewerLib/logic.py
  DetectionViewerLib/logic_annotation.py
  DetectionViewerLib/logic_dataset.py
  DetectionViewerLib/logic_detection.py
  DetectionViewerLib/logic_view.py
  DetectionViewerLib/parameter_node.py
  DetectionViewerLib/widget.py
  DetectionViewerLib/widget_annotation.py
  DetectionViewerLib/widget_dataset.py
  DetectionViewerLib/widget_view.py
  )

set(MODULE_PYTHON_RESOURCES
  Resources/Icons/${MODULE_NAME}.png
  Resources/UI/${MODULE_NAME}.ui
  Resources/UI/Annotations.ui
  Resources/UI/Dataset.ui
  Resources/UI/Settings.ui
  Resources/UI/View.ui
  )

#-----------------------------------------------------------------------------
slicerMacroBuildScriptedModule(
  NAME ${MODULE_NAME}
  SCRIPTS ${MODULE_PYTHON_SCRIPTS}
  RESOURCES ${MODULE_PYTHON_RESOURCES}
  )
