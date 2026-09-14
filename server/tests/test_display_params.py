"""Photometric tile params: validation runs without mosaics; pixel math runs
against a tiny in-memory check only when mosaics exist (same guard as test_api)."""
import os
import pytest
from fastapi.testclient import TestClient

from main import app, _adjust
from rio_tiler.models import ImageData
import numpy as np

client = TestClient(app)

# validation is independent of data files: FastAPI rejects before the route runs
def test_brightness_out_of_range_422():
    assert client.get("/tiles/rgb/2021/10/335/542.png?brightness=99").status_code == 422
    assert client.get("/tiles/rgb/2021/10/335/542.png?brightness=0.1").status_code == 422

def test_contrast_saturation_out_of_range_422():
    assert client.get("/tiles/rgb/2021/10/335/542.png?contrast=0").status_code == 422
    assert client.get("/tiles/rgb/2021/10/335/542.png?saturation=5").status_code == 422

def test_adjust_defaults_are_noop():
    a = np.arange(12, dtype="uint8").reshape(3, 2, 2)
    img = ImageData(a)
    out = _adjust(img, 1.0, 1.0, 1.0)
    assert np.array_equal(out.array, a)

def test_adjust_brightness_scales():
    a = np.full((3, 2, 2), 100, dtype="uint8")
    out = _adjust(ImageData(a), 1.5, 1.0, 1.0)
    assert int(out.array[0, 0, 0]) == 150

def test_adjust_render_on_fully_valid_tile():
    """Regression: np.clip().astype() collapses an all-False mask to np.ma.nomask
    (scalar); replacing img.array then left _mask shape () and render() 500'd
    when writing it as the alpha band. Interior mosaic tiles are fully valid."""
    img = _adjust(ImageData(np.full((3, 2, 2), 100, dtype="uint8")), 1.5, 1.0, 1.0)
    assert img.array.mask.shape == (3, 2, 2)
    assert img.render(img_format="PNG")

def test_adjust_contrast_about_midpoint():
    a = np.full((3, 2, 2), 100, dtype="uint8")
    out = _adjust(ImageData(a), 1.0, 2.0, 1.0)
    assert int(out.array[0, 0, 0]) == int(round((100 - 127.5) * 2 + 127.5))

def test_adjust_saturation_zero_is_gray():
    a = np.zeros((3, 1, 1), dtype="uint8"); a[0, 0, 0] = 200; a[2, 0, 0] = 50
    out = _adjust(ImageData(a), 1.0, 1.0, 0.0)
    assert len(set(int(v) for v in out.array[:, 0, 0])) == 1
