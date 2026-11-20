"""Garmin's Developer Program hosts and the paths the integration calls, its timeouts,
and the activity types it imports.
"""

GARMIN_AUTHORIZE_URL = "https://connect.garmin.com/oauth2Confirm"
GARMIN_TOKEN_URL = "https://diauth.garmin.com/di-oauth2-service/oauth/token"  # noqa: S105
GARMIN_API_HOST = "apis.garmin.com"
GARMIN_USER_ID_URL = "https://apis.garmin.com/partner-gateway/rest/user/id"
GARMIN_USER_PERMISSIONS_URL = "https://apis.garmin.com/partner-gateway/rest/user/permissions"
GARMIN_USER_REGISTRATION_URL = "https://apis.garmin.com/partner-gateway/rest/user/registration"
ACTIVITY_FILE_PATH = "/wellness-api/rest/activityFile"  # on GARMIN_API_HOST, over https

GARMIN_TIMEOUT = 30  # seconds, for each phase of a Garmin HTTP request
# seconds waited before each retry of a user call that answers 403 during the code
# exchange, while Garmin hasn't registered the new user yet
USER_CALL_RETRY_DELAYS_S = (1, 2, 4)
# largest activity file accepted, as downloaded and as decompressed from a ZIP
MAX_FILE_BYTES = 25 * 1024 * 1024

# the permission a user grants for their activities to be sent
ACTIVITY_EXPORT_PERMISSION = "ACTIVITY_EXPORT"
# header carrying the client ID of the app a notification is sent to
CLIENT_ID_HEADER = "garmin-client-id"

# top-level keys of a notification body
ACTIVITY_FILES = "activityFiles"
DEREGISTRATIONS = "deregistrations"
USER_PERMISSIONS_CHANGE = "userPermissionsChange"

# Garmin activity types that are runs; a notification without a type is imported too,
# and the FIT file's sport decides
RUNNING_ACTIVITY_TYPES = frozenset(
    {
        "RUNNING",
        "INDOOR_RUNNING",
        "OBSTACLE_RUN",
        "STREET_RUNNING",
        "TRACK_RUNNING",
        "TRAIL_RUNNING",
        "TREADMILL_RUNNING",
        "ULTRA_RUN",
        "VIRTUAL_RUN",
    }
)
