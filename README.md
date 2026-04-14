# GazuRemote

A lightweight remote client for [Kitsu / Zou](https://www.cg-wire.com/kitsu) production tracking.  
Designed for artists working **outside the studio** over a VPN connection.

## What it does

- Authenticates against the Kitsu/Zou API over VPN
- Displays your assigned tasks (my tasks view)
- Lets you add comments / feedback directly to Kitsu
- Allows publishing preview files to Kitsu tasks
- Validates local mount point against the studio's project structure

## What it does NOT do

- Launch DCC applications
- Initialize projects
- Modify the project file structure

---

## Requirements

| Requirement | Notes |
|---|---|
| **VPN connection** | The user is responsible for establishing the VPN tunnel to the studio network |
| **Python 3.12** | Bundled locally – run `install.cmd` |
| **Local mount point** | The project folder must be synced / mapped on the client machine |

---

## Installation

### 1. Clone the repository

```cmd
git clone https://github.com/<your-account>/GazuRemote.git
cd GazuRemote
```

### 2. Install Python & dependencies

Run the installer script (Windows):

```cmd
install.cmd
```

The script will:
- Copy `Python312` from the sibling Gazu installation (if `WORKGROUP` env var is set), **or**
- Prompt you to install Python 3.12 manually into the `Python312/` subfolder
- Install all required packages from `requirements.txt`

### 3. Manual Python install (if needed)

1. Download Python 3.12 from https://www.python.org/downloads/
2. Install to `GazuRemote\Python312\` (use "Customize installation" → change path)
3. Run:
   ```cmd
   Python312\Scripts\pip install -r requirements.txt
   ```

---

## Running

```cmd
GazuRemote.cmd
```

Or directly:

```cmd
Python312\python.exe __main__.py
```

---

## Updating

```cmd
git pull
install.cmd
```

The `install.cmd` will also upgrade any outdated dependencies.

---

## Configuration

GazuRemote stores its configuration in `%USERPROFILE%\GazuRemote\user_config.json`.

⚠️ **Never commit this file** – it contains your credentials in plaintext.

### Mount Point Setup

| Field | Description |
|---|---|
| **Remote Mount Point** | Read from the Kitsu database (set by the project Admin). **Not editable.** |
| **Local Mount Point** | The root folder on your machine where the project is mapped (e.g. `Z:\Projects`). |

The local mount point must match the remote mount point's **folder structure**.  
Syncing the project files is the **user's responsibility** (e.g. using `rsync`, `rclone`, or a VPN-mapped network drive).

---

## Architecture

```
GazuRemote/
├── __main__.py          # Entry point
├── GazuRemote.cmd       # Windows launcher
├── install.cmd          # First-time setup
├── requirements.txt
├── images/              # App icons and logo
├── login/
│   ├── login_view.py    # Authentication + mount point validation
│   └── login_window.ui
├── main/
│   ├── main_view.py         # Main window (task list)
│   ├── main_window.ui
│   ├── remote_tasks_widget.py  # Task tree, publish, feedback
│   ├── publisher_dialog.py
│   └── publisher_dialog.ui
└── services/
    ├── gazu_api.py       # Kitsu/Zou API wrapper
    ├── config_service.py # Config & credentials
    └── ui_utils.py       # UI helpers & logging
```

---

## License

Internal studio tool. All rights reserved.
