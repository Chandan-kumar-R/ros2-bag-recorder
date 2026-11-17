#!/bin/bash
# Source ROS and the workspace, then run the given command.
set -e

source "/opt/ros/${ROS_DISTRO}/setup.bash"
source "${WS}/install/setup.bash"

exec "$@"
