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
| Nuke | `.nk`, `.nknc` | 🔲 Not implemented |
| Houdini | `.hip`, `.hiplc`, `.hipnc` | 🔲 Not implemented |

The Fusion path is configurable via **Settings** (gear icon in the main window).  
A console window for DCC output can optionally be shown/hidden from the same Settings dialog.

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

### 1. Clone the repository

```cmd
git clone https://github.com/nagyg/GazuRemote.git
cd GazuRemote
```

### 2. Run the installer

```cmd
install.cmd
```

The script will:
- Extract the bundled `Python312_clean.zip` (Python 3.12.10 embeddable + pip)
- Install all required packages from `requirements.txt`

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
├── __main__.py                  # Entry point
├── GazuRemote.exe               # Main launcher (no console)
├── GazuRemote.cmd               # Debug launcher (console output)
├── install.cmd                  # First-time setup
├── Python312_clean.zip          # Bundled Python 3.12.10 embeddable + pip
├── requirements.txt
├── images/                      # App icons and logo
├── login/
│   ├── login_view.py            # Authentication + mount point validation
│   └── login_window.ui
├── main/
│   ├── main_view.py             # Main window (task list + Settings button)
│   ├── main_window.ui
│   ├── remote_tasks_widget.py   # 4-panel task tree, dir browser, file list, thumbnail
│   ├── dcc_launcher.py          # DCC launch dispatcher
│   ├── app_settings_dialog.py   # Fusion path + Show Console setting
│   ├── publisher_dialog.py      # Publish dialog
│   └── publisher_dialog.ui
├── dcc/
│   └── Fusion/
│       └── open_fusion.cmd      # Fusion environment setup + launch
└── services/
    ├── gazu_api.py              # Kitsu/Zou API wrapper
    ├── config_service.py        # Config & credentials
    └── ui_utils.py              # UI helpers & logging
```

---

## License

Internal studio tool. All rights reserved.
