"""The Garmin Personal API's host and the paths the developer script calls."""

GARMIN_PERSONAL_API_BASE = "https://personal.connectapi.garmin.com"
TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"  # noqa: S105
ACTIVITY_SEARCH_PATH = "/activitylist-service/activities/search/activities"
ACTIVITY_PATH = "/activity-service/activity/{activity_id}"
ACTIVITY_FILE_PATH = "/download-service/files/activity/{activity_id}"  # ZIP of the original file
GARMIN_TIMEOUT = 30  # seconds, for each phase of a Garmin HTTP request
