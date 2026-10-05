"""Generate marketing images via provider-specific backends into the agent workspace."""

from __future__ import annotations

import base64
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Optional
from uuid import uuid4

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.models.agent import LLMProvider
from app.models.conversation import ChatAttachment
from app.tools.sandbox_file import SandboxPathError, resolve_sandbox_path

logger = logging.getLogger(__name__)

_SAFE_STEM = re.compile(r"[^A-Za-z0-9._-]+")

# Sizes accepted by gpt-image-1 and/or dall-e-3 in current openai SDK.
ALLOWED_SIZES = frozenset(
    {
        "1024x1024",
        "1536x1024",
        "1024x1536",
        "1792x1024",
        "1024x1792",
        "auto",
    }
)

DEFAULT_SIZE = "1024x1024"
OPENAI_DEFAULT_MODEL = "gpt-image-1"
OPENAI_FALLBACK_MODEL = "dall-e-3"
OPENROUTER_DEFAULT_IMAGE_MODEL = "google/gemini-2.5-flash-image"
GOOGLE_DEFAULT_IMAGE_MODEL = "gemini-2.5-flash-image"
OPENROUTER_IMAGES_URL = "https://openrouter.ai/api/v1/images"
GOOGLE_GENAI_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Capability matrix: "supported" backends generate images; others raise clear errors.
IMAGE_PROVIDER_SUPPORT: dict[str, str] = {
    LLMProvider.openai.value: "supported",
    LLMProvider.openrouter.value: "supported",
    LLMProvider.google.value: "supported",
    LLMProvider.anthropic.value: (
        "not_supported — Anthropic has no image generation API; "
        "use openai, openrouter, or google"
    ),
    LLMProvider.ollama.value: (
        "not_supported — Ollama has no image generation API in Coia; "
        "use openai, openrouter, or google"
    ),
}

DEFAULT_IMAGE_MODELS: dict[str, str] = {
    LLMProvider.openai.value: OPENAI_DEFAULT_MODEL,
    LLMProvider.openrouter.value: OPENROUTER_DEFAULT_IMAGE_MODEL,
    LLMProvider.google.value: GOOGLE_DEFAULT_IMAGE_MODEL,
}

SIZE_TO_ASPECT: dict[str, str] = {
    "1024x1024": "1:1",
    "1536x1024": "3:2",
    "1792x1024": "16:9",
    "1024x1536": "2:3",
    "1024x1792": "9:16",
    "auto": "1:1",
}


class GenerateImageInput(BaseModel):
    prompt: str = Field(
        description=(
            "Detailed image prompt: subject, setting, style, lighting, "
            "composition, and aspect intent"
        )
    )
    size: str = Field(
        default=DEFAULT_SIZE,
        description=(
            "Image size, e.g. 1024x1024, 1536x1024, 1024x1536 "
            "(default 1024x1024)"
        ),
    )
    filename: str = Field(
        default="",
        description=(
            "Optional filename or stem for the PNG under `_generated/` "
            "(e.g. hero.png or hero). Auto-generated when omitted."
        ),
    )


def provider_supports_image_gen(provider: LLMProvider | str) -> bool:
    value = provider.value if isinstance(provider, LLMProvider) else str(provider)
    return IMAGE_PROVIDER_SUPPORT.get(value) == "supported"


def unsupported_provider_message(provider: LLMProvider | str) -> str:
    value = provider.value if isinstance(provider, LLMProvider) else str(provider)
    detail = IMAGE_PROVIDER_SUPPORT.get(
        value, "not_supported for this provider"
    )
    return (
        f"Error: generate_image is not available for provider '{value}' "
        f"({detail}). Supported: openai, openrouter, google."
    )


def resolve_image_model(
    provider: LLMProvider | str,
    image_model: str | None = None,
) -> str:
    """Pick the image model: agent override, else provider default."""
    value = provider.value if isinstance(provider, LLMProvider) else str(provider)
    override = (image_model or "").strip()
    if override:
        return override
    return DEFAULT_IMAGE_MODELS.get(value, OPENAI_DEFAULT_MODEL)


def normalize_image_size(size: str | None) -> str:
    cleaned = (size or DEFAULT_SIZE).strip().lower().replace(" ", "")
    if cleaned not in ALLOWED_SIZES:
        return DEFAULT_SIZE
    return cleaned


def size_to_aspect_ratio(size: str) -> str:
    return SIZE_TO_ASPECT.get(normalize_image_size(size), "1:1")


def safe_image_filename(name: str | None) -> str:
    """Return a safe `.png` filename under `_generated/`."""
    raw = (name or "").strip()
    if not raw:
        return f"image_{uuid4().hex[:10]}.png"
    base = Path(raw).name
    stem = Path(base).stem or "image"
    cleaned = _SAFE_STEM.sub("_", stem).strip("._") or "image"
    return f"{cleaned[:120]}.png"


def write_generated_png(workspace: Path, relative_name: str, data: bytes) -> Path:
    """Write PNG bytes under `{workspace}/_generated/{name}` (sandbox-safe)."""
    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    rel = f"_generated/{Path(relative_name).name}"
    try:
        target = resolve_sandbox_path(workspace, rel)
    except SandboxPathError:
        raise
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def _decode_b64_or_url(item: object) -> bytes:
    if isinstance(item, dict):
        b64 = item.get("b64_json") or item.get("b64")
        if b64:
            return base64.b64decode(b64)
        url = item.get("url")
        if url:
            with httpx.Client(timeout=60.0) as client:
                resp = client.get(url)
                resp.raise_for_status()
                return resp.content
        raise RuntimeError("Image API returned neither b64_json nor url")

    b64 = getattr(item, "b64_json", None)
    if b64:
        return base64.b64decode(b64)
    url = getattr(item, "url", None)
    if url:
        with httpx.Client(timeout=60.0) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.content
    raise RuntimeError("Image API returned neither b64_json nor url")


def _strip_data_url(b64_or_data_url: str) -> bytes:
    raw = (b64_or_data_url or "").strip()
    if "," in raw and raw.lower().startswith("data:"):
        raw = raw.split(",", 1)[1]
    return base64.b64decode(raw)


def _generate_via_openai(
    *,
    api_key: str,
    prompt: str,
    size: str,
    model: str,
    base_url: str | None = None,
) -> tuple[bytes, str]:
    from openai import OpenAI

    kwargs: dict = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    client = OpenAI(**kwargs)

    models_to_try: list[str] = []
    for candidate in (model, OPENAI_DEFAULT_MODEL, OPENAI_FALLBACK_MODEL):
        if candidate and candidate not in models_to_try:
            models_to_try.append(candidate)

    last_error: Exception | None = None
    for model_id in models_to_try:
        try:
            gen_kwargs: dict = {
                "model": model_id,
                "prompt": prompt,
                "size": size if size != "auto" or model_id != OPENAI_FALLBACK_MODEL else DEFAULT_SIZE,
                "n": 1,
            }
            if model_id == OPENAI_FALLBACK_MODEL:
                if gen_kwargs["size"] not in {
                    "1024x1024",
                    "1792x1024",
                    "1024x1792",
                }:
                    gen_kwargs["size"] = DEFAULT_SIZE
                gen_kwargs["response_format"] = "b64_json"
            result = client.images.generate(**gen_kwargs)
            if not result.data:
                raise RuntimeError("Image API returned empty data")
            return _decode_b64_or_url(result.data[0]), model_id
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.info("Image model %s failed: %s", model_id, exc)
            continue
    raise RuntimeError(
        f"Image generation failed with {', '.join(models_to_try)}: {last_error}"
    )


def _generate_via_openrouter(
    *,
    api_key: str,
    prompt: str,
    size: str,
    model: str,
) -> tuple[bytes, str]:
    """OpenRouter dedicated Image API (`POST /api/v1/images`).

    Works with image-output models such as ``google/gemini-2.5-flash-image``,
    ``openai/gpt-image-1``, ``black-forest-labs/flux.2-pro``, etc.
    See https://openrouter.ai/docs/guides/overview/multimodal/image-generation
    """
    payload: dict = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "output_format": "png",
    }
    # Prefer explicit pixel size when the router accepts it; also send aspect.
    if size and size != "auto":
        payload["size"] = size
    payload["aspect_ratio"] = size_to_aspect_ratio(size)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/coia-agents",
        "X-Title": "Coia Agents",
    }
    with httpx.Client(timeout=120.0) as client:
        resp = client.post(OPENROUTER_IMAGES_URL, headers=headers, json=payload)
        if resp.status_code >= 400:
            detail = resp.text[:500]
            raise RuntimeError(
                f"OpenRouter images API HTTP {resp.status_code}: {detail}"
            )
        body = resp.json()

    data = body.get("data") if isinstance(body, dict) else None
    if not data:
        raise RuntimeError("OpenRouter images API returned empty data")
    return _decode_b64_or_url(data[0]), model


def _extract_google_inline_image(body: dict) -> bytes:
    candidates = body.get("candidates") or []
    if not candidates:
        # Surface block / safety feedback when present.
        feedback = body.get("promptFeedback") or body.get("error")
        raise RuntimeError(
            f"Google image API returned no candidates: {feedback or body}"
        )
    parts = (
        ((candidates[0] or {}).get("content") or {}).get("parts") or []
    )
    for part in parts:
        if not isinstance(part, dict):
            continue
        inline = part.get("inlineData") or part.get("inline_data")
        if not inline:
            continue
        data = inline.get("data")
        if data:
            return _strip_data_url(data)
    raise RuntimeError("Google image API response contained no inline image data")


def _generate_via_google(
    *,
    api_key: str,
    prompt: str,
    size: str,
    model: str,
) -> tuple[bytes, str]:
    """Gemini native image generation via REST ``generateContent``.

    Default model: ``gemini-2.5-flash-image`` (Nano Banana). Uses httpx so we
    do not require the ``google-genai`` SDK.
    """
    model_id = model.removeprefix("models/")
    url = f"{GOOGLE_GENAI_BASE}/models/{model_id}:generateContent"
    aspect = size_to_aspect_ratio(size)
    payload: dict = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": {"aspectRatio": aspect},
        },
    }
    with httpx.Client(timeout=120.0) as client:
        resp = client.post(url, params={"key": api_key}, json=payload)
        if resp.status_code >= 400:
            # Retry without imageConfig for older model schemas.
            if resp.status_code == 400:
                slim = {
                    "contents": payload["contents"],
                    "generationConfig": {
                        "responseModalities": ["TEXT", "IMAGE"],
                    },
                }
                resp = client.post(url, params={"key": api_key}, json=slim)
            if resp.status_code >= 400:
                detail = resp.text[:500]
                raise RuntimeError(
                    f"Google image API HTTP {resp.status_code}: {detail}"
                )
        body = resp.json()

    return _extract_google_inline_image(body), model_id


def generate_image_bytes(
    *,
    provider: LLMProvider | str,
    api_key: str,
    prompt: str,
    size: str = DEFAULT_SIZE,
    image_model: str | None = None,
    base_url: str | None = None,
) -> tuple[bytes, str]:
    """Dispatch to the provider backend. Returns ``(png_bytes, model_used)``."""
    value = provider.value if isinstance(provider, LLMProvider) else str(provider)
    if not provider_supports_image_gen(value):
        raise RuntimeError(unsupported_provider_message(value))

    model = resolve_image_model(value, image_model)
    safe_size = normalize_image_size(size)

    if value == LLMProvider.openai.value:
        return _generate_via_openai(
            api_key=api_key,
            prompt=prompt,
            size=safe_size,
            model=model,
            base_url=base_url,
        )
    if value == LLMProvider.openrouter.value:
        return _generate_via_openrouter(
            api_key=api_key,
            prompt=prompt,
            size=safe_size,
            model=model,
        )
    if value == LLMProvider.google.value:
        return _generate_via_google(
            api_key=api_key,
            prompt=prompt,
            size=safe_size,
            model=model,
        )
    raise RuntimeError(unsupported_provider_message(value))


def create_generate_image_tool(
    workspace: Path,
    *,
    provider: LLMProvider | str,
    api_key: str,
    base_url: str | None = None,
    image_model: str | None = None,
    workspace_root: Path | None = None,
    chat_id: str | None = None,
    on_image: Optional[Callable[[ChatAttachment], None]] = None,
) -> StructuredTool:
    """Build the ``generate_image`` tool for an agent."""

    workspace.mkdir(parents=True, exist_ok=True)
    provider_value = (
        provider.value if isinstance(provider, LLMProvider) else str(provider)
    )

    def generate_image(
        prompt: str,
        size: str = DEFAULT_SIZE,
        filename: str = "",
    ) -> str:
        text = (prompt or "").strip()
        if not text:
            return "Error: prompt is required"

        if not provider_supports_image_gen(provider_value):
            return unsupported_provider_message(provider_value)

        key = (api_key or "").strip()
        if not key:
            return (
                "Error: generate_image requires an API key on this agent "
                f"(provider={provider_value})"
            )

        safe_size = normalize_image_size(size)
        safe_name = safe_image_filename(filename)

        try:
            png_bytes, model_used = generate_image_bytes(
                provider=provider_value,
                api_key=key,
                prompt=text,
                size=safe_size,
                image_model=image_model,
                base_url=base_url,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("generate_image failed")
            return f"Error: image generation failed: {exc}"

        try:
            path = write_generated_png(workspace, safe_name, png_bytes)
        except SandboxPathError as exc:
            return f"Error: {exc}"
        except OSError as exc:
            return f"Error: failed to write image: {exc}"

        rel_workspace = f"_generated/{path.name}"
        parts = [
            f"Generated image with {model_used} ({safe_size}).",
            f"Saved to agent workspace: {rel_workspace}",
            f"({len(png_bytes)} bytes).",
        ]

        if chat_id and workspace_root is not None:
            try:
                # Lazy import avoids tools ↔ chat_attachments circular import.
                from app.services.chat_attachments import (
                    ChatAttachmentError,
                    save_upload,
                )

                attachment = save_upload(
                    workspace_root,
                    chat_id,
                    filename=path.name,
                    data=png_bytes,
                    content_type="image/png",
                )
                if on_image is not None:
                    on_image(attachment)
                parts.append(
                    f"Registered as chat attachment: {attachment.name}"
                )
            except ChatAttachmentError as exc:
                parts.append(f"(Chat attachment skipped: {exc})")
        elif on_image is not None:
            # Defensive: callback without chat_id cannot register a preview.
            parts.append(
                "(Chat attachment skipped: chat_id missing — "
                "image saved to workspace only)"
            )

        return " ".join(parts)

    return StructuredTool.from_function(
        func=generate_image,
        name="generate_image",
        description=(
            "Generate a PNG marketing image from a text prompt when the agent "
            "provider has an image backend (openai Images API; openrouter "
            f"`/api/v1/images`, default `{OPENROUTER_DEFAULT_IMAGE_MODEL}`; "
            f"google Gemini image models, default `{GOOGLE_DEFAULT_IMAGE_MODEL}`). "
            "Saves under `_generated/` in the agent workspace and, in chat, "
            "registers a previewable attachment. "
            "Anthropic and Ollama return a clear unsupported error. "
            "Args: prompt (required), optional size, optional filename stem."
        ),
        args_schema=GenerateImageInput,
    )
