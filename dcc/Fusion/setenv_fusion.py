import os
import sys
import shutil

def escape_lua_path(path):
    """
    Escapes backslashes for Lua strings.
    E.g., "C:\\Work" -> "C:\\\\Work"
    """
    if not path:
        return ""
    # Python's replace handles the escaping correctly
    return path.replace("\\", "\\\\")

def update_prefs(source_path, dest_path, updates):
    """
    Copies source to dest, updating lines matching keys in updates dictionary.
    """
    # Create destination directory if it doesn't exist
    dest_dir = os.path.dirname(dest_path)
    if not os.path.exists(dest_dir):
        try:
            os.makedirs(dest_dir)
            # print(f"Created directory: {dest_dir}")
        except OSError as e:
            print(f"Error creating directory {dest_dir}: {e}")
            return False

    # Copy file if source exists
    if os.path.exists(source_path):
        try:
            shutil.copy2(source_path, dest_path)
            # print(f"Copied template from: {source_path}")
        except IOError as e:
            print(f"Error copying file: {e}")
            return False
    else:
        print(f"Source file not found: {source_path}")
        # If dest exists, we might still want to update it, so we continue
        if not os.path.exists(dest_path):
            return False

    # Read the file content
    try:
        with open(dest_path, 'r') as f:
            lines = f.readlines()
    except IOError as e:
        print(f"Error reading {dest_path}: {e}")
        return False

    # Process updates
    new_lines = []
    for line in lines:
        updated = False
        for key, value in updates.items():
            # Look for pattern: ["KEY"] = "..."
            # Using a simple string search for the key structure used in workgroup.prefs
            search_str = f'["{key}"]'
            if search_str in line and "=" in line:
                # Construct new line: ["KEY"] = "ESCAPED_PATH",
                # Preserving indentation (tabs or spaces) is nice but strict replacement is safer
                # We assume standard formatting: \t\t\t\t["KEY"] = "VALUE",
                
                # Get indentation
                indent = line.split('[')[0]
                
                escaped_val = escape_lua_path(value)
                new_line = f'{indent}["{key}"] = "{escaped_val}",\n'
                new_lines.append(new_line)
                # print(f"Updated {key} -> {value}")
                updated = True
                break
        
        if not updated:
            new_lines.append(line)

    # Write back changes
    try:
        with open(dest_path, 'w') as f:
            f.writelines(new_lines)
        # print(f"Successfully updated: {dest_path}")
        return True
    except IOError as e:
        print(f"Error writing to {dest_path}: {e}")
        return False

if __name__ == "__main__":
    # fast and loose argument parsing
    # Usage: python update_fusion_prefs.py "source_file" "dest_file" "Key1=Value1" "Key2=Value2" ...
    
    if len(sys.argv) < 3:
        print("Usage: python update_fusion_prefs.py <source> <dest> [key=value ...]")
        sys.exit(1)

    source = sys.argv[1]
    dest = sys.argv[2]
    
    updates = {}
    for arg in sys.argv[3:]:
        if '=' in arg:
            key, val = arg.split('=', 1)
            updates[key] = val
    
    success = update_prefs(source, dest, updates)
    if not success:
        sys.exit(1)
