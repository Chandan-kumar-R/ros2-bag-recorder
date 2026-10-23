cmake_minimum_required(VERSION 3.8)
project(rosbag_recorder_msgs)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/RecordingConfig.msg"
  "msg/RecorderStatus.msg"
  "msg/RecordingSummary.msg"
  "msg/TopicStat.msg"
  "msg/TopicStats.msg"
  "srv/StartRecording.srv"
  "srv/StopRecording.srv"
  "srv/PreviewSelection.srv"
  "srv/ValidateOutput.srv"
  "srv/SetRateMonitor.srv"
  "srv/GetDiagnostics.srv"
  "srv/GetRegistry.srv"
  "srv/SetRegistry.srv"
  DEPENDENCIES builtin_interfaces
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
