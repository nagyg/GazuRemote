"""Reload.py

Finds the nearest .gazu_context file, calls the Kitsu API synchronously,
writes the full context (raw data + aliases + path maps + comp settings)
to the composition, then opens Show.py to display the result.
"""
import os
import json


def get_comp():
    try:
        return comp
    except NameError:
        try:
            return fusion.GetCurrentComp()
        except NameError:
            print("Error: Could not access Fusion composition object.")
            return None


def find_context_ids(current_comp):
    """Traverse up from the comp file to find .gazu_context.
    Returns (project_id, task_id) or (None, None).
    """
    script_name = current_comp.GetAttrs().get('COMPS_FileName', '')
    if not script_name:
        print("Comp is not saved. Cannot find relative context file.")
        return None, None

    current_path = os.path.dirname(script_name)
    while True:
        context_file = os.path.join(current_path, '.gazu_context')
        if os.path.exists(context_file):
            try:
                with open(context_file, 'r') as f:
                    data = json.load(f)
                return data.get('project_id', ''), data.get('task_id', '')
            except Exception as e:
                print(f"ERROR reading context file: {e}")
                return None, None
        parent = os.path.dirname(current_path)
        if parent == current_path:
            break
        current_path = parent

    return None, None


def _update_comp_settings(current_comp, ctx):
    data = {}
    if isinstance(ctx.get('entity_data'), dict):
        data = ctx['entity_data'].copy()
        nested = data.pop('data', None)
        if isinstance(nested, dict):
            data.update(nested)

    fps = data.get('fps')
    if fps:
        try:
            current_comp.SetPrefs("Comp.FrameFormat.Rate", float(fps))
            print(f"Applied FPS: {fps}")
        except Exception as e:
            print(f"FPS error: {e}")

    res = data.get('resolution')
    if res and isinstance(res, str) and 'x' in res:
        try:
            w, h = res.lower().split('x')
            current_comp.SetPrefs("Comp.FrameFormat.Width",  int(w))
            current_comp.SetPrefs("Comp.FrameFormat.Height", int(h))
            print(f"Applied Resolution: {w}x{h}")
        except Exception as e:
            print(f"Resolution error: {e}")

    f_in, f_out = data.get('frame_in'), data.get('frame_out')
    if f_in is not None and f_out is not None:
        try:
            current_comp.SetAttrs({
                "COMPN_GlobalStart": int(f_in), "COMPN_GlobalEnd":   int(f_out),
                "COMPN_RenderStart": int(f_in), "COMPN_RenderEnd":   int(f_out),
            })
            print(f"Applied Frame Range: {f_in}-{f_out}")
        except Exception as e:
            print(f"Frame range error: {e}")


def _update_comp_data(current_comp, ctx):
    int_keys = {"frame_in", "frame_out", "entity_nb_frames"}

    aliases = {
        'project_name':    'Gazu.Project',
        'sequence_name':   'Gazu.Sequence',
        'episode_name':    'Gazu.Episode',
        'task_short_name': 'Gazu.Task',
    }
    for src, dst in aliases.items():
        if ctx.get(src):
            current_comp.SetData(dst, ctx[src])

    if 'entity_name' in ctx:
        current_comp.SetData("Gazu.Entity", ctx['entity_name'])
        if ctx.get('entity_type') == 'Shot':
            current_comp.SetData("Gazu.Shot", ctx['entity_name'])
        elif ctx.get('entity_type') == 'Asset':
            current_comp.SetData("Gazu.Asset", ctx['entity_name'])

    # task_id / project_id are accessible via comp:GetData("Gazu.Context.task_id") — no flat alias needed
    excluded = {"entity_description", "entity_data", "data", "task_id", "project_id"}
    for key, val in ctx.items():
        if key in excluded or val is None:
            continue
        if key in int_keys:
            try:
                val = str(int(float(val)))
            except (ValueError, TypeError):
                pass
        current_comp.SetData(f"Gazu.{key}", val)

    if isinstance(ctx.get('entity_data'), dict):
        flat = ctx['entity_data'].copy()
        nested = flat.pop('data', None)
        if isinstance(nested, dict):
            flat.update(nested)
        for key, val in flat.items():
            if val is None:
                continue
            clean = str(key).replace(" ", "_").replace("-", "_")
            if clean in int_keys:
                try:
                    val = str(int(float(val)))
                except (ValueError, TypeError):
                    pass
            current_comp.SetData(f"Gazu.{clean}", val)

    print("Comp data updated.")


def _update_path_maps(current_comp, ctx):
    mp = ctx.get('project_mountpoint')
    pn = ctx.get('project_name')
    updates = {}
    if mp:
        updates['project_mountpoint'] = mp
    if mp and pn:
        updates['GazuProject'] = os.path.join(mp, pn)
        parts = [mp, pn, "shots"]
        for k in ('episode_name', 'sequence_name', 'entity_name'):
            if ctx.get(k):
                parts.append(ctx[k])
        updates['GazuShotPath'] = os.path.join(*parts)
    for k, v in updates.items():
        try:
            current_comp.SetPrefs(f"Comp.Paths.Map.{k}:", v)
        except Exception as e:
            print(f"Path map error {k}: {e}")
    if updates:
        print("Path maps updated.")


if __name__ == "__main__":
    print("Gazu - Reloading context...")

    current_comp = get_comp()
    if not current_comp:
        print("Error: No active Fusion composition.")
    else:
        project_id, task_id = find_context_ids(current_comp)
        if not project_id or not task_id:
            print("Could not load context.")
        else:
            print(f"Gazu context found - project={project_id}, task={task_id}")

            # Set env vars for this scope (used by gazu_api.get_context_data below)
            os.environ['GAZU_PROJECT_ID'] = project_id
            os.environ['GAZU_TASK_ID']    = task_id

            # Call Kitsu API synchronously
            api_ok = False
            try:
                import gazu_api
                ok, ctx = gazu_api.get_context_data()
                if ok and ctx:
                    print("Gazu API: context loaded.")
                    current_comp.SetData("Gazu.Context", ctx)
                    _update_comp_data(current_comp, ctx)
                    _update_path_maps(current_comp, ctx)
                    _update_comp_settings(current_comp, ctx)
                    api_ok = True
                else:
                    print(f"Gazu API error: {ctx}")
            except ImportError:
                print("WARNING: gazu_api not available in PYTHONPATH.")

            # Always open Show.py (shows fresh data if api_ok, cached otherwise)
            try:
                fusion.RunScript("Scripts:Comp/Gazu/Context/Show.py")
            except Exception as e:
                print(f"Error launching Show.py: {e}")
