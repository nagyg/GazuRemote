import gazu
import os
import json
import functools
import traceback
from gazu.exception import HostException, MethodNotAllowedException, AuthFailedException

DEBUG_MODE = False

def set_debug_mode(enabled):
    """Sets the debug mode for the Gazu API module."""
    global DEBUG_MODE
    DEBUG_MODE = enabled
    if DEBUG_MODE:
        print("Nuke Gazu API: Debug mode enabled.")

def _gazu_api_call(func):
    """
    Decorator to handle common Gazu API call patterns.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        func_name = func.__name__
        try:
            if DEBUG_MODE:
                print(f"Nuke Gazu API: Executing {func_name}...")
            result = func(*args, **kwargs)
            if DEBUG_MODE:
                print(f"Nuke Gazu API: {func_name} executed successfully.")
            return True, result
        except Exception as e:
            print(f"Nuke Gazu API Error: An error occurred during {func_name}.")
            if DEBUG_MODE:
                traceback.print_exc()
            return False, str(e)
    return wrapper

def load_user_credentials():
    """
    Loads user credentials from ~/GazuRemote/user_config.json
    Returns (success, credentials_dict) tuple.
    """
    try:
        # Get user home directory
        home_dir = os.path.expanduser("~")
        config_path = os.path.join(home_dir, "GazuRemote", "user_config.json")
        
        if not os.path.exists(config_path):
            return False, f"Config file not found: {config_path}"
        
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        # Extract config_service section
        config_service = config.get('config_service', {})
        
        if not config_service:
            return False, "Missing 'config_service' section in config file"
        
        # Extract needed credentials (note: 'user' field instead of 'email')
        credentials = {
            'host': config_service.get('host'),
            'email': config_service.get('user'),  # Note: 'user' field maps to 'email'
            'password': config_service.get('password')
        }
        
        # Validate that all required fields are present
        for key, value in credentials.items():
            if not value:
                return False, f"Missing or empty '{key}' in config_service section"
        
        if DEBUG_MODE:
            print(f"Nuke Gazu API: Credentials loaded from {config_path}")
            print(f"  Host: {credentials['host']}")
            print(f"  Email: {credentials['email']}")
        
        return True, credentials
        
    except Exception as e:
        return False, f"Error loading credentials: {e}"

def auto_login():
    """
    Automatically logs into Gazu using stored credentials.
    Returns (success, message) tuple.
    """
    # Load credentials
    success, credentials = load_user_credentials()
    if not success:
        return False, f"Failed to load credentials: {credentials}"
    
    try:
        # Set host
        if DEBUG_MODE:
            print(f"Nuke Gazu API: Setting host: {credentials['host']}")
        gazu.set_host(credentials['host'])
        
        # Login
        if DEBUG_MODE:
            print("Nuke Gazu API: Logging in...")
        gazu.log_in(credentials['email'], credentials['password'])
        
        # Verify login
        user = gazu.client.get_current_user()
        full_name = user.get('full_name', 'N/A')
        
        if DEBUG_MODE:
            print(f"Nuke Gazu API: Login successful. User: {full_name}")
        
        return True, f"Logged in as {full_name}"
        
    except (HostException, MethodNotAllowedException) as e:
        return False, "Host not reachable or invalid"
    except AuthFailedException as e:
        return False, "Authentication failed - invalid credentials"
    except Exception as e:
        return False, f"Login error: {e}"

@_gazu_api_call
def get_task_by_id(task_id):
    """
    Retrieves full task data by task ID.
    """
    return gazu.task.get_task(task_id)

@_gazu_api_call
def get_entity_by_id(entity_id):
    """
    Retrieves entity (shot/asset) data by entity ID.
    """
    return gazu.asset.get_asset(entity_id)

def get_context_data():
    """
    Gets the current Gazu context (project and task IDs) from environment variables
    and fetches the corresponding data from the database.
    Returns (success, context_data) tuple.
    """
    try:
        project_id = os.environ.get('GAZU_PROJECT_ID')
        task_id = os.environ.get('GAZU_TASK_ID')
        
        if not project_id or not task_id:
            return False, "No Gazu context found in environment variables"
        
        # Auto-login if not already logged in
        try:
            # Test if we're already logged in
            gazu.client.get_current_user()
        except:
            login_success, login_msg = auto_login()
            if not login_success:
                return False, f"Auto-login failed: {login_msg}"
        
        # Fetch only task data - it contains all the info we need
        task_success, task_data = get_task_by_id(task_id)
        if not task_success:
            return False, f"Failed to fetch task data: {task_data}"
         
        # Extract data from task_data
        context = {
            # Full task data can be accessed via context['task']
            # 'task': task_data,
            'task_id': task_id,
            'project_id': project_id,
            'task_name': task_data.get('task_type', {}).get('name', 'Unknown'),
            'task_short_name': task_data.get('task_type', {}).get('short_name', None),
            'task_for_entity': task_data.get('task_type', {}).get('for_entity', None),
            'task_status': task_data.get('task_status', {}).get('name', 'Unknown'),
            'entity_type': task_data.get('entity_type', {}).get('name', 'Unknown'),
            'sequence_name': task_data.get('sequence', {}).get('name', None),
            'entity_name': task_data.get('entity', {}).get('name', 'Unknown'),
            'entity_data': task_data.get('entity', {}).get('data', {}),
            'entity_nb_frames': task_data.get('entity', {}).get('nb_frames', None),
            'entity_description': task_data.get('entity', {}).get('description', None),
            'project_name': task_data.get('project', {}).get('name', 'Unknown'),
            'project_mountpoint': task_data.get('project', {}).get('data', {}).get('mountpoint', None),
            
            # Episode name (not all project types have episodes)
            'episode_name': task_data.get('episode', {}).get('name', None) if task_data.get('episode') else None
        }
        
        if DEBUG_MODE:
            print("Nuke Gazu API: Context data retrieved successfully")
            print(f"  Project Mountpoint: {context['project_mountpoint']}")
            print(f"  Task Type Short Name: {context['task_short_name']}")
            print(f"  Task For Entity: {context['task_for_entity']}")
            print(f"  Entity Data: {context['entity_data']}")
            print(f"  Episode Name: {context['episode_name']}")
            print(f"  Entity Frames: {context['entity_nb_frames']}")

        return True, context
        
    except Exception as e:
        if DEBUG_MODE:
            traceback.print_exc()
        return False, f"Error getting context data: {e}"