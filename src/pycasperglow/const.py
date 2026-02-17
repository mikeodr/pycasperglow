"""BLE UUIDs and packet constants for Casper Glow."""

SERVICE_UUID = "9bb30001-fee9-4c24-8361-443b5b7c88f6"
WRITE_CHAR_UUID = "9bb30002-fee9-4c24-8361-443b5b7c88f6"
READ_CHAR_UUID = "9bb30003-fee9-4c24-8361-443b5b7c88f6"

DEVICE_NAME_PREFIX = "Jar"

RECONNECT_PACKET = bytes.fromhex("080122026a00")
READY_MARKER = bytes.fromhex("72020800")

ACTION_BODY_ON = bytes.fromhex("1a020802")
ACTION_BODY_OFF = bytes.fromhex("1a020804")

# Pause / Resume
ACTION_BODY_PAUSE = bytes.fromhex("1a020805")
ACTION_BODY_RESUME = bytes.fromhex("1a020806")

# State query — asks the device to report its current state
QUERY_STATE_BODY = bytes.fromhex("52020803")

# Valid dimming times the iOS app allows (in minutes)
DIMMING_TIME_MINUTES: tuple[int, ...] = (15, 30, 45, 60, 90)

# Brightness levels the iOS app uses (percentages)
# Level 1 (dimmest) = 60%, Level 5 (brightest) = 100%
BRIGHTNESS_LEVELS: tuple[int, ...] = (60, 70, 80, 90, 100)

HANDSHAKE_TIMEOUT = 10.0
STATE_RESPONSE_TIMEOUT = 5.0
