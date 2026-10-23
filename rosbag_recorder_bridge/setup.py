import os
from glob import glob

from setuptools import find_packages, setup

package_name = 'rosbag_recorder_bridge'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='wall-e',
    maintainer_email='c.k.rajendra@saxion.nl',
    description='Headless ROS 2 control surface for ros2_bag_recorder.',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'recorder_bridge=rosbag_recorder_bridge.bridge_node:main',
        ],
    },
)
