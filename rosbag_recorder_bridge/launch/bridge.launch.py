"""Run the recorder bridge on its own, typically on the robot."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    arguments = [
        DeclareLaunchArgument(
            'registry_file', default_value='',
            description='Topic registry YAML. Empty uses the one installed by '
                        'ros2_bag_recorder.'),
        DeclareLaunchArgument(
            'default_bag_path', default_value='~/rosbags',
            description='Directory the dashboard starts out pointing at.'),
        DeclareLaunchArgument(
            'status_period_sec', default_value='0.5',
            description='How often recorder status is published.'),
        DeclareLaunchArgument(
            'topic_stats_period_sec', default_value='1.0',
            description='How often the topic table is refreshed.'),
    ]

    bridge = Node(
        package='rosbag_recorder_bridge',
        executable='recorder_bridge',
        name='rosbag_recorder_bridge',
        parameters=[{
            'registry_file': LaunchConfiguration('registry_file'),
            'default_bag_path': LaunchConfiguration('default_bag_path'),
            'status_period_sec': LaunchConfiguration('status_period_sec'),
            'topic_stats_period_sec': LaunchConfiguration('topic_stats_period_sec'),
        }],
        emulate_tty=True,
        output='screen',
    )

    return LaunchDescription(arguments + [bridge])
