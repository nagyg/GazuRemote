import re

def get_gazu_context(comp):
    """
    Retrieves Gazu context data from the composition.
    Returns a dictionary of keys (Project, Shot, Version, etc.)
    """
    if not comp:
        return {}
        
    gazu_context = {}
    
    # 1. Fetch from 'Gazu' Comp Data
    raw_gazu = comp.GetData("Gazu")
    if raw_gazu and isinstance(raw_gazu, dict):
         gazu_context.update(raw_gazu)
    else:
        # Fallback manual fetch for safety
        keys = ["Project", "Sequence", "Shot", "Entity", "Asset", "Episode", 
                "Task", "TaskType", "frame_in", "frame_out"]
        for k in keys:
            val = comp.GetData(f"Gazu.{k}")
            if val is not None:
                gazu_context[k] = val
                
    # 2. Extract Version from Comp Name if not already set or override it
    # Format: Film_SQ01_SH010_comp_v001
    comp_name = comp.GetAttrs("COMPS_Name")
    match = re.search(r"(_v|v)(\d+)", comp_name, re.IGNORECASE)
    if match:
         version_str = f"v{match.group(2)}"
         gazu_context["Version"] = version_str
         gazu_context["version"] = version_str
    elif "Version" not in gazu_context:
         gazu_context["Version"] = "v001"
         gazu_context["version"] = "v001"

    return gazu_context

def update_single_node(node, context_data):
    """
    Updates the 'Clip' input of a Saver or Loader node based on 'GazuFilename',
    or the 'LUTFile' input of a FileLUT node based on 'GazuLUTName'.
    """
    print(f"Processing Node: {node.Name}")

    # Determine pattern and target input based on node type
    pattern = None
    target_input = None

    # FileLUT node
    lut_pattern = node.GetInput("GazuLUTFile")
    if lut_pattern is not None and lut_pattern != "":
        pattern = lut_pattern
        target_input = "LUTFile"

    # Saver / Loader node
    if pattern is None:
        pattern = node.GetInput("GazuFilename")
        if pattern is None:
            pattern = node.GetInput("UserGazuFilename")
        if pattern is not None and pattern != "":
            target_input = "Clip"
        else:
            pattern = None

    # Check if pattern is valid
    if not pattern:
        print(f"  [SKIP] No Gazu pattern input found or empty.")
        return False

    # Replace placeholders
    result_path = pattern
    for key, val in context_data.items():
        placeholder = "{" + key + "}"
        if placeholder in result_path:
            result_path = result_path.replace(placeholder, str(val))

    # Check for unresolved tokens
    if re.search(r"\{[a-zA-Z0-9_]+\}", result_path):
        print(f"  [WARN] Unresolved tokens in: {result_path}")

    print(f"  Result: {result_path}")
    node.SetInput(target_input, result_path)
    return True

def update_all_nodes(comp):
    """
    Finds all Saver and Loader nodes in the comp and updates them.
    """
    if not comp:
        return

    print("--- Updating All Savers, Loaders and FileLUTs (Gazu) ---")
    ctx = get_gazu_context(comp)
    print(f"  Context Version: {ctx.get('Version')}")

    # Get Savers, Loaders and FileLUTs
    savers = comp.GetToolList(False, "Saver") or {}
    loaders = comp.GetToolList(False, "Loader") or {}
    fileluts = comp.GetToolList(False, "FileLUT") or {}

    # Combine lists of values instead of merging dicts (which might have colliding keys)
    all_nodes = list(savers.values()) + list(loaders.values()) + list(fileluts.values())

    if not all_nodes:
        print("  No Savers, Loaders or FileLUTs found.")
        return

    count = 0
    for node in all_nodes:
        if update_single_node(node, ctx):
            count += 1
    
    print(f"--- Updated {count} Nodes ---")
