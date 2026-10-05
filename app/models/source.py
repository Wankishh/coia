"""Data source configuration models (library + legacy embedded shapes)."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


class SourceType(str, Enum):
    sql = "sql"
    nosql = "nosql"
    files = "files"
    rest = "rest"


class SshAuth(str, Enum):
    password = "password"
    key = "key"


class SshConfig(BaseModel):
    enabled: bool = False
    host: Optional[str] = None
    port: int = 22
    username: Optional[str] = None
    auth: SshAuth = SshAuth.password
    password: Optional[str] = None
    private_key: Optional[str] = None
    remote_host: Optional[str] = None
    remote_port: Optional[int] = None


class SqlSourceConfig(BaseModel):
    engine: Literal["postgresql", "mysql", "sqlite"] = "postgresql"
    connection_string: Optional[str] = None
    ssh: Optional[SshConfig] = None


class NosqlSourceConfig(BaseModel):
    engine: Literal["mongodb"] = "mongodb"
    connection_string: Optional[str] = None
    ssh: Optional[SshConfig] = None


class FilesSourceConfig(BaseModel):
    path_prefix: Optional[str] = None


class RestAuthType(str, Enum):
    none = "none"
    bearer = "bearer"
    header = "header"


class RestSourceConfig(BaseModel):
    """GET-first HTTP API source."""

    base_url: str = ""
    auth: RestAuthType = RestAuthType.none
    bearer_token: Optional[str] = None
    header_name: Optional[str] = None
    header_value: Optional[str] = None
    allowed_path_prefixes: list[str] = Field(default_factory=list)
    timeout_seconds: float = 15.0


SourceConfigPayload = Union[
    SqlSourceConfig, NosqlSourceConfig, FilesSourceConfig, RestSourceConfig
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SourceConfig(BaseModel):
    """Source payload shape (library docs and legacy agent.sources entries)."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    description: str = ""
    type: SourceType
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title")
    @classmethod
    def title_non_empty(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("title is required")
        return title

    @model_validator(mode="after")
    def validate_typed_config(self) -> SourceConfig:
        self.config = _normalize_config(self.type, self.config)
        return self

    def typed_config(self) -> SourceConfigPayload:
        if self.type == SourceType.sql:
            return SqlSourceConfig.model_validate(self.config)
        if self.type == SourceType.nosql:
            return NosqlSourceConfig.model_validate(self.config)
        if self.type == SourceType.rest:
            return RestSourceConfig.model_validate(self.config)
        return FilesSourceConfig.model_validate(self.config)


class DataSourceCreate(BaseModel):
    title: str
    description: str = ""
    type: SourceType
    config: dict[str, Any] = Field(default_factory=dict)
    id: Optional[str] = None

    @field_validator("title")
    @classmethod
    def title_non_empty(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("title is required")
        return title

    @model_validator(mode="after")
    def validate_typed_config(self) -> DataSourceCreate:
        self.config = _normalize_config(self.type, self.config)
        return self


class DataSourceUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    type: Optional[SourceType] = None
    config: Optional[dict[str, Any]] = None

    @field_validator("title")
    @classmethod
    def title_non_empty_when_set(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        title = value.strip()
        if not title:
            raise ValueError("title cannot be empty when provided")
        return title


class DataSource(BaseModel):
    """Stored global library source document (`data_sources` collection)."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    description: str = ""
    type: SourceType
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    @model_validator(mode="after")
    def validate_typed_config(self) -> DataSource:
        self.config = _normalize_config(self.type, self.config)
        return self

    def as_source_config(self) -> SourceConfig:
        return SourceConfig(
            id=self.id,
            title=self.title,
            description=self.description,
            type=self.type,
            config=self.config,
        )


class SshPublic(BaseModel):
    enabled: bool = False
    host: Optional[str] = None
    port: int = 22
    username: Optional[str] = None
    auth: SshAuth = SshAuth.password
    password_set: bool = False
    private_key_set: bool = False
    remote_host: Optional[str] = None
    remote_port: Optional[int] = None


class SourcePublic(BaseModel):
    """API response shape — secrets redacted to *_set flags."""

    id: str
    title: str
    description: str = ""
    type: SourceType
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SourceSummary(BaseModel):
    """Lightweight attachment summary for agent responses."""

    id: str
    title: str
    type: SourceType
    description: str = ""


def _normalize_config(source_type: SourceType, config: dict[str, Any]) -> dict[str, Any]:
    raw = config or {}
    if source_type == SourceType.sql:
        return SqlSourceConfig.model_validate(raw).model_dump(mode="json")
    if source_type == SourceType.nosql:
        return NosqlSourceConfig.model_validate(raw).model_dump(mode="json")
    if source_type == SourceType.rest:
        return RestSourceConfig.model_validate(raw).model_dump(mode="json")
    return FilesSourceConfig.model_validate(raw).model_dump(mode="json")


def _ssh_public(ssh: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not ssh:
        return None
    model = SshConfig.model_validate(ssh)
    return SshPublic(
        enabled=model.enabled,
        host=model.host,
        port=model.port,
        username=model.username,
        auth=model.auth,
        password_set=bool(model.password and str(model.password).strip()),
        private_key_set=bool(model.private_key and str(model.private_key).strip()),
        remote_host=model.remote_host,
        remote_port=model.remote_port,
    ).model_dump(mode="json")


def to_public_source(
    source: SourceConfig | DataSource,
    *,
    include_timestamps: bool = False,
) -> SourcePublic:
    if source.type in (SourceType.sql, SourceType.nosql):
        engine = source.config.get("engine")
        conn = (source.config.get("connection_string") or "").strip()
        public_config: dict[str, Any] = {
            "engine": engine,
            "connection_string_set": bool(conn),
            "ssh": _ssh_public(source.config.get("ssh")),
        }
    elif source.type == SourceType.rest:
        bearer = (source.config.get("bearer_token") or "").strip()
        header_value = (source.config.get("header_value") or "").strip()
        public_config = {
            "base_url": source.config.get("base_url") or "",
            "auth": source.config.get("auth") or RestAuthType.none.value,
            "bearer_token_set": bool(bearer),
            "header_name": source.config.get("header_name") or None,
            "header_value_set": bool(header_value),
            "allowed_path_prefixes": list(
                source.config.get("allowed_path_prefixes") or []
            ),
            "timeout_seconds": source.config.get("timeout_seconds") or 15.0,
        }
    else:
        public_config = {
            "path_prefix": source.config.get("path_prefix"),
        }
    created_at = getattr(source, "created_at", None) if include_timestamps else None
    updated_at = getattr(source, "updated_at", None) if include_timestamps else None
    return SourcePublic(
        id=source.id,
        title=source.title,
        description=source.description or "",
        type=source.type,
        config=public_config,
        created_at=created_at,
        updated_at=updated_at,
    )


def to_source_summary(source: SourceConfig | DataSource) -> SourceSummary:
    return SourceSummary(
        id=source.id,
        title=source.title,
        type=source.type,
        description=source.description or "",
    )


def merge_source_secrets(
    existing: SourceConfig,
    incoming: SourceConfig,
) -> SourceConfig:
    """Keep stored secrets when the client omits them on update."""
    if existing.type != incoming.type:
        return incoming

    merged_config = dict(incoming.config)
    if incoming.type in (SourceType.sql, SourceType.nosql):
        new_conn = (merged_config.get("connection_string") or "").strip()
        old_conn = (existing.config.get("connection_string") or "").strip()
        if not new_conn and old_conn:
            merged_config["connection_string"] = old_conn

        new_ssh = merged_config.get("ssh") or {}
        old_ssh = existing.config.get("ssh") or {}
        if isinstance(new_ssh, dict) and isinstance(old_ssh, dict):
            ssh = dict(new_ssh)
            if not (ssh.get("password") or "").strip() and (old_ssh.get("password") or "").strip():
                ssh["password"] = old_ssh["password"]
            if not (ssh.get("private_key") or "").strip() and (
                old_ssh.get("private_key") or ""
            ).strip():
                ssh["private_key"] = old_ssh["private_key"]
            merged_config["ssh"] = ssh
    elif incoming.type == SourceType.rest:
        new_bearer = (merged_config.get("bearer_token") or "").strip()
        old_bearer = (existing.config.get("bearer_token") or "").strip()
        if not new_bearer and old_bearer:
            merged_config["bearer_token"] = old_bearer
        new_header = (merged_config.get("header_value") or "").strip()
        old_header = (existing.config.get("header_value") or "").strip()
        if not new_header and old_header:
            merged_config["header_value"] = old_header

    return SourceConfig(
        id=incoming.id,
        title=incoming.title,
        description=incoming.description,
        type=incoming.type,
        config=merged_config,
    )


def merge_sources_list(
    existing: list[SourceConfig],
    incoming: list[SourceConfig],
) -> list[SourceConfig]:
    by_id = {s.id: s for s in existing}
    merged: list[SourceConfig] = []
    for src in incoming:
        old = by_id.get(src.id)
        if old is not None:
            merged.append(merge_source_secrets(old, src))
        else:
            merged.append(src)
    return merged
