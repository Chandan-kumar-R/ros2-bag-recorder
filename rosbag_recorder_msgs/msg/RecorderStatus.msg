# Heartbeat of the recorder. Published on a latched (transient_local) topic so
# a UI that starts late still learns the current state immediately.

uint8 STATE_IDLE=0
uint8 STATE_PREPARING=1
uint8 STATE_RECORDING=2
uint8 STATE_STOPPING=3
uint8 STATE_ERROR=4

builtin_interfaces/Time stamp

uint8 state
string state_detail          # short operator-readable qualifier, may be empty

float64 duration_sec         # 0.0 unless recording or just finished
uint64 bag_size_bytes        # summed on-disk size of every open bag
float64 write_rate_bytes_per_sec
uint32 topic_count           # topics actually subscribed by the recorder
uint64 message_count         # messages handed to the writers
uint32 failed_topic_count    # selected topics whose type could not be imported
uint32 lost_topic_count      # topics that vanished mid-recording

string bag_path
string bag_name
string[] bag_uris            # one per active writer
string[] active_writers      # 'sqlite3', 'mcap'

uint64 disk_free_bytes
uint64 disk_total_bytes

# Populated when state is ERROR, cleared on the next successful start.
string last_error

# The config the current (or most recent) session was started with.
RecordingConfig config
