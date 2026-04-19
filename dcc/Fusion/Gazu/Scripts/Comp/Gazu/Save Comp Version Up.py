import os
import re
import sys

# Get current comp
try:
    comp = fusion.GetCurrentComp()
except NameError:
    comp = None

def get_next_version_path(filepath):
    """
    Parses the filepath for a version number (v001), increments it,
    and returns a path that does not exist yet (skipping existing versions).
    """
    dirname, basename = os.path.split(filepath)
    name, ext = os.path.splitext(basename)
    
    # Regex to find the LAST occurrence of v followed by digits
    # Examples: shot_v001.comp, shot_v1.comp
    match = re.search(r'[vV](\d+)(?!.*[vV]\d+)', name)
    
    if not match:
        return None, "Could not find version number pattern (e.g. v001) in filename."

    prefix = name[:match.start(1)] # Up to the digits
    version_str = match.group(1)   # The digits
    suffix = name[match.end(1):]   # After the digits
    
    padding = len(version_str)
    current_version = int(version_str)
    
    # Loop to find the next free version
    next_version = current_version + 1
    
    while True:
        new_version_str = f"{next_version:0{padding}d}"
        new_name = f"{prefix}{new_version_str}{suffix}{ext}"
        new_path = os.path.join(dirname, new_name)
        
        if not os.path.exists(new_path):
            return new_path, None
        
        # If file exists, we can either skip it (safe increment) 
        # or prompt (strict increment). 
        # Nuke's "Version Up" usually just goes to the next number `current + 1`.
        # If `current + 1` exists, Nuke warns you.
        # However, "Smart Save" features often find the next FREE slot.
        # Let's stick to strict `current + 1` first as it's more predictable, 
        # OR `current + 1` and fail if exists.
        # User said "updates on save as".
        
        # Let's check max iterations to avoid infinite loop
        if next_version - current_version > 100:
            return None, "Too many existing versions found."
            
        # For safety/convenience, let's find the next AVAILABLE version.
        next_version += 1

def main():
    if not comp:
        print("No composition found.")
        return

    filepath = comp.GetAttrs().get('COMPS_FileName', '')
    
    if not filepath:
        print("Composition has not been saved yet. Please save manually first.")
        # Fusion equivalent of message box?
        comp.AskUser("Error", {
            "Links": { "Label": { "Add": { "Text": "Please save the file manually first." } }, "OK": { "Add": { "Button": "OK" } } }
        })
        return
        
    new_filepath, error = get_next_version_path(filepath)
    
    if error:
        print(error)
        comp.AskUser("Error", {
            "Links": { "Label": { "Add": { "Text": error } }, "OK": { "Add": { "Button": "OK" } } }
        })
        return

    print(f"Version Up: {filepath} -> {new_filepath}")
    
    # Confirm
    # Note: AskUser structure is complex, this is simplified.
    # We'll just save it.
    
    try:
        # 1. Save to new path FIRST (so Comp has new name/version)
        # This is strictly required because `get_gazu_context` parses the CURRENT comp name.
        comp.Save(new_filepath)
        print(f"Saved (Initial): {new_filepath}")
        
        # 2. Update filenames (now using the new version from Comp name)
        try:
            from gazu_tools import filename_utils
            import importlib
            importlib.reload(filename_utils)
            print("Updating nodes for new version...")
            filename_utils.update_all_nodes(comp)
        except ImportError:
            print("Warning: Could not run Update Filename automatically. Gazu tools missing.")

        # 3. Save AGAIN to persist the updated node paths
        comp.Save(new_filepath)
        print(f"Saved (Final): {new_filepath}")

    except Exception as e:
        print(f"Error saving file: {e}")

if __name__ == "__main__":
    main()
