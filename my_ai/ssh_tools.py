"""Allowlisted SSH helper for Harold.

Configure in .env:
  HAROLD_SSH_HOST, HAROLD_SSH_USER, HAROLD_SSH_PASS (or HAROLD_SSH_KEY_PATH),
  HAROLD_SSH_PORT (default 22).

Only the named commands in ALLOWED_COMMANDS can run; arbitrary shell input is
never accepted. Requires `paramiko` (pip install paramiko).
"""
import os
import posixpath

ALLOWED_COMMANDS = {
    "uptime": "uptime",
    "disk": "df -h /",
    "memory": "free -h",
    "status": "systemctl is-active harold || true",
    "list": "ls -la ~/peake_ai",
}

_TIMEOUT = 20


def _config():
    host = os.environ.get("HAROLD_SSH_HOST", "").strip()
    user = os.environ.get("HAROLD_SSH_USER", "").strip()
    if not host or not user:
        return None
    return {
        "host": host,
        "user": user,
        "port": int(os.environ.get("HAROLD_SSH_PORT", "22") or 22),
        "password": os.environ.get("HAROLD_SSH_PASS") or None,
        "key": os.environ.get("HAROLD_SSH_KEY_PATH") or None,
    }


def _connect():
    cfg = _config()
    if cfg is None:
        raise RuntimeError("HAROLD_SSH_HOST and HAROLD_SSH_USER are not set")
    try:
        import paramiko
    except ImportError as exc:
        raise RuntimeError("paramiko is not installed (pip install paramiko)") from exc
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        cfg["host"],
        port=cfg["port"],
        username=cfg["user"],
        password=cfg["password"],
        key_filename=cfg["key"],
        timeout=_TIMEOUT,
        look_for_keys=cfg["key"] is None and cfg["password"] is None,
    )
    return client


def run_named_command(name):
    """Run an allowlisted command by name; returns (ok, output)."""
    command = ALLOWED_COMMANDS.get(str(name).strip().lower())
    if command is None:
        return False, "Unknown command. Allowed: " + ", ".join(sorted(ALLOWED_COMMANDS))
    try:
        client = _connect()
    except Exception as exc:
        return False, f"SSH connection failed: {exc}"
    try:
        _, stdout, stderr = client.exec_command(command, timeout=_TIMEOUT)
        out = stdout.read().decode("utf-8", "replace").strip()
        err = stderr.read().decode("utf-8", "replace").strip()
        return stdout.channel.recv_exit_status() == 0, out or err
    except Exception as exc:
        return False, f"SSH command failed: {exc}"
    finally:
        client.close()


def upload_file(local_path, remote_dir="peake_ai"):
    """Upload a file into a directory under the remote home; returns (ok, message)."""
    if not os.path.isfile(local_path):
        return False, "Local file not found."
    remote_dir = remote_dir.strip("/")
    if ".." in remote_dir.split("/"):
        return False, "Invalid remote directory."
    try:
        client = _connect()
    except Exception as exc:
        return False, f"SSH connection failed: {exc}"
    try:
        sftp = client.open_sftp()
        target = posixpath.join(remote_dir, os.path.basename(local_path))
        sftp.put(local_path, target)
        sftp.close()
        return True, f"Uploaded to {target}"
    except Exception as exc:
        return False, f"Upload failed: {exc}"
    finally:
        client.close()
