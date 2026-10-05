"""Data Sources library CRUD and file-source content endpoints."""

from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.deps import get_settings, get_source_repo
from app.config import Settings
from app.models.source import (
    DataSourceCreate,
    DataSourceUpdate,
    NosqlSourceConfig,
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
    dir_entry,
    file_entry,
    list_source_files,
    mkdir_path,
    normalize_dir_path,
    read_text_file,
    resolve_existing_file,
    resolve_upload_relative_path,
    source_root,
    write_text_file,
    write_upload,
)
from app.services.source_schema import (
    SourceSchema,
    fetch_mongo_schema,
    fetch_source_schema,
)
from app.services.source_test import SourceTestRequest, SourceTestResult, test_source_connection

router = APIRouter(tags=["sources"])


class FileContentUpdate(BaseModel):
    content: str = Field(description="Full text file contents")


class MkdirBody(BaseModel):
    path: str = Field(description="Relative directory path to create")


class SourceFileInfo(BaseModel):
    name: str
    path: str
    type: Literal["file", "dir"]
    size: Optional[int] = None
    is_text: Optional[bool] = None
    mtime: Optional[str] = None
    created: Optional[str] = None


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
    """List tables/columns (SQL) or collections (MongoDB) for a library source."""
    source = await source_repo.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    if source.type == SourceType.sql:
        try:
            cfg = SqlSourceConfig.model_validate(source.config)
            return await fetch_source_schema(source.id, cfg)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=400, detail=str(exc) or "Schema fetch failed"
            ) from exc
    if source.type == SourceType.nosql:
        try:
            cfg = NosqlSourceConfig.model_validate(source.config)
            return await fetch_mongo_schema(source.id, cfg)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=400, detail=str(exc) or "Schema fetch failed"
            ) from exc
    raise HTTPException(
        status_code=400,
        detail="Schema browser is only available for SQL and MongoDB sources",
    )


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
    path: Optional[str] = Query(
        default=None,
        description="Relative directory to list (immediate children only)",
    ),
    source_repo: SourceRepository = Depends(get_source_repo),
    settings: Settings = Depends(get_settings),
) -> list[SourceFileInfo]:
    source = await source_repo.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    _require_files_source(source)
    root = source_root(settings.workspace_path, source_id)
    try:
        rel = normalize_dir_path(path)
        entries = list_source_files(root, rel or None)
    except SourceFilesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [SourceFileInfo(**entry) for entry in entries]


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
        description="Relative destination path (or directory ending with /)",
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
        rel = resolve_upload_relative_path(path, file.filename)
        if not rel:
            raise SourceFilesError("path is empty")
        data = await file.read()
        write_upload(root, rel, data)
        return SourceFileInfo(**file_entry(root, rel))
    except SourceFilesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/sources/{source_id}/files/mkdir",
    response_model=SourceFileInfo,
    status_code=201,
)
async def mkdir_source_dir(
    source_id: str,
    body: MkdirBody,
    source_repo: SourceRepository = Depends(get_source_repo),
    settings: Settings = Depends(get_settings),
) -> SourceFileInfo:
    source = await source_repo.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    _require_files_source(source)
    root = source_root(settings.workspace_path, source_id)
    try:
        rel = normalize_dir_path(body.path)
        if not rel:
            raise SourceFilesError("path is empty")
        mkdir_path(root, rel)
        return SourceFileInfo(**dir_entry(root, rel))
    except SourceFilesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sources/{source_id}/files/{file_path:path}/raw")
async def download_source_file_raw(
    source_id: str,
    file_path: str,
    source_repo: SourceRepository = Depends(get_source_repo),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    source = await source_repo.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    _require_files_source(source)
    root = source_root(settings.workspace_path, source_id)
    try:
        target = resolve_existing_file(root, file_path)
    except SourceFilesError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(target, filename=target.name)


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
