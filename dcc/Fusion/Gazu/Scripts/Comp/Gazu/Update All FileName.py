import sys
import os

def main():
    """
    Main entry point for "Update Filename" script.
    Imports logic from shared SiteLib/Python library.
    """
    try:
        from gazu_tools import filename_utils
        import importlib
        importlib.reload(filename_utils)
    except ImportError as e:
         print(f"ERROR: {e}. Check PYTHONPATH.")
         return

    # Run the main logic
    comp = fusion.GetCurrentComp()
    filename_utils.update_all_nodes(comp)

if __name__ == "__main__":
    main()
