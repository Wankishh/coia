"""Data Sources library CRUD and file-source content endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app.api.deps import get_settings, get_source_repo
from app.config import Settings
from app.models.source import (
    DataSourceCreate,
    DataSourceUpdate,
    SourcePublic,
    SourceType,
    SqlSourceConfig,
    to_public_source,
)
from app.services.repos import SourceRepository
from app.services.source_files import (
    SourceFilesError,
    delete_file,
    delete_library_source_dir,
    list_source_files,
    normalize_upload_name,
    read_text_file,
    source_root,
    write_text_file,
    write_upload,
)
from app.services.source_schema import SourceSchema, fetch_source_schema
from app.services.source_test import SourceTestRequest, SourceTestResult, test_source_connection

router = APIRouter(tags=["sources"])


class FileContentUpdate(BaseModel):
    content: str = Field(description="Full text file contents")


class SourceFileInfo(BaseModel):
    path: str
    size: int
    is_text: bool


class SourceFileContent(BaseModel):
    path: str
    content: str


def _require_files_source(source) -> None:
    if source.type != SourceType.files:
        raise HTTPException(status_code=400, detail="Source is not a files source")


@router.post("/sources", response_model=SourcePublic, status_code=201)
async def create_source(
    payload: DataSourceCreate,
    source_repo: SourceRepository = Depends(get_source_repo),
    settings: Settings = Depends(get_settings),
) -> SourcePublic:
    try:
        source = await source_repo.create(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if source.type == SourceType.files:
        source_root(settings.workspace_path, source.id)
    return to_public_source(source, include_timestamps=True)


@router.get("/sources", response_model=list[SourcePublic])
async def list_sources(
    source_repo: SourceRepository = Depends(get_source_repo),
) -> list[SourcePublic]:
    sources = await source_repo.list_all()
    return [to_public_source(s, include_timestamps=True) for s in sources]


@router.get("/sources/{source_id}", response_model=SourcePublic)
async def get_source(
    source_id: str,
    source_repo: SourceRepository = Depends(get_source_repo),
) -> SourcePublic:
    source = await source_repo.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return to_public_source(source, include_timestamps=True)


@router.patch("/sources/{source_id}", response_model=SourcePublic)
async def update_source(
    source_id: str,
    payload: DataSourceUpdate,
    source_repo: SourceRepository = Depends(get_source_repo),
    settings: Settings = Depends(get_settings),
) -> SourcePublic:
    source = await source_repo.update(source_id, payload)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    if source.type == SourceType.files:
        source_root(settings.workspace_path, source.id)
    return to_public_source(source, include_timestamps=True)


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(
    source_id: str,
    source_repo: SourceRepository = Depends(get_source_repo),
    settings: Settings = Depends(get_settings),
) -> None:
    deleted = await source_repo.delete(source_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Source not found")
    delete_library_source_dir(settings.workspace_path, source_id)


@router.get("/sources/{source_id}/schema", response_model=SourceSchema)
async def get_source_schema(
    source_id: str,
    source_repo: SourceRepository = Depends(get_source_repo),
) -> SourceSchema:
    """List tables and columns (plus cheap row counts) for a SQL library source."""
    source = await source_repo.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    if source.type != SourceType.sql:
        raise HTTPException(
            status_code=400,
            detail="Schema browser is only available for SQL sources",
        )
    try:
        cfg = SqlSourceConfig.model_validate(source.config)
        return await fetch_source_schema(source.id, cfg)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc) or "Schema fetch failed") from exc


@router.post("/sources/test", response_model=SourceTestResult)
async def test_source_draft(
    payload: SourceTestRequest,
    settings: Settings = Depends(get_settings),
) -> SourceTestResult:
    """Probe an unsaved / draft source config (SELECT 1 / Mongo ping / files folder)."""
    if payload.type is None:
        raise HTTPException(status_code=400, detail="type is required")
    return await test_source_connection(payload, settings)


@router.post("/sources/{source_id}/test", response_model=SourceTestResult)
async def test_source(
    source_id: str,
    payload: Optional[SourceTestRequest] = None,
    source_repo: SourceRepository = Depends(get_source_repo),
    settings: Settings = Depends(get_settings),
) -> SourceTestResult:
    """
    Probe a saved library source.

    Optional body overrides draft fields; omitted secrets are filled from storage.
    An empty / omitted body tests the stored config as-is.
    """
    source = await source_repo.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    # Treat a bare "{}" / missing typed payload as "use stored source".
    if payload is None or not getattr(payload, "type", None):
        return await test_source_connection(source, settings)
    return await test_source_connection(payload, settings, existing=source)


# --- File source contents -------------------------------------------------


@router.get(
    "/sources/{source_id}/files",
    response_model=list[SourceFileInfo],
)
async def list_source_files_endpoint(
    source_id: str,
    source_repo: SourceRepository = Depends(get_source_repo),
    settings: Settings = Depends(get_settings),
) -> list[SourceFileInfo]:
    source = await source_repo.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    _require_files_source(source)
    root = source_root(settings.workspace_path, source_id)
    return [SourceFileInfo(**entry) for entry in list_source_files(root)]


@router.post(
    "/sources/{source_id}/files",
    response_model=SourceFileInfo,
    status_code=201,
)
async def upload_source_file(
    source_id: str,
    file: UploadFile = File(...),
    path: Optional[str] = Query(
        default=None,
        description="Optional relative path override (defaults to upload filename)",
    ),
    source_repo: SourceRepository = Depends(get_source_repo),
    settings: Settings = Depends(get_settings),
) -> SourceFileInfo:
    source = await source_repo.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    _require_files_source(source)
    root = source_root(settings.workspace_path, source_id)
    try:
        rel = path.strip().lstrip("/") if path else normalize_upload_name(file.filename)
        if not rel:
            raise SourceFilesError("path is empty")
        data = await file.read()
        target = write_upload(root, rel, data)
    except SourceFilesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SourceFileInfo(
        path=rel,
        size=target.stat().st_size,
        is_text=True,
    )


@router.get(
    "/sources/{source_id}/files/{file_path:path}",
    response_model=SourceFileContent,
)
async def get_source_file(
    source_id: str,
    file_path: str,
    source_repo: SourceRepository = Depends(get_source_repo),
    settings: Settings = Depends(get_settings),
) -> SourceFileContent:
    source = await source_repo.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    _require_files_source(source)
    root = source_root(settings.workspace_path, source_id)
    try:
        content = read_text_file(root, file_path)
    except SourceFilesError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SourceFileContent(path=file_path, content=content)


@router.put(
    "/sources/{source_id}/files/{file_path:path}",
    response_model=SourceFileContent,
)
async def put_source_file(
    source_id: str,
    file_path: str,
    body: FileContentUpdate,
    source_repo: SourceRepository = Depends(get_source_repo),
    settings: Settings = Depends(get_settings),
) -> SourceFileContent:
    source = await source_repo.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    _require_files_source(source)
    root = source_root(settings.workspace_path, source_id)
    try:
        write_text_file(root, file_path, body.content)
    except SourceFilesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SourceFileContent(path=file_path, content=body.content)


@router.delete(
    "/sources/{source_id}/files/{file_path:path}",
    status_code=204,
)
async def delete_source_file(
    source_id: str,
    file_path: str,
    source_repo: SourceRepository = Depends(get_source_repo),
    settings: Settings = Depends(get_settings),
) -> None:
    source = await source_repo.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    _require_files_source(source)
    root = source_root(settings.workspace_path, source_id)
    try:
        delete_file(root, file_path)
    except SourceFilesError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
