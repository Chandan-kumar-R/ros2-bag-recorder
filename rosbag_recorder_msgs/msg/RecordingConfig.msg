# Everything needed to describe one recording session.
#
# This mirrors the keys of ros2_bag_recorder's rosbag_param.yaml so a config
# built in the UI and a config written by hand stay interchangeable.

# --- topic selection -------------------------------------------------------
string SELECTION_REGISTRY="registry"
string SELECTION_KEYWORDS="keywords"
string SELECTION_MANUAL="manual"

# 'registry', 'keywords' or 'manual'.
string selection_method

# Substring keywords, used only when selection_method is 'keywords'.
string[] keywords

# Exact topic names ticked by hand, used only when selection_method is
# 'manual'. The recorder itself only understands 'registry' and 'keywords', so
# the bridge writes this list out as a one-module topic registry and runs the
# recorder in ordinary registry mode against it.
string[] manual_topics

# Registry module names to enable, used only when selection_method is
# 'registry'. Modules not listed here are treated as disabled.
string[] modules

# Regex blocklist, applied last in both modes.
string[] exclude_patterns

# Absolute path to a topic registry YAML. Empty means the bridge uses the
# copy installed in ros2_bag_recorder's share directory.
string registry_file

# --- output ----------------------------------------------------------------
string bag_path
string bag_name
bool append_timestamp

bool storage_sqlite
bool storage_mcap

# Seconds between ROS graph re-scans for newly appearing topics.
float64 discovery_interval_sec
