import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    """Launch the bag recorder, overridable with params_file:=<path>."""
    pkg_name = 'ros2_bag_recorder'
    param_file_name = 'rosbag_param.yaml'
    default_params = os.path.join(
        get_package_share_directory(pkg_name), 'config', param_file_name)

    params_file_arg = DeclareLaunchArgument(
        'params_file',
        default_value=default_params,
        description='Full path to the recorder parameter YAML.'
    )

    recorder_node = Node(
        package=pkg_name,
        executable='topic_recorder',
        name='ros2_bag_recorder_node',
        parameters=[LaunchConfiguration('params_file')],
        emulate_tty=True,
        output='screen',
    )

    return LaunchDescription([
        params_file_arg,
        recorder_node,
    ])
