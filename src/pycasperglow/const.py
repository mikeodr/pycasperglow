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

# Dimming time (keyed by minutes)
# TODO Need to verify these action bodies, likely wrong still
ACTION_BODY_DIM_15 = bytes.fromhex("1a04080210 0f".replace(" ", ""))
ACTION_BODY_DIM_30 = bytes.fromhex("1a04080210 1e".replace(" ", ""))
ACTION_BODY_DIM_45 = bytes.fromhex("1a04080210 2d".replace(" ", ""))
ACTION_BODY_DIM_60 = bytes.fromhex("1a04080210 3c".replace(" ", ""))
ACTION_BODY_DIM_90 = bytes.fromhex("1a04080210 5a".replace(" ", ""))

# Brightness (keyed by level 1-5)
# TODO Need to verify these action bodies, likely wrong still
ACTION_BODY_BRIGHTNESS_1 = bytes.fromhex("1a040804 1001".replace(" ", ""))
ACTION_BODY_BRIGHTNESS_2 = bytes.fromhex("1a040804 1002".replace(" ", ""))
ACTION_BODY_BRIGHTNESS_3 = bytes.fromhex("1a040804 1003".replace(" ", ""))
ACTION_BODY_BRIGHTNESS_4 = bytes.fromhex("1a040804 1004".replace(" ", ""))
ACTION_BODY_BRIGHTNESS_5 = bytes.fromhex("1a040804 1005".replace(" ", ""))

# Lookup tables
DIMMING_TIME_MINUTES: tuple[int, ...] = (15, 30, 45, 60, 90)

DIMMING_TIME_TO_ACTION: dict[int, bytes] = {
    15: ACTION_BODY_DIM_15,
    30: ACTION_BODY_DIM_30,
    45: ACTION_BODY_DIM_45,
    60: ACTION_BODY_DIM_60,
    90: ACTION_BODY_DIM_90,
}

BRIGHTNESS_TO_ACTION: dict[int, bytes] = {
    1: ACTION_BODY_BRIGHTNESS_1,
    2: ACTION_BODY_BRIGHTNESS_2,
    3: ACTION_BODY_BRIGHTNESS_3,
    4: ACTION_BODY_BRIGHTNESS_4,
    5: ACTION_BODY_BRIGHTNESS_5,
}

HANDSHAKE_TIMEOUT = 10.0
