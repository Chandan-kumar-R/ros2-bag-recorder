<h1 align="center">ROS 2 Bag Recorder</h1>

<p align="center">
  <a href="https://docs.ros.org/en/jazzy/"><img alt="ROS 2: Jazzy" src="https://img.shields.io/badge/ROS%202-Jazzy-22314E?logo=ros&logoColor=white"></a>
  <a href="https://releases.ubuntu.com/24.04/"><img alt="Ubuntu: 24.04" src="https://img.shields.io/badge/Ubuntu-24.04-E95420?logo=ubuntu&logoColor=white"></a>
  <img alt="Python: 3.12" src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white">
  <img alt="GUI: PySide6" src="https://img.shields.io/badge/GUI-PySide6-41CD52?logo=qt&logoColor=white">
  <img alt="Storage: sqlite3 and MCAP" src="https://img.shields.io/badge/Storage-sqlite3%20%C2%B7%20MCAP-6E40C9">
  <a href="#-docker"><img alt="Docker: ready" src="https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white"></a>
  <a href="LICENSE"><img alt="License: Apache 2.0" src="https://img.shields.io/badge/License-Apache%202.0-D4A017"></a>
</p>

<p align="center">
  <img src="docs/dashboard_ex.gif" alt="The ROS 2 Bag Recorder dashboard: idle, recording, the live topic table, pre-flight checks, and the finished bag" width="900">
</p>

<p align="center">
  <b><i>A dashboard for recording ROS 2 bags.</i></b><br>
  <sub>20 seconds, real UI. <a href="docs/dashboard_ex.mp4">Download the MP4</a> for full resolution and sound.</sub>
</p>

---

## 🚀 Overview

Pick topics, check the setup, then start and stop recordings from one window, without typing a long `ros2 bag record` command. Your topic list is saved as YAML, so every run records the same topics. Run the dashboard on your laptop to control a recorder on your robot; the bag is saved on the robot, not sent over the network.

- Author: Chandan Kumar Rajendra ([@Chandan-kumar-R](https://github.com/Chandan-kumar-R))
- Tested on: Ubuntu 22.04 with ROS 2 Humble, and Ubuntu 24.04 with ROS 2 Jazzy

**Which branch?**

- [`main`](https://github.com/Chandan-kumar-R/ros2-bag-recorder/tree/main) : ROS 2 Humble, Ubuntu 22.04
- [`jazzy`](https://github.com/Chandan-kumar-R/ros2-bag-recorder/tree/jazzy) : ROS 2 Jazzy, Ubuntu 24.04

**Highlights**

- **Pick topics in YAML :** by module, by keyword, or by ticking them in the UI.
- **Never write message types :** They come from the live ROS graph.
- **Late topics are caught.** The graph is re-scanned while recording, not only at startup.
- **`sqlite3`, MCAP, or both** in a single pass.
- **The recorder is headless.** The dashboard is optional, and can run on your laptop while the robot records.

---

## 📖 Documentation

- [Quick start](#-quick-start) : install, build, run
- [Docker](#-docker) : run it without installing ROS dependencies
- [How it works](#-how-it-works) : what runs where, and how the robot and your laptop talk
- [Usage](#-usage) : terminal, dashboard, remote robot, or from your own code
- [Configuration](#-configuration) : the two YAML files

---

## 🤔 Why not just `ros2 bag record`?

Use `ros2 bag record` for a one-off. Use this when you record the same robot every day.

| | `ros2 bag record` | ROS 2 Bag Recorder |
|---|---|---|
| Topic list lives in | a shell alias | a version-controlled YAML file |
| Selecting topics | name them all, every time | modules, keywords, or tick them in a UI |
| Topic that appears late | missed | picked up automatically |
| Topic that is renamed | silently missed | reported as unmatched, by name |
| Message type missing | the run fails | that topic is skipped and logged |
| Output formats | one per run | `sqlite3` + MCAP in one pass |
| Remote operation | ssh in and hope | a dashboard on your laptop |
| Starting a recording from code | spawn a process | call a ROS 2 service |

---

## ✨ Features

| | |
|---|---|
| **Topic selection** | Registry modules, substring keywords, or hand-ticked. Regex excludes applied last, so an exclusion always wins. |
| **QoS matching** | Per publisher, so `best_effort` sensor streams and `transient_local` topics like `/tf_static` are both captured. |
| **Live discovery** | Topics that start publishing mid-recording are added on the fly. |
| **Pre-flight** | Path, name collision, disk space, storage plugin and selection are checked **on the recording machine**. `START` unlocks only when they pass. |
| **Topic table** | Every topic on the graph, coloured by what your selection does to it: *will record*, *excluded*, *recording*, *type failed*, *lost*. |
| **Preview** | Computed by the same code the recorder uses, so it cannot drift from what actually gets recorded. |
| **Editable registry** | Add topics, patterns and modules from the UI and save back to the robot, validated before it is written. |
| **Remote** | Bridge on the robot, window on your laptop. Recorded data never crosses the network. |
| **Scriptable** | Any ROS 2 node, a mission script, a state machine can drive recordings through the same services. |
| **Crash-safe** | Close the dashboard, lose the network or kill the GUI; the recording carries on and closes cleanly. |

---

## ⚡ Quick start

**Requires** [Ubuntu 24.04](https://releases.ubuntu.com/24.04/) · [ROS 2 Jazzy](https://docs.ros.org/en/jazzy/)

> This is the **`jazzy`** branch, for ROS 2 Jazzy. For Ubuntu 22.04 and ROS 2 Humble, use the [`main`](https://github.com/Chandan-kumar-R/ros2-bag-recorder/tree/main) branch.

```bash
# 1. dependencies
sudo apt install ros-jazzy-rosbag2-py                  # required
sudo apt install ros-jazzy-rosbag2-storage-mcap        # optional: MCAP output
sudo apt install libxcb-cursor0 python3-psutil         # dashboard
pip3 install --user --break-system-packages PySide6    # dashboard
```

Ubuntu 24.04 ships no PySide6 package and marks the system Python as externally managed (PEP 668), so `pip` needs `--break-system-packages`. With `--user` it only touches `~/.local`.

```bash
# 2. build
cd ~/ros2_ws/src
git clone -b jazzy https://github.com/Chandan-kumar-R/ros2-bag-recorder.git
cd ~/ros2_ws
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
source install/setup.bash
```

```bash
# 3. run
ros2 launch rosbag_recorder_ui dashboard.launch.py     # dashboard
ros2 launch ros2_bag_recorder recorder.launch.py       # terminal only
```

Recorder only, without the GUI dependencies:

```bash
colcon build --symlink-install --packages-select ros2_bag_recorder
```

> **Note** `libxcb-cursor0` is not optional for the dashboard. Qt 6.5+ needs it, the PySide6 wheel does not ship it, and Ubuntu does not install it by default. Without it Qt aborts with a misleading "reinstall the application" message.

---

## 🐳 Docker

No ROS on the host? Run it in a container. The image is ROS 2 Jazzy on Ubuntu 24.04 with MCAP support.

### Quick start: `start.sh`

```bash
./start.sh dashboard     # bridge + dashboard window on this display
./start.sh bridge        # headless bridge, e.g. on the robot
./start.sh recorder      # terminal recorder, packaged rosbag_param.yaml
./start.sh shell         # bash inside the image
```

It builds the image on first use and handles the networking, the bag folder and X11 access for you. Bags land in `~/rosbags`. Stop with `Ctrl-C`, or close the dashboard window.

| Variable | Default | Meaning |
|---|---|---|
| `ROS_DOMAIN_ID` | `0` | Domain to join. Must match the nodes you record. |
| `BAG_DIR` | `~/rosbags` | Host directory the bags are written to |
| `CONFIG_DIR` | | Host directory mounted read-only at `/config` |
| `REBUILD=1` | | Rebuild the image, e.g. after pulling changes |

Anything after the mode is passed to `ros2 launch`:

```bash
CONFIG_DIR=~/rec ./start.sh recorder params_file:=/config/my_params.yaml
ROS_DOMAIN_ID=99 ./start.sh dashboard use_bridge:=false
```

### By hand

The Dockerfile has two targets. A plain `docker build` builds the last one, `headless`.

| Target | Contains | Default command | Size |
|---|---|---|---|
| `headless` (default) | recorder + bridge | `bridge.launch.py` | ~1.3 GB |
| `dashboard` | the above + PySide6 and the Qt libraries | `dashboard.launch.py` | ~2.6 GB |

```bash
# build, from the repository root
docker build -t ros2-bag-recorder:jazzy .
docker build -t ros2-bag-recorder:jazzy-dashboard --target dashboard .
```

Always run with `--net=host --ipc=host`, or DDS cannot see the nodes outside the container. Also set `FASTDDS_BUILTIN_TRANSPORTS=UDPv4`: the container runs as root, and Fast DDS shared memory between root and a normal user finds the topics but delivers no messages. Bags are written to `/root/rosbags` in the container, so mount a host directory there.

```bash
# on the robot: the bridge, driven from a dashboard or service calls
docker run --rm -it --net=host --ipc=host \
  -e FASTDDS_BUILTIN_TRANSPORTS=UDPv4 \
  -v ~/rosbags:/root/rosbags \
  ros2-bag-recorder:jazzy
```

```bash
# terminal recorder with your own parameter file
docker run --rm -it --net=host --ipc=host \
  -e FASTDDS_BUILTIN_TRANSPORTS=UDPv4 \
  -v ~/rosbags:/root/rosbags \
  -v $(pwd)/my_params.yaml:/params.yaml:ro \
  ros2-bag-recorder:jazzy \
  ros2 launch ros2_bag_recorder recorder.launch.py params_file:=/params.yaml
```

```bash
# the dashboard (let root in the container use your display first)
xhost +SI:localuser:root
docker run --rm -it --net=host --ipc=host \
  -e FASTDDS_BUILTIN_TRANSPORTS=UDPv4 \
  -e DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v ~/rosbags:/root/rosbags \
  ros2-bag-recorder:jazzy-dashboard
```

The same setups with [`compose.yaml`](compose.yaml); bags land in `./rosbags`:

```bash
docker compose up bridge                # headless bridge
docker compose up dashboard             # bridge + dashboard
docker compose run --rm recorder        # terminal recorder
```

### Good to know

- Use the same `ROS_DOMAIN_ID` inside and outside the container (`-e ROS_DOMAIN_ID=...`).
- `docker stop` ends a recording cleanly: the image's stop signal is SIGINT, the same as `Ctrl-C`.
- The container runs as root, so the bags it writes are owned by root on the host. `sudo chown -R $USER ~/rosbags` hands them back.
- Message packages must be installed **in the image** for their topics to be recorded. For custom messages, build them into a derived image (`FROM ros2-bag-recorder:jazzy`).

---

## 🧭 How it works

<p align="center">
  <img src="docs/architecture.png" alt="Deployment architecture" width="1000">
</p>

- The dashboard sends **commands** and receives **status** over ROS 2 services and topics.
- Recorded data never crosses that boundary, it goes straight onto the robot's own disk. A 4K camera stream costs the dashboard nothing.
- One machine or two: the picture is the same, only the latency differs.-
- Diagram source: [`docs/architecture.drawio`](docs/architecture.drawio) editable in [diagrams.net](https://app.diagrams.net/). Re-export to `docs/architecture.png` after changing it.
- Diagram source: [`docs/architecture.drawio`](docs/architecture.drawio). Re-export to `docs/architecture.png` after editing.

---

## 💻 Usage

### 1. Record from a terminal

Edit [`rosbag_param.yaml`](ros2_bag_recorder/config/rosbag_param.yaml), then:

```bash
ros2 launch ros2_bag_recorder recorder.launch.py
```

Stop with `Ctrl-C`. Bags land in `bag_folder.path` (default `~/rosbags`).

To use a parameter file somewhere else:

```bash
ros2 launch ros2_bag_recorder recorder.launch.py params_file:=/path/to/my_params.yaml
```

### 2. Record from the dashboard

Starts the bridge and the window together:

```bash
ros2 launch rosbag_recorder_ui dashboard.launch.py
```

For an entry in the Ubuntu application grid that sources ROS and this workspace for you:

```bash
ros2 run rosbag_recorder_ui install_desktop_entry
```

> Closing the window shuts down the stack it started. A bridge you started yourself keeps recording.

### 3. Record on a robot, drive it from your laptop

Both machines need the same `ROS_DOMAIN_ID` and a route to each other.

```bash
# on the robot
ros2 launch rosbag_recorder_bridge bridge.launch.py default_bag_path:=/data/rosbags
```

```bash
# on your laptop
ros2 launch rosbag_recorder_ui dashboard.launch.py use_bridge:=false
```

Every path, check and number is then the robot's answer, not your laptop's.

### 4. Drive it from your own code

The bridge is a plain ROS 2 node, so a mission script can record without any of the UI:

```bash
ros2 service call /rosbag_recorder_bridge/start_recording \
  rosbag_recorder_msgs/srv/StartRecording \
  "{config: {selection_method: 'keywords', keywords: ['camera'],
             bag_path: '/data/rosbags', bag_name: 'run_42',
             append_timestamp: true, storage_sqlite: true,
             discovery_interval_sec: 1.0}}"

ros2 service call /rosbag_recorder_bridge/stop_recording \
  rosbag_recorder_msgs/srv/StopRecording "{}"
```

<p align="center">
  <img src="docs/topics.png" alt="The dashboard's live topic table" width="900">
</p>

---

## 🔧 Configuration

Two files. The dashboard reads and writes the same ones.

### [`topic_registry.yaml`](ros2_bag_recorder/config/topic_registry.yaml) : what *can* be recorded

Topics grouped into **modules**. Each entry has exactly one key `topic` or `pattern`:

```yaml
camera:
  - topic: /camera/left/image         # an exact name
  - topic: /camera/right/camera_info
  - pattern: /camera/.+/image         # ...or match many with one regex (fullmatch)
```

- Mix both kinds freely in one module.
- Message types are **not** listed they come from the ROS graph at runtime.
- New module = a section here plus a toggle under `modules:` below.

### [`rosbag_param.yaml`](ros2_bag_recorder/config/rosbag_param.yaml) : what *is* recorded this run

| Key | Meaning |
|---|---|
| `selection_method` | `'registry'`, `'keywords'` or `'manual'` |
| `keywords` | Substring keywords; `keywords` mode only, e.g. `['camera', 'gps']` |
| `manual_topics` | Exact topic names; `manual` mode only, written by the dashboard |
| `modules.<name>` | Toggle a registry module; `registry` mode only |
| `exclude_patterns` | Regex blocklist, applied last — always wins |
| `bag_folder.path` / `.name` | Where bags are written |
| `bag_folder.append_timestamp` | Suffix `_YYYY-MM-DD_HH-MM-SS`, avoids collisions |
| `storage_id.sqlite` / `.mcap` | Enable either or both output formats |
| `discovery_interval_sec` | How often the graph is re-scanned for new topics |
| `registry_file` | An alternative registry. Empty uses the packaged one. |

### Selection modes

| Mode | Records | Good for |
|---|---|---|
| **`registry`** | The topics in the modules you enable | Curated, repeatable recordings |
| **`keywords`** | Every live topic whose name *contains* a keyword | Quick ad-hoc capture, no registry edit |
| **`manual`** | Exactly the topics ticked in the dashboard | Refining a selection by hand |

Example : `keywords: ['camera', 'gps']` records `/camera/left/image`, `/front/camera_info`, `/gps/fix`, `/ublox/gps_raw`, and anything else matching.

> **`manual` is a dashboard mode.** The recorder understands only `registry` and `keywords`, so a `manual` file run through `ros2 launch` stops with a clear error. The dashboard writes an equivalent registry beside it so the selection still replays from a terminal

### Good to know

- Timestamps are **receive time** (node clock), like `ros2 bag record`.
- Message packages must be installed **on the recording machine**. A topic whose type will not import is skipped and logged the rest of the bag is unaffected.
- Anything the dashboard could not measure reads `N/A`. Never a zero, never a guess.

---

## 📁 Project structure

```
ros2-bag-recorder/
├── ros2_bag_recorder/         The recorder. Standalone, no GUI dependency.
│   ├── config/                topic_registry.yaml, rosbag_param.yaml
│   ├── launch/                recorder.launch.py
│   └── ros2_bag_recorder/     multiple_topic.py, topic_selection.py
│
├── rosbag_recorder_msgs/      Service and message definitions. No code.
│   ├── msg/                   RecorderStatus, RecordingConfig, TopicStat, ...
│   └── srv/                   StartRecording, PreviewSelection, SetRegistry, ...
│
├── rosbag_recorder_bridge/    Headless lifecycle owner. Runs on the robot.
│   └── rosbag_recorder_bridge/
│                              bridge_node.py, session.py, recorder_api.py,
│                              graph.py, rate_monitor.py, sysinfo.py
│
├── rosbag_recorder_ui/        PySide6 dashboard. Runs wherever you are.
│   └── rosbag_recorder_ui/
│       ├── core/              theme, config store, history, formatting, icons
│       ├── ros/               the only file that touches rclpy
│       ├── views/             one module per page
│       └── widgets/           cards, indicators, log panel, sidebar
│
├── docker/                    container entrypoint
├── Dockerfile                 headless and dashboard images
├── compose.yaml               bridge / recorder / dashboard services
├── start.sh                   one-command docker run: dashboard / bridge / recorder
│
└── docs/                      architecture diagram, screenshots, demo clip
```

---

## 🤝 Contributing

Issues and pull requests are welcome.

- Open an issue before a large change.
- Keep `ros2_bag_recorder` usable on its own it must work with none of the other three packages installed.
- Run the tests before opening a PR.
- Match the style of the file you are editing, including its comment density.

---

## 📄 License

Apache License 2.0
