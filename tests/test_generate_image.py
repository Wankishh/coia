"""Pure helpers for generate_image tool."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.models.agent import LLMProvider
from app.tools.generate_image import (
    DEFAULT_IMAGE_MODELS,
    GOOGLE_DEFAULT_IMAGE_MODEL,
    OPENAI_DEFAULT_MODEL,
    OPENROUTER_DEFAULT_IMAGE_MODEL,
    normalize_image_size,
    provider_supports_image_gen,
    resolve_image_model,
    safe_image_filename,
    size_to_aspect_ratio,
    unsupported_provider_message,
    write_generated_png,
)


def test_provider_support_matrix() -> None:
    assert provider_supports_image_gen(LLMProvider.openai) is True
    assert provider_supports_image_gen("openai") is True
    assert provider_supports_image_gen(LLMProvider.openrouter) is True
    assert provider_supports_image_gen(LLMProvider.google) is True
    for provider in (LLMProvider.anthropic, LLMProvider.ollama):
        assert provider_supports_image_gen(provider) is False
        msg = unsupported_provider_message(provider)
        assert "Error:" in msg
        assert provider.value in msg
        assert "openai" in msg.lower() or "Supported:" in msg


def test_resolve_image_model_defaults() -> None:
    assert resolve_image_model("openai") == OPENAI_DEFAULT_MODEL
    assert resolve_image_model("openrouter") == OPENROUTER_DEFAULT_IMAGE_MODEL
    assert resolve_image_model("google") == GOOGLE_DEFAULT_IMAGE_MODEL
    assert resolve_image_model("openai", "dall-e-3") == "dall-e-3"
    assert resolve_image_model("openrouter", "  openai/gpt-image-1  ") == (
        "openai/gpt-image-1"
    )
    for provider, default in DEFAULT_IMAGE_MODELS.items():
        assert resolve_image_model(provider) == default


def test_normalize_image_size() -> None:
    assert normalize_image_size("1024x1024") == "1024x1024"
    assert normalize_image_size(" 1536X1024 ") == "1536x1024"
    assert normalize_image_size("bogus") == "1024x1024"
    assert normalize_image_size(None) == "1024x1024"


def test_size_to_aspect_ratio() -> None:
    assert size_to_aspect_ratio("1024x1024") == "1:1"
    assert size_to_aspect_ratio("1792x1024") == "16:9"
    assert size_to_aspect_ratio("1024x1792") == "9:16"


def test_safe_image_filename() -> None:
    assert safe_image_filename("hero.png") == "hero.png"
    assert safe_image_filename("hero") == "hero.png"
    assert safe_image_filename("../evil/name!!.png") == "name.png"
    auto = safe_image_filename("")
    assert auto.endswith(".png")
    assert auto.startswith("image_")


def test_write_generated_png(tmp_path: Path) -> None:
    data = b"\x89PNG\r\n\x1a\nfake"
    path = write_generated_png(tmp_path, "shot.png", data)
    assert path.name == "shot.png"
    assert path.parent.name == "_generated"
    assert path.read_bytes() == data


def test_write_generated_png_strips_path_components(tmp_path: Path) -> None:
    """Only the basename is used — traversal components are discarded."""
    path = write_generated_png(tmp_path, "../../escape.png", b"x")
    assert path.name == "escape.png"
    assert path.parent == (tmp_path / "_generated").resolve()
    assert path.read_bytes() == b"x"


def test_openrouter_backend_posts_images_api() -> None:
    from app.tools.generate_image import generate_image_bytes

    fake_png = b"\x89PNG\r\n\x1a\nopenrouter"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [{"b64_json": __import__("base64").b64encode(fake_png).decode()}]
    }

    with patch("app.tools.generate_image.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value = mock_resp
        data, model = generate_image_bytes(
            provider="openrouter",
            api_key="sk-or-test",
            prompt="a red cube",
            size="1024x1024",
        )

    assert data == fake_png
    assert model == OPENROUTER_DEFAULT_IMAGE_MODEL
    args, kwargs = client.post.call_args
    assert args[0].endswith("/api/v1/images")
    assert kwargs["json"]["model"] == OPENROUTER_DEFAULT_IMAGE_MODEL
    assert kwargs["json"]["prompt"] == "a red cube"
    assert kwargs["json"]["output_format"] == "png"


def test_google_backend_generate_content() -> None:
    from app.tools.generate_image import generate_image_bytes

    fake_png = b"\x89PNG\r\n\x1a\ngoogle"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": "image/png",
                                "data": __import__("base64")
                                .b64encode(fake_png)
                                .decode(),
                            }
                        }
                    ]
                }
            }
        ]
    }

    with patch("app.tools.generate_image.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value = mock_resp
        data, model = generate_image_bytes(
            provider="google",
            api_key="AIza-test",
            prompt="a blue sphere",
            image_model="gemini-2.5-flash-image",
        )

    assert data == fake_png
    assert model == "gemini-2.5-flash-image"
    args, kwargs = client.post.call_args
    assert "gemini-2.5-flash-image:generateContent" in args[0]
    assert kwargs["params"]["key"] == "AIza-test"


def test_anthropic_backend_raises_clear_error() -> None:
    from app.tools.generate_image import generate_image_bytes

    with pytest.raises(RuntimeError) as exc:
        generate_image_bytes(
            provider="anthropic",
            api_key="sk-ant",
            prompt="nope",
        )
    assert "anthropic" in str(exc.value)
    assert "not available" in str(exc.value).lower() or "Error" in str(exc.value)
