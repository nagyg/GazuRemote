# GazuRemote

A lightweight remote client for [Kitsu / Zou](https://www.cg-wire.com/kitsu) production tracking.  
Designed for artists working **outside the studio** over a VPN connection.

## What it does

- Authenticates against the Kitsu/Zou API over VPN
- Displays your assigned tasks (my tasks view)
- Lets you add comments / feedback directly to Kitsu
- Allows publishing preview files to Kitsu tasks
- Validates local mount point against the studio's project structure
- Browses local task folders (directory tree + file list)
- Opens DCC files directly from the file browser (Fusion supported)

## DCC Launcher

GazuRemote supports opening DCC files directly from the task file browser by double-clicking a file.

| DCC | Extensions | Status |
|---|---|---|
| **Fusion** | `.comp` | ✅ Implemented – `dcc/Fusion/open_fusion.cmd` |
| **Nuke** | `.nk` | ✅ Implemented – `dcc/Nuke/open_nuke.cmd` |
| Houdini | `.hip`, `.hiplc`, `.hipnc` | 🔲 Not implemented |

The DCC executable paths are configurable via **Settings** (gear icon in the main window).  
DCC processes are launched in the background (no separate console window).

---

## What it does NOT do

- Initialize projects
- Modify the project file structure

---

## Requirements

| Requirement | Notes |
|---|---|
| **VPN connection** | The user is responsible for establishing the VPN tunnel to the studio network |
| **Windows 10/11** | 64-bit. Python 3.12 is bundled – no separate install needed |
| **Local mount point** | The project folder must be synced / mapped on the client machine |

---

## Installation

### 0. Install Git for Windows

Git is required to clone and update the repository.  
Download and install it from: https://git-scm.com/download/win

> ⚠️ **Important:** Install GazuRemote in a folder where you have full read/write access (e.g. `%USERPROFILE%\GazuRemote` or `C:\GazuRemote`).  
> **Do not install** under `C:\Program Files\` — standard users cannot write there, and the application will fail on startup.

### 1. Clone the repository

Navigate to the folder where you want to install GazuRemote, then clone:

```cmd
cd %USERPROFILE%\Downloads
git clone https://github.com/nagyg/GazuRemote.git
```

### 2. Enter the folder

```cmd
cd GazuRemote
```

### 3. Run the installer

```cmd
install.cmd
```

The script will:
- Extract the bundled `Python312.zip` (Python 3.12.10 embeddable + pip)
- Install desktop UI dependencies (`PySide6`) from `requirements.txt`
- Extract the bundled `Python312\Gazu.zip` → `Python312\Gazu\` (Kitsu API stack: `gazu`, `requests`, `socketio`, `pywin32`, etc.)

No separate Python installation required.

---

## Running

Double-click **`GazuRemote.exe`** or run from the command line:

```cmd
GazuRemote.exe
```

> **Debug / console output:** use `GazuRemote.cmd` instead — it runs the app via Python directly and keeps the console window open.

---

## Updating

Double-click **`update.cmd`** or run from the command line:

```cmd
update.cmd
```

This will pull the latest `master` branch from GitHub.  
Afterwards run `install.cmd` if dependencies changed.

> **Note:** `update.cmd` requires a `git clone` installation. If you downloaded GazuRemote as a ZIP, the script will guide you through migrating to a proper clone.

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
├── __main__.py                  # Entry point
├── GazuRemote.exe               # Main launcher (no console)
├── GazuRemote.cmd               # Debug launcher (console output)
├── install.cmd                  # First-time setup
├── update.cmd                   # git pull latest master (with ZIP-install guard)
├── Python312.zip                # Bundled Python 3.12.10 embeddable + pip
├── requirements.txt             # PySide6 only (Kitsu API stack bundled separately)
├── requirements_dcc.txt         # Gazu only for DCC
├── images/                      # App icons and logo
├── Python312/                   # Extracted at install time (gitignored)
│   ├── python.exe               # Python 3.12.10
│   ├── Lib/site-packages/       # PySide6 and other desktop deps
│   └── Gazu/                    # Extracted at install time (gitignored)
│       ├── Lib/                 # gazu, requests, certifi, socketio, pywin32, etc.
│       └── scripts/             # gazu_api.py
├── login/
│   ├── login_view.py            # Authentication + mount point validation
│   └── login_window.ui
├── main/
│   ├── main_view.py             # Main window (task list + Settings button)
│   ├── main_window.ui
│   ├── remote_tasks_widget.py   # 4-panel task tree, dir browser, file list, thumbnail
│   ├── dcc_launcher.py          # DCC launch dispatcher (.comp → Fusion, .nk → Nuke)
│   ├── app_settings_dialog.py   # Fusion path + Nuke Root Path settings
│   ├── publisher_dialog.py      # Publish dialog
│   └── publisher_dialog.ui
├── dcc/
│   ├── Fusion/
│   │   ├── open_fusion.cmd      # Fusion environment setup + launch
│   │   ├── Plugins/             # Studio Fusion plugins – gitignored, copy here locally
│   │   ├── Reactor/             # Fusion Reactor package manager
│   │   └── Gazu/                # Fusion site (plugins, scripts, profiles)
│   └── Nuke/
│       ├── open_nuke.cmd        # Nuke environment setup + launch
│       ├── Plugins/             # Studio Nuke plugins – gitignored, copy here locally
│       │                        # Each subfolder is auto-added to NUKE_PATH at launch
│       └── Gazu/                # Nuke site (menu.py + gazu_nuke.py)
└── services/
    ├── gazu_api.py              # Kitsu/Zou API wrapper
    ├── config_service.py        # Config & credentials
    └── ui_utils.py              # UI helpers & logging
```

---

## License

Internal studio tool. All rights reserved.
