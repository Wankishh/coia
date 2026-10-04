"""Optional SSH tunnel helper for SQL/NoSQL source connections."""

from __future__ import annotations

import logging
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional
from urllib.parse import urlparse, urlunparse

from app.models.source import SshConfig

logger = logging.getLogger(__name__)


def rewrite_url_host_port(url: str, host: str, port: int) -> str:
    """Rewrite netloc host:port while keeping credentials and path."""
    parsed = urlparse(url)
    userinfo = ""
    if parsed.username is not None:
        userinfo = parsed.username
        if parsed.password is not None:
            userinfo += f":{parsed.password}"
        userinfo += "@"
    new_netloc = f"{userinfo}{host}:{port}"
    return urlunparse(parsed._replace(netloc=new_netloc))


def parse_db_host_port(url: str, default_port: int) -> tuple[str, int]:
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or default_port
    return host, port


@contextmanager
def optional_ssh_tunnel(
    connection_url: str,
    ssh: Optional[SshConfig],
    *,
    default_remote_port: int,
) -> Iterator[str]:
    """
    If ssh.enabled, open a local tunnel and yield a rewritten localhost URL.
    Otherwise yield the original URL unchanged.
    """
    if ssh is None or not ssh.enabled:
        yield connection_url
        return

    if not ssh.host or not ssh.username:
        raise ValueError("SSH tunnel requires host and username")

    db_host, db_port = parse_db_host_port(connection_url, default_remote_port)
    remote_host = ssh.remote_host or db_host
    remote_port = ssh.remote_port or db_port

    try:
        from sshtunnel import SSHTunnelForwarder
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "sshtunnel is not installed; cannot open SSH tunnel"
        ) from exc

    key_path: Optional[Path] = None
    pkey_arg = None
    password = None

    if ssh.auth.value == "key":
        if not (ssh.private_key or "").strip():
            raise ValueError("SSH auth=key requires private_key")
        # sshtunnel accepts a path; write key material to a temp file.
        tmp = tempfile.NamedTemporaryFile("w", delete=False, suffix=".pem")
        tmp.write(ssh.private_key)
        tmp.flush()
        tmp.close()
        key_path = Path(tmp.name)
        key_path.chmod(0o600)
        pkey_arg = str(key_path)
    else:
        password = ssh.password or None
        if not password:
            raise ValueError("SSH auth=password requires password")

    tunnel = SSHTunnelForwarder(
        (ssh.host, int(ssh.port or 22)),
        ssh_username=ssh.username,
        ssh_password=password,
        ssh_pkey=pkey_arg,
        remote_bind_address=(remote_host, int(remote_port)),
        local_bind_address=("127.0.0.1", 0),
    )

    try:
        tunnel.start()
        local_port = tunnel.local_bind_port
        rewritten = rewrite_url_host_port(connection_url, "127.0.0.1", local_port)
        logger.info(
            "SSH tunnel open: 127.0.0.1:%s -> %s:%s via %s",
            local_port,
            remote_host,
            remote_port,
            ssh.host,
        )
        yield rewritten
    finally:
        try:
            tunnel.stop()
        except Exception:  # noqa: BLE001
            logger.exception("Failed to stop SSH tunnel cleanly")
        if key_path is not None:
            try:
                key_path.unlink(missing_ok=True)
            except OSError:
                pass
