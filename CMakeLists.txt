cmake_minimum_required(VERSION 3.20.6...3.22.6 FATAL_ERROR)

project(DetectionViewer)

#-----------------------------------------------------------------------------
# Extension meta-information
set(EXTENSION_HOMEPAGE "https://github.com/Stya-hr/SlicerDetectionViewer#SlicerDetectionViewer")
set(EXTENSION_CONTRIBUTORS "Huang Rui, Codex")
set(EXTENSION_DESCRIPTION "A Slicer extension to view and edit detection dataset")
set(EXTENSION_ICONURL "https://raw.githubusercontent.com/Stya-hr/SlicerDetectionViewer/refs/heads/main/DetectionViewer.png")
set(EXTENSION_SCREENSHOTURLS "https://github.com/Stya-hr/SlicerDetectionViewer/blob/main/docs/figs/screenshot.png")
set(EXTENSION_DEPENDS "NA") # Specified as a list or "NA" if no dependencies
set(EXTENSION_CATEGORY "Annotation")

#-----------------------------------------------------------------------------
# Extension dependencies
find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

#-----------------------------------------------------------------------------
# Extension modules
add_subdirectory(DetectionViewer)
## NEXT_MODULE

#-----------------------------------------------------------------------------
include(${Slicer_EXTENSION_GENERATE_CONFIG})
include(${Slicer_EXTENSION_CPACK})
