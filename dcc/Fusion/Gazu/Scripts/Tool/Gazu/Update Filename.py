import sys
import os

def main():
    """
    Main entry point for "Update Filename" script (Tool context).
    Imports logic from shared SiteLib/Python library.
    Updates only the specific single tool involved.
    """
    try:
        from gazu_tools import filename_utils
        import importlib
        importlib.reload(filename_utils)
    except ImportError as e:
         print(f"ERROR: {e}. Check PYTHONPATH.")
         return

    comp = fusion.GetCurrentComp()
    if not comp:
        return

    # 1. Get Context
    ctx = filename_utils.get_gazu_context(comp)
    print(f"--- Updating Single Node (Gazu) ---")
    print(f"  Context Version: {ctx.get('Version')}")
    
    # 2. Find Target Tool (Run on specific tool)
    tool_to_update = None
    
    # Try getting 'tool' from global scope (standard for Fusion Tool Scripts)
    try:
        if 'tool' in globals():
            tool_to_update = tool
    except (NameError, KeyError):
        pass
        
    # If not found (e.g. ran from menu without selection context), use ActiveTool
    if not tool_to_update:
        tool_to_update = comp.ActiveTool
        
    if tool_to_update:
        print(f"  Target: {tool_to_update.Name}")
        # Call the single-node update function as required
        filename_utils.update_single_node(tool_to_update, ctx)
    else:
        print("  No tool selected or active.")

if __name__ == "__main__":
    main()
