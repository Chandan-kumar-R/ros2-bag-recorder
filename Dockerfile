# ROS 2 Bag Recorder, ROS 2 Jazzy on Ubuntu 24.04.
#
# Two targets:
#   headless   (default) recorder + bridge, no GUI. Runs on the robot.
#   dashboard  adds PySide6 and the Qt runtime libraries for the GUI.
#
#   docker build -t ros2-bag-recorder:jazzy .
#   docker build -t ros2-bag-recorder:jazzy-dashboard --target dashboard .
#
# See the Docker section of README.md for run commands, or use compose.yaml.

ARG ROS_DISTRO=jazzy

# ----------------------------------------------------------------------------
#  Build the workspace
# ----------------------------------------------------------------------------
FROM ros:${ROS_DISTRO}-ros-base AS base

ARG ROS_DISTRO
ENV ROS_DISTRO=${ROS_DISTRO} \
    WS=/ros2_ws \
    DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

WORKDIR ${WS}

# Optional extras the package.xml files do not pull in: MCAP output.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ros-${ROS_DISTRO}-rosbag2-storage-mcap \
    && rm -rf /var/lib/apt/lists/*

# Resolve dependencies from the manifests alone, so a source-only change
# does not re-run apt.
COPY ros2_bag_recorder/package.xml      src/ros2-bag-recorder/ros2_bag_recorder/
COPY rosbag_recorder_msgs/package.xml   src/ros2-bag-recorder/rosbag_recorder_msgs/
COPY rosbag_recorder_bridge/package.xml src/ros2-bag-recorder/rosbag_recorder_bridge/
COPY rosbag_recorder_ui/package.xml     src/ros2-bag-recorder/rosbag_recorder_ui/
RUN apt-get update \
    && rosdep update --rosdistro ${ROS_DISTRO} \
    && rosdep install --from-paths src --ignore-src -y --rosdistro ${ROS_DISTRO} \
    && rm -rf /var/lib/apt/lists/*

COPY . src/ros2-bag-recorder
RUN . /opt/ros/${ROS_DISTRO}/setup.sh \
    && colcon build --event-handlers console_direct- \
    && rm -rf build log

COPY docker/entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

# Bags are written here; mount a host directory over it.
VOLUME ["/root/rosbags"]

# ----------------------------------------------------------------------------
#  Dashboard: base + Qt
# ----------------------------------------------------------------------------
FROM base AS dashboard

# The PySide6 wheel bundles Qt but not the X11/xcb libraries it loads.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3-pip \
        libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
        libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 \
        libxcb-xkb1 libxkbcommon-x11-0 libxkbcommon0 libx11-xcb1 \
        libgl1 libegl1 libfontconfig1 libdbus-1-3 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Ubuntu 24.04 has no PySide6 package and marks the system Python as
# externally managed (PEP 668), hence --break-system-packages.
RUN pip3 install --no-cache-dir --break-system-packages PySide6

ENV QT_X11_NO_MITSHM=1
CMD ["ros2", "launch", "rosbag_recorder_ui", "dashboard.launch.py"]

# ----------------------------------------------------------------------------
#  Headless (default): the bridge, driven by a dashboard or service calls
# ----------------------------------------------------------------------------
FROM base AS headless

CMD ["ros2", "launch", "rosbag_recorder_bridge", "bridge.launch.py"]
