"""Constants for the Comelit integration."""

DOMAIN = "comelit_intercom"

# Configuration keys
CONF_HOST = "host"
CONF_PORT = "port"
CONF_TOKEN = "token"
# Name/email of a dedicated user (paired via the Comelit app) whose token to
# extract from a device backup — so Home Assistant uses its own identity.
CONF_USER_MATCH = "dedicated_user"
# Web-UI (port 8080) admin password, used to auto-provision a dedicated user
# and to extract tokens from device backups.
CONF_WEB_PASSWORD = "web_password"

# Default values
DEFAULT_PORT = 64100
# Web-UI (config/backup) port and its factory-default admin password.
DEFAULT_WEB_PORT = 8080
DEFAULT_WEB_PASSWORD = "comelit"
# Name of the dedicated user the integration auto-creates for its own identity.
HA_USER_NAME = "Home Assistant"

# Update interval (in seconds)
UPDATE_INTERVAL = 300  # 5 minutes

# --- Push notifications (FCM) ---
# Optional feature: receive real-time doorbell/ring events via Comelit's cloud
# push (Firebase Cloud Messaging). These are the Comelit Android app's
# (com.comelit.bigapp) Firebase project credentials, extracted from the public
# APK. They identify the app's FCM project so we can register a token that
# Comelit's push backend will deliver ring events to.
CONF_ENABLE_NOTIFICATIONS = "enable_notifications"
# Optional: enroll the push token under a *different* ICONA identity token than
# the one used for control, so a paired phone keeps its own push registration.
CONF_PUSH_TOKEN = "push_token"

FCM_PROJECT_ID = "friend-home-55eb5"
FCM_APP_ID = "1:140273510303:android:ecb227a626746c69"
FCM_API_KEY = "AIzaSyDPANoOl3vYKoGPk3CqjDjIbJHrhJUzz7M"
FCM_SENDER_ID = "140273510303"
FCM_BUNDLE_ID = "com.comelit.bigapp"

# Re-enroll the push token this often (seconds) so the device keeps forwarding.
PUSH_REENROLL_INTERVAL = 6 * 3600  # 6 hours

# Storage key prefix for persisted FCM credentials (per config entry).
STORAGE_VERSION = 1
STORAGE_KEY_FCM = "comelit_intercom_fcm"

# HA event fired on the bus when the doorbell rings.
EVENT_DOORBELL = "comelit_intercom_doorbell"
