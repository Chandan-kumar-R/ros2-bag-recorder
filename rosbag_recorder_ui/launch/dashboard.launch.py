"""
Bring up the whole recording stack: bridge plus dashboard.

Use this on a workstation. On a robot : run bridge.launch.py there and this
launch file with use_bridge:=false on the operator's machine.
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, Shutdown
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    arguments = [
        DeclareLaunchArgument(
            'use_bridge', default_value='true',
            description='Also start the recorder bridge. Set false when the bridge '
                        'already runs on the robot.'),
        DeclareLaunchArgument(
            'bridge_namespace', default_value='/rosbag_recorder_bridge',
            description='Namespace the dashboard looks for the bridge under.'),
        DeclareLaunchArgument(
            'default_bag_path', default_value='~/rosbags',
            description='Directory the dashboard starts out pointing at.'),
        DeclareLaunchArgument(
            'registry_file', default_value='',
            description='Topic registry YAML. Empty uses the packaged one.'),
        DeclareLaunchArgument(
            'params_file', default_value='',
            description='Recorder parameter file to preload into the dashboard.'),
    ]

    bridge = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(PathJoinSubstitution([
            FindPackageShare('rosbag_recorder_bridge'), 'launch', 'bridge.launch.py'])),
        condition=IfCondition(LaunchConfiguration('use_bridge')),
        launch_arguments={
            'registry_file': LaunchConfiguration('registry_file'),
            'default_bag_path': LaunchConfiguration('default_bag_path'),
        }.items(),
    )

    dashboard = Node(
        package='rosbag_recorder_ui',
        executable='rosbag_recorder_ui',
        name='rosbag_recorder_dashboard',
        arguments=[['--bridge-namespace=', LaunchConfiguration('bridge_namespace')],
                   ['--config=', LaunchConfiguration('params_file')],
                   ['--managed-bridge=', LaunchConfiguration('use_bridge')]],
        emulate_tty=True,
        output='screen',
        # Closing the window ends the launch.
        on_exit=Shutdown(reason='the dashboard window was closed'),
    )

    return LaunchDescription(arguments + [bridge, dashboard])
