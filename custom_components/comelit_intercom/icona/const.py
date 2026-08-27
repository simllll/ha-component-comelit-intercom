"""Constants for the Comelit Local integration."""

DOMAIN = "comelit_intercom_local"
MANUFACTURER = "Comelit"
MODEL = "6701W"

CONF_HTTP_PORT = "http_port"
CONF_VIDEO_AUTO_RECONNECT = "video_auto_reconnect"
CONF_ENABLE_NOTIFICATIONS = "enable_notifications"
CONF_VERBOSE_LOGGING = "verbose_logging"
CONF_ENABLE_AUDIO = "enable_audio"

_verbose_logging: bool = False


def is_verbose_logging() -> bool:
    """Return True when verbose logging is enabled via the integration options."""
    return _verbose_logging


def set_verbose_logging(enabled: bool) -> None:
    """Set the verbose logging flag (called on setup and options reload)."""
    global _verbose_logging
    _verbose_logging = enabled


_audio_enabled: bool = True


def is_audio_enabled() -> bool:
    """Return True when the RTSP stream should advertise/carry the audio track."""
    return _audio_enabled


def set_audio_enabled(enabled: bool) -> None:
    """Set the audio-stream flag (called on setup and options reload)."""
    global _audio_enabled
    _audio_enabled = enabled


# Talk-back (mic → entrance) advertised in the SDP as a second, recvonly PCMA
# track. Off by default: a second same-payload audio m-line confuses go2rtc's
# track mapping and breaks the whole stream, so it's only advertised when
# two-way answering is enabled. Tied to the auto_answer option.
_talkback_enabled: bool = False


def is_talkback_enabled() -> bool:
    """Return True when the RTSP SDP should advertise the mic backchannel."""
    return _talkback_enabled


def set_talkback_enabled(enabled: bool) -> None:
    """Set the talk-back flag (called on setup and options reload)."""
    global _talkback_enabled
    _talkback_enabled = enabled


DEFAULT_PORT = 64100
DEFAULT_HTTP_PORT = 8080

# Video config sent to the device via encode_video_config().
VIDEO_WIDTH = 800
VIDEO_HEIGHT = 480
VIDEO_FPS = 16
