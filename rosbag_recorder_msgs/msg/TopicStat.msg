# Per-topic view of the ROS graph as the bridge currently understands it.
#
# Any numeric field that could not be determined is published as -1 so the UI
# can render 'N/A' instead of inventing a value.

uint8 STATE_UNSELECTED=0    # live, but not matched by the current selection
uint8 STATE_SELECTED=1      # matched; would be recorded if recording started
uint8 STATE_EXCLUDED=2      # matched by selection but killed by exclude_patterns
uint8 STATE_RECORDING=3     # actively subscribed by the recorder right now
uint8 STATE_FAILED=4        # selected, but its message type could not be imported
uint8 STATE_LOST=5          # was being recorded, has since left the graph

string name
string type
uint8 state

int32 publisher_count       # -1 when unknown
int32 subscriber_count      # -1 when unknown

float64 hz                  # -1.0 when not being measured
float64 bytes_per_sec       # -1.0 when not being measured
int64 message_count         # -1 when not counted (only counted while recording)

# QoS of the publisher(s), as resolved by the bridge. Empty string = unknown.
string reliability
string durability
string history
int32 depth                 # -1 when unknown

bool rate_monitored         # true when a rate probe is attached to this topic
bool newly_discovered       # appeared in the graph within the last few scans
