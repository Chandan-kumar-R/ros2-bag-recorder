#!/usr/bin/env bash
# Start the ROS 2 Bag Recorder in Docker. Builds the image on first use.
#
#   ./start.sh dashboard   bridge + dashboard window on this display
#   ./start.sh bridge      headless bridge, driven by a dashboard elsewhere
#   ./start.sh recorder    terminal recorder, packaged rosbag_param.yaml
#   ./start.sh shell       bash inside the image
#
# Anything after the mode goes to ros2 launch, for example:
#   CONFIG_DIR=~/rec ./start.sh recorder params_file:=/config/my_params.yaml
#
# Environment:
#   ROS_DOMAIN_ID   domain to join (default 0)
#   BAG_DIR         host directory the bags land in (default ~/rosbags)
#   CONFIG_DIR      host directory mounted read-only at /config (optional)
#   REBUILD=1       rebuild the image even if it exists
set -euo pipefail

DISTRO=jazzy
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

MODE="${1:-}"
[ -n "$MODE" ] || usage 1
shift

case "$MODE" in
  dashboard) TARGET=dashboard; TAG="$DISTRO-dashboard" ;;
  bridge|recorder|shell) TARGET=headless; TAG="$DISTRO" ;;
  -h|--help|help) usage 0 ;;
  *) echo "Unknown mode '$MODE'." >&2; usage 1 ;;
esac
IMAGE="ros2-bag-recorder:$TAG"
NAME="ros2-bag-recorder-$MODE"

if [ "${REBUILD:-0}" = 1 ] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building $IMAGE ..."
  docker build -t "$IMAGE" --target "$TARGET" "$HERE"
fi

if [ -n "$(docker ps -q --filter "name=^${NAME}$")" ]; then
  echo "'$NAME' is already running. Stop it with: docker stop $NAME" >&2
  exit 1
fi

BAG_DIR="${BAG_DIR:-$HOME/rosbags}"
mkdir -p "$BAG_DIR"

# Host network and IPC so DDS sees the nodes outside the container. UDP only:
# the container runs as root, and Fast DDS shared memory between root and a
# normal user discovers topics but delivers no data.
ARGS=(--rm --name "$NAME" --net=host --ipc=host
      -e "ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-0}"
      -e FASTDDS_BUILTIN_TRANSPORTS=UDPv4
      -v "$BAG_DIR:/root/rosbags")
[ -t 0 ] && ARGS+=(-it)
if [ -n "${CONFIG_DIR:-}" ]; then
  ARGS+=(-v "$(cd "$CONFIG_DIR" && pwd):/config:ro")
fi

case "$MODE" in
  dashboard)
    if [ -z "${DISPLAY:-}" ]; then
      echo 'DISPLAY is not set; the dashboard needs an X11 display.' >&2
      exit 1
    fi
    # Let root in the container draw on this display, and nobody else.
    xhost +SI:localuser:root >/dev/null
    ARGS+=(-e DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix:rw)
    CMD=(ros2 launch rosbag_recorder_ui dashboard.launch.py
         default_bag_path:=/root/rosbags "$@")
    ;;
  bridge)
    CMD=(ros2 launch rosbag_recorder_bridge bridge.launch.py
         default_bag_path:=/root/rosbags "$@")
    ;;
  recorder)
    CMD=(ros2 launch ros2_bag_recorder recorder.launch.py "$@")
    ;;
  shell)
    CMD=(bash "$@")
    ;;
esac

echo "Starting $NAME on ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-0}, bags in $BAG_DIR"
exec docker run "${ARGS[@]}" "$IMAGE" "${CMD[@]}"
