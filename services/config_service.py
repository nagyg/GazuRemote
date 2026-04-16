import json
from pathlib import Path


class ConfigService:
    """
    Handles loading and saving user configuration for GazuRemote.
    Config is stored in ~/GazuRemote/user_config.json (separate from main Gazu).
    """

    def __init__(self):
        self.config_dir = Path.home() / "GazuRemote"
        self.config_file = self.config_dir / "user_config.json"
        self.ensure_config_exists()

    def ensure_config_exists(self):
        """Ensures the config directory and file exist."""
        if not self.config_dir.exists():
            self.config_dir.mkdir(parents=True)

        if not self.config_file.is_file():
            with open(self.config_file, "w") as f:
                json.dump({"config_service": {}}, f, indent=4)

    def save_credentials(self, host, email, password, role):
        """Saves the user's credentials to the config file."""
        data = self.load_config_data()
        if "config_service" not in data:
            data["config_service"] = {}
        data["config_service"]["host"] = host
        data["config_service"]["user"] = email
        data["config_service"]["password"] = password  # WARNING: Plaintext!
        data["config_service"]["role"] = role
        self._save_config_data(data)

    def load_credentials(self):
        """Loads the user's credentials from the config file."""
        return self.load_config_data().get("config_service", {})

    def save_last_project(self, project_id):
        """Saves the last selected project ID to the config file."""
        data = self.load_config_data()
        if "config_service" not in data:
            data["config_service"] = {}
        data["config_service"]["last_project_id"] = project_id
        self._save_config_data(data)

    def save_remote_address(self, project_id, remote_address):
        """
        Saves the studio server network address (UNC path) for a specific project.
        e.g. \\\\10.0.0.100\\storage\\Projects
        """
        data = self.load_config_data()
        if "remote_addresses" not in data:
            data["remote_addresses"] = {}
        data["remote_addresses"][project_id] = remote_address
        self._save_config_data(data)

    def load_remote_address(self, project_id):
        """
        Loads the studio server network address for a specific project.
        Returns an empty string if not configured.
        """
        data = self.load_config_data()
        return data.get("remote_addresses", {}).get(project_id, "")

    def save_local_mount_point(self, project_id, local_mount_point):
        """
        Saves the local mount point for a specific project.
        This allows different projects to have different local mappings.
        """
        data = self.load_config_data()
        if "mount_points" not in data:
            data["mount_points"] = {}
        data["mount_points"][project_id] = local_mount_point
        self._save_config_data(data)

    def load_local_mount_point(self, project_id):
        """
        Loads the local mount point for a specific project.
        Returns an empty string if not configured.
        """
        data = self.load_config_data()
        return data.get("mount_points", {}).get(project_id, "")

    def load_config_data(self):
        """Loads the entire configuration data from the file."""
        try:
            with open(self.config_file, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_config_data(self, data):
        """Saves the entire config data to the JSON file."""
        with open(self.config_file, "w") as f:
            json.dump(data, f, indent=4)
