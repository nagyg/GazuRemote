import gazu
import functools
import traceback
import threading

from gazu.exception import HostException, MethodNotAllowedException, AuthFailedException

from services.config_service import ConfigService

DEBUG_MODE = False
_config_service = ConfigService()
_api_lock = threading.Lock()
_is_reauthenticating = False


def set_debug_mode(enabled):
    """Sets the debug mode for the Gazu API module."""
    global DEBUG_MODE
    DEBUG_MODE = enabled
    if DEBUG_MODE:
        print("GazuRemote API: Debug mode enabled.")


def ensure_connection():
    """
    Ensures that the connection to the Zou server is still active.
    If not, it attempts to re-authenticate using the stored credentials.
    Uses a lock to prevent concurrent re-authentication from multiple threads.
    """
    global _is_reauthenticating

    try:
        gazu.client.get_current_user()
        return True, None
    except Exception as e:
        if DEBUG_MODE:
            print(f"GazuRemote API: Initial connection check failed ({e}). Attempting re-auth...")

    with _api_lock:
        try:
            gazu.client.get_current_user()
            return True, None
        except Exception:
            pass

        if _is_reauthenticating:
            return True, None

        _is_reauthenticating = True
        try:
            credentials = _config_service.load_credentials()
            host = credentials.get("host")
            user = credentials.get("user")
            password = credentials.get("password")

            if not all([host, user, password]):
                return False, "Stored credentials incomplete. Manual login required."

            success, message = connect_to_zou(host, user, password)
            if success:
                if DEBUG_MODE:
                    print("GazuRemote API: Re-authentication successful.")
                return True, None
            else:
                return False, f"Re-authentication failed: {message}"
        finally:
            _is_reauthenticating = False


def _gazu_api_call(func):
    """
    Decorator to handle common Gazu API call patterns:
    - Ensures connection before the call.
    - Catches any exceptions.
    - Returns a standard (success, data) tuple.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        func_name = func.__name__

        if func_name not in ["connect_to_zou", "get_user_role"]:
            conn_ok, conn_error = ensure_connection()
            if not conn_ok:
                print(f"GazuRemote API Error: Connection failed for {func_name}. {conn_error}")
                return False, conn_error

        try:
            if DEBUG_MODE:
                print(f"GazuRemote API: Executing {func_name}...")
            result = func(*args, **kwargs)
            if DEBUG_MODE:
                print(f"GazuRemote API: {func_name} executed successfully.")
            return True, result
        except Exception as e:
            print(f"GazuRemote API Error: An error occurred during {func_name}.")
            traceback.print_exc()
            return False, str(e)

    return wrapper


def connect_to_zou(host, email, password):
    """
    Connects to the Zou server and logs in with the provided credentials.
    Returns a (success, message) tuple.
    """
    try:
        if DEBUG_MODE:
            print(f"GazuRemote API: Setting host: {host}")
        gazu.set_host(host)

        if DEBUG_MODE:
            print("GazuRemote API: Host set. Logging in...")
        gazu.log_in(email, password)

        user = gazu.client.get_current_user()
        full_name = user.get("full_name", "N/A")
        if DEBUG_MODE:
            print(f"GazuRemote API: Login successful: {full_name}")
        return True, full_name

    except (HostException, MethodNotAllowedException):
        if DEBUG_MODE:
            traceback.print_exc()
        return False, "The specified host is not reachable. Please check the URL."

    except AuthFailedException:
        if DEBUG_MODE:
            traceback.print_exc()
        return False, "Invalid email or password. Please try again."

    except Exception as e:
        traceback.print_exc()
        return False, f"An unexpected error occurred: {e}"


@_gazu_api_call
def get_all_open_user_projects():
    """Retrieves all open projects the currently logged-in user is a member of."""
    projects = gazu.project.all_open_projects()
    if DEBUG_MODE:
        print(f"GazuRemote API: Found {len(projects)} projects.")
    return projects


@_gazu_api_call
def get_logged_in_user():
    """Fetches the full user object for the currently logged-in user."""
    return gazu.client.get_current_user()


@_gazu_api_call
def get_project_by_id(project_id):
    """Retrieves all data for a single project."""
    return gazu.project.get_project(project_id)


@_gazu_api_call
def get_user_role():
    """Returns the role of the currently logged-in user."""
    user_data = gazu.client.get_current_user()
    role = user_data.get("role")
    if role:
        return role.capitalize()
    return "N/A"


@_gazu_api_call
def get_kitsu_base_url():
    """Constructs the base web URL for the Kitsu instance."""
    host = gazu.get_host()
    web_host = host.replace("/api", "")
    return web_host


@_gazu_api_call
def get_tasks_for_user_and_project(user, project_data, include_done=False):
    """
    Fetches all tasks for a given user and project.
    Filters by project_id from all tasks assigned to the user.
    """
    all_user_tasks = gazu.task.all_tasks_for_person(user)

    if include_done:
        done_tasks = gazu.task.all_done_tasks_for_person(user)
        all_user_tasks.extend(done_tasks)

    project_id = project_data["id"]
    project_tasks = [
        task for task in all_user_tasks
        if task["project_id"] == project_id
    ]
    return project_tasks


@_gazu_api_call
def get_task(task_id):
    """Retrieves a single task by its ID."""
    return gazu.task.get_task(task_id)


@_gazu_api_call
def get_task_statuses():
    """Retrieves all possible task statuses from the Gazu API."""
    return gazu.task.all_task_statuses()


@_gazu_api_call
def get_task_status_by_name(name):
    """Finds a specific task status by its name."""
    all_statuses = gazu.task.all_task_statuses()
    for status in all_statuses:
        if status["name"].lower() == name.lower():
            return status
    return None


@_gazu_api_call
def get_all_task_types_for_project(project):
    """Returns all task types for a given project."""
    return gazu.task.all_task_types_for_project(project["id"])


@_gazu_api_call
def publish_preview_to_task(task, task_status, comment, file_path):
    """Publishes a preview file for a given task with a comment."""
    params = {
        "task": task,
        "task_status": task_status,
        "comment": comment,
        "preview_file_path": file_path,
        "normalize_movie": True,
    }
    return gazu.task.publish_preview(**params)


@_gazu_api_call
def download_preview_file_thumbnail(preview_file_id, destination_path):
    """Downloads a thumbnail for a given preview file ID."""
    return gazu.files.download_preview_file_thumbnail(preview_file_id, destination_path)


@_gazu_api_call
def add_comment_to_task(task, task_status, comment):
    """Adds a comment (without file) to a task and updates its status."""
    return gazu.task.add_comment(task, task_status, comment)
