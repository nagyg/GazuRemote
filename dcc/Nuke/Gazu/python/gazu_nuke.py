import nuke
import os
import json

# Import our Nuke-specific Gazu API
try:
    import gazu_api
except ImportError:
    print("WARNING: Could not import gazu_api module")
    gazu_api = None

def find_and_load_context():
    """
    Traverses up from the current script's directory to find and load '.gazu_context'.
    Sets the context as environment variables for the current Nuke session.
    """
    # Start searching from the directory of the current Nuke script, if it exists.
    # Otherwise, fall back to the current working directory.
    try:
        script_name = nuke.root().name()
        if script_name and script_name != "Root":  # Check if a real script is loaded
            start_path = os.path.dirname(script_name)
        else:
            start_path = os.getcwd()
    except RuntimeError:  # Happens if the script is unsaved
        start_path = os.getcwd()

    # Additional fallback: if start_path is empty, use current working directory
    if not start_path:
        start_path = os.getcwd()

    current_path = start_path
    
    # Traverse up until the filesystem root OR until we find a context file
    while True:
        context_file = os.path.join(current_path, '.gazu_context')
        
        if os.path.exists(context_file):
            # print(f"Gazu context file found at: {context_file}")
            try:
                with open(context_file, 'r') as f:
                    context_data = json.load(f)
                
                # Set environment variables for this session
                os.environ['GAZU_PROJECT_ID'] = context_data.get('project_id', '')
                os.environ['GAZU_TASK_ID'] = context_data.get('task_id', '')
                
                print("Gazu context loaded successfully:")
                print(f"  Project ID: {os.environ['GAZU_PROJECT_ID']}")
                print(f"  Task ID: {os.environ['GAZU_TASK_ID']}")
                
                # Fetch additional data from Gazu database
                if gazu_api:
                    fetch_gazu_data()
                
                return True  # Exit immediately after successful loading
            except Exception as e:
                print(f"ERROR reading context file: {e}")
                # Continue searching in parent directories if this file was corrupted

        # Move up one directory
        parent_path = os.path.dirname(current_path)
        if parent_path == current_path:  # Reached filesystem root
            break
        current_path = parent_path
        
    print("No Gazu context found. Running in standalone mode.")
    return False

def fetch_gazu_data():
    """
    Fetches additional task and project data from the Gazu database
    using the context IDs from environment variables.
    """
    if not gazu_api:
        print("Gazu API not available - skipping data fetch")
        return
    
    success, context_data = gazu_api.get_context_data()
    
    if success:
        # Store the full context data globally for other scripts to use
        nuke.gazu_context = context_data
    else:
        print(f"Failed to fetch Gazu data: {context_data}")

def show_environment_info():
    """
    Shows a dialog with current environment information and Gazu context.
    """
    # Collect environment information
    info_lines = []
    info_lines.append("=" * 60)  # Longer separator line
    info_lines.append("GAZU ENVIRONMENT INFO")
    info_lines.append("=" * 60)
    info_lines.append("")
    
    # Gazu Context
    info_lines.append("GAZU CONTEXT:")
    project_id = os.environ.get('GAZU_PROJECT_ID')
    task_id = os.environ.get('GAZU_TASK_ID')
    
    if project_id and task_id:
        info_lines.append(f"  Project ID: {project_id}")
        info_lines.append(f"  Task ID: {task_id}")
        info_lines.append("  Status: CONTEXT LOADED ✓")
        
        # Add database info if available
        if hasattr(nuke, 'gazu_context'):
            ctx = nuke.gazu_context
            info_lines.append("")
            info_lines.append("DATABASE INFO:")
            info_lines.append(f"  Project Name: {ctx['project_name']}")
            info_lines.append(f"  Entity Name: {ctx['entity_name']}")
            info_lines.append(f"  Task Status: {ctx.get('task_status', 'Unknown')}")
    else:
        info_lines.append("  Status: NO CONTEXT FOUND ✗")
    
    info_lines.append("")
    info_lines.append("=" * 60)
    
    # Current Nuke Script Info
    info_lines.append("CURRENT SCRIPT INFO:")
    try:
        script_name = nuke.root().name()
        if script_name and script_name != "Root":
            info_lines.append(f"  Script: {script_name}")
            info_lines.append(f"  Directory: {os.path.dirname(script_name)}")
        else:
            info_lines.append("  Script: UNSAVED/NEW")
            info_lines.append(f"  Working Dir: {os.getcwd()}")
    except:
        info_lines.append("  Script: ERROR READING")
    
    info_lines.append("=" * 60)
    
    # Create the info text
    info_text = "\n".join(info_lines)
    
    # Show in Nuke's message dialog
    nuke.message(info_text)
    
    # Also print to console for copy-paste
    print("\n" + info_text)

def reload_context():
    """
    Manually reload the Gazu context from the current location.
    """
    result = find_and_load_context()
    if result:
        nuke.message("Gazu context reloaded successfully!\n\nCheck the Script Editor for details.")
    else:
        nuke.message("No Gazu context found in the current location.\n\nMake sure your script is saved in a task folder.")

def show_raw_task_data():
    """
    Shows the raw task data from Gazu database.
    """
    if not gazu_api:
        nuke.message("Gazu API not available!")
        return
    
    project_id = os.environ.get('GAZU_PROJECT_ID')
    task_id = os.environ.get('GAZU_TASK_ID')
    
    if not project_id or not task_id:
        nuke.message("No Gazu context found!\n\nLoad a script from a task folder first.")
        return
    
    print("=" * 60)
    print("FETCHING RAW TASK DATA...")
    print("=" * 60)
    
    # Auto-login if needed
    try:
        gazu.client.get_current_user()
    except:
        success, msg = gazu_api.auto_login()
        if not success:
            nuke.message(f"Auto-login failed: {msg}")
            return
    
    # Fetch raw task data
    task_success, task_data = gazu_api.get_task_by_id(task_id)
    
    if task_success:
        import pprint
        print("RAW TASK DATA:")
        print("=" * 60)
        pprint.pprint(task_data)
        print("=" * 60)
        
        nuke.message("Raw task data printed to Script Editor console.\n\nCheck the Script Editor for details.")
    else:
        error_msg = f"Failed to fetch task data: {task_data}"
        print(error_msg)
        nuke.message(error_msg)

def set_knob_enabled(node, knob_name, enabled):
    """
    Enables or disables the specified knob on the node.
    Used by override checkboxes.
    """
    if knob_name in node.knobs():
        node[knob_name].setEnabled(enabled)

def add_param_with_override(node, knob, name, value):
    """Helper to add a knob with a disabled state and an override checkbox."""
    knob.setValue(value)
    knob.setEnabled(False)
    node.addKnob(knob)
    override_knob = nuke.Boolean_Knob(f"{name}_override", "")
    override_knob.setFlag(nuke.ENDLINE)
    override_knob.setTooltip("Enable to edit this parameter")
    node.addKnob(override_knob)

def add_gazu_knobs_to_node(node, ctx):
    """
    Adds all Gazu-related knobs to the given node, using the provided context.
    Each parameter gets an 'Override' Boolean_Knob (checkbox) to enable editing.
    The checkbox is placed at the end of the row and toggles the enabled state via a nuke expression.
    """
    # Project Information
    add_param_with_override(node, nuke.String_Knob("gazu_project_name", "Project Name"), "gazu_project_name", ctx['project_name'])
    add_param_with_override(node, nuke.String_Knob("gazu_project_id", "Project ID"), "gazu_project_id", ctx['project_id'])
    add_param_with_override(node, nuke.String_Knob("gazu_task_id", "Task ID"), "gazu_task_id", ctx['task_id'])

    if ctx.get('project_mountpoint'):
        # Replace backslashes with forward slashes for Nuke compatibility
        mountpoint = ctx['project_mountpoint'].replace('\\', '/')
        add_param_with_override(node, nuke.String_Knob("gazu_project_mountpoint", "Project Mountpoint"), "gazu_project_mountpoint", mountpoint)

    add_param_with_override(node, nuke.String_Knob("gazu_task_name", "Task Type"), "gazu_task_name", ctx['task_name'])

    if ctx.get('task_short_name'):
        add_param_with_override(node, nuke.String_Knob("gazu_task_short_name", "Task Short Name"), "gazu_task_short_name", ctx['task_short_name'])

    if ctx.get('episode_name'):
        add_param_with_override(node, nuke.String_Knob("gazu_episode_name", "Episode"), "gazu_episode_name", ctx['episode_name'])

    if ctx.get('sequence_name'):
        add_param_with_override(node, nuke.String_Knob("gazu_sequence_name", "Sequence"), "gazu_sequence_name", ctx['sequence_name'])

    entity_data_divider = nuke.Text_Knob("entity_data_divider", "Entity Data:")
    node.addKnob(entity_data_divider)

    add_param_with_override(node, nuke.String_Knob("gazu_entity_name", "Entity"), "gazu_entity_name", ctx['entity_name'])
    add_param_with_override(node, nuke.String_Knob("gazu_entity_type", "Type"), "gazu_entity_type", ctx['entity_type'])

    if ctx.get('entity_nb_frames'):
        add_param_with_override(node, nuke.Int_Knob("gazu_entity_frames", "Frames"), "gazu_entity_frames", ctx['entity_nb_frames'])

    # Process main entity data keys first (like frame_in, frame_out)
    if ctx.get('entity_data'):
        # Safely get the nested 'data' dictionary
        entity_metadata = ctx['entity_data'].get('data', {})

        # Combine keys from entity_data and its nested 'data' dict
        # We use a set to avoid duplicating keys if they exist in both places
        all_keys = set(ctx['entity_data'].keys()) | set(entity_metadata.keys())
        
        # We don't want to process the 'data' dictionary itself as a knob
        if 'data' in all_keys:
            all_keys.remove('data')

        for key in sorted(list(all_keys)):
            # Prioritize value from the nested 'data' dict, then from entity_data
            value = entity_metadata.get(key, ctx['entity_data'].get(key))

            if value is None:
                continue
            
            # --- Special handling for resolution strings ---
            if key in ('resolution', 'ud_resolution') and isinstance(value, str) and 'x' in value:
                try:
                    parts = value.split('x')
                    width = int(parts[0])
                    height = int(parts[1])

                    # Create X (width) knob
                    x_param_name = f"entity_{key}_x"
                    x_param_label = f"{key.replace('_', ' ').title()} X"
                    x_knob = nuke.Int_Knob(x_param_name, x_param_label)
                    add_param_with_override(node, x_knob, x_param_name, width)

                    # Create Y (height) knob
                    y_param_name = f"entity_{key}_y"
                    y_param_label = f"{key.replace('_', ' ').title()} Y"
                    y_knob = nuke.Int_Knob(y_param_name, y_param_label)
                    add_param_with_override(node, y_knob, y_param_name, height)
                    
                    continue # Skip default processing for this key
                except (ValueError, IndexError):
                    print(f"Gazu WARNING: Could not parse '{key}': {value}. Creating as string.")
                    # Fallback to default string processing if parsing fails
            
            param_name = f"entity_{key}"
            param_label = f"{key.replace('_', ' ').title()}"
            
            if isinstance(value, bool):
                knob = nuke.Boolean_Knob(param_name, param_label)
            elif isinstance(value, int):
                knob = nuke.Int_Knob(param_name, param_label)
            elif isinstance(value, float):
                knob = nuke.Double_Knob(param_name, param_label)
            elif isinstance(value, (list, dict)):
                knob = nuke.Multiline_Eval_String_Knob(param_name, param_label)
                value = str(value)
            else:
                knob = nuke.String_Knob(param_name, param_label)
                value = str(value)
            add_param_with_override(node, knob, param_name, value)

    # --- Add Path Knobs ---
    paths_divider = nuke.Text_Knob("paths_divider", "Paths:")
    node.addKnob(paths_divider)

    mountpoint = ctx.get('project_mountpoint', '').replace('\\', '/')
    project_name = ctx.get('project_name', '')
    
    # Only proceed if we have a mountpoint and project name
    if mountpoint and project_name:
        project_path = f"{mountpoint}/{project_name}"
        shots_path = f"{project_path}/shots"
        
        shot_path_parts = [shots_path]
        # Add episode if it exists and is not None
        if ctx.get('episode_name'):
            shot_path_parts.append(ctx['episode_name'])
        if ctx.get('sequence_name'):
            shot_path_parts.append(ctx['sequence_name'])
        if ctx.get('entity_name'):
            shot_path_parts.append(ctx['entity_name'])
        
        shot_path = "/".join(p for p in shot_path_parts if p)

        task_path = ""
        if shot_path and ctx.get('task_short_name'):
            task_path = f"{shot_path}/{ctx['task_short_name']}"

        # Add knobs only if the paths could be constructed
        add_param_with_override(node, nuke.String_Knob("gazu_shots_path", "Shots"), "gazu_shots_path", shots_path)
        if len(shot_path_parts) > 1:
            add_param_with_override(node, nuke.String_Knob("gazu_shot_path", "Shot"), "gazu_shot_path", shot_path)
        if task_path:
            add_param_with_override(node, nuke.String_Knob("gazu_task_path", "Task"), "gazu_task_path", task_path)
            
    # --- Additional Info ---
    divider_knob = nuke.Text_Knob("gazu_divider", "")
    node.addKnob(divider_knob)

    # Add entity description if available
    if ctx.get('entity_description'):
        add_param_with_override(
            node,
            nuke.Multiline_Eval_String_Knob("gazu_entity_description", "Description"),
            "gazu_entity_description",
            ctx['entity_description']
        )

    import datetime
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    add_param_with_override(node, nuke.String_Knob("gazu_timestamp", "Created"), "gazu_timestamp", timestamp)

    # Finalize node appearance
    node['tile_color'].setValue(0x4CAF50FF)

    label_parts = [
        f"Project: {ctx['project_name']}",
    ]
    if ctx.get('episode_name'):
        label_parts.append(f"Episode: {ctx['episode_name']}")
    label_parts.append(f"Entity: {ctx['entity_name']}")
    if ctx.get('entity_nb_frames'):
        label_parts.append(f"Frames: {ctx['entity_nb_frames']}")
    label_text = "\n".join(label_parts)
    node['label'].setValue(label_text)

def refresh_gazu_node():
    """
    Refreshes the GazuData node: removes all custom knobs except the tab and refresh button,
    reloads context silently, and repopulates the node with fresh data.
    """
    node = nuke.thisNode()
    keep_names = {"gazu_tab", "gazu_refresh"}
    knobs_to_remove = [
        k for k in node.allKnobs()
        if (k.name().startswith("gazu_") or k.name().startswith("entity_") or k.name().endswith("_divider"))
        and k.name() not in keep_names
    ]
    for knob in knobs_to_remove:
        node.removeKnob(knob)

    find_and_load_context()

    if not gazu_api:
        return

    project_id = os.environ.get('GAZU_PROJECT_ID')
    task_id = os.environ.get('GAZU_TASK_ID')
    if not project_id or not task_id:
        return

    success, ctx = gazu_api.get_context_data()
    if not success:
        return

    nuke.gazu_context = ctx

    add_gazu_knobs_to_node(node, ctx)

def create_gazu_node():
    """
    Creates a custom Gazu node with task data filled in as parameters.
    """
    if not gazu_api:
        nuke.message("Gazu API not available!")
        return

    project_id = os.environ.get('GAZU_PROJECT_ID')
    task_id = os.environ.get('GAZU_TASK_ID')

    if not project_id or not task_id:
        nuke.message("No Gazu context found!\n\nLoad a script from a task folder first.")
        return

    print("Refreshing Gazu context data...")
    success, context_data = gazu_api.get_context_data()
    if not success:
        nuke.message(f"Failed to fetch Gazu data: {context_data}")
        return

    nuke.gazu_context = context_data
    ctx = nuke.gazu_context

    gazu_node = nuke.createNode("NoOp", inpanel=False)
    gazu_node.setName("GazuData")
    tab_knob = nuke.Tab_Knob("gazu_tab", "Gazu Data")
    gazu_node.addKnob(tab_knob)
    refresh_knob = nuke.PyScript_Knob("gazu_refresh", "Refresh")
    refresh_knob.setCommand("gazu_nuke.refresh_gazu_node()")
    gazu_node.addKnob(refresh_knob)

    add_gazu_knobs_to_node(gazu_node, ctx)

    print(f"Gazu Data node created with fresh data: {ctx['entity_name']} - {ctx['task_name']}")

    return gazu_node

def gazu_knob_changed():
    """
    Callback: Handles override checkboxes for GazuData node knobs.
    """
    knob = nuke.thisKnob()
    node = nuke.thisNode()
    name = knob.name()
    if name.endswith("_override"):
        param_name = name.replace("_override", "")
        if param_name in node.knobs():
            node[param_name].setEnabled(knob.value())

# Register callback for all NoOp nodes (or only GazuData if you want)
nuke.addKnobChanged(gazu_knob_changed, nodeClass='NoOp')

# Also try to load context when a script is opened
def on_script_load():
    """Called when a script is loaded."""
    find_and_load_context()

# Hook into Nuke's script load event
nuke.addOnScriptLoad(on_script_load)

# Add menu items
gazu_menu = nuke.menu('Nuke').addMenu('Gazu')
gazu_menu.addSeparator()
gazu_menu.addCommand('Info/Environment', show_environment_info)
gazu_menu.addCommand('Info/Raw Task Data', show_raw_task_data)
gazu_menu.addSeparator()
gazu_menu.addCommand('Reload Context', reload_context)
gazu_menu.addCommand('Create Gazu Data Node', create_gazu_node)

