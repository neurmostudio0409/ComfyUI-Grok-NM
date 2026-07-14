"""
影像 / 影片工具
ComfyUI IMAGE tensor([B,H,W,C] float 0~1)與 base64 / URL 互轉、影片存檔。
torch / PIL / numpy 延遲匯入,讓 CI(無 torch 環境)也能載入本模組。
"""

import base64
import os
import time

from ..config.settings import MAX_IMAGE_INPUT_BYTES, PLUGIN_DIR

_DATA_URL_PREFIX = "data:"


def strip_data_url(s: str) -> str:
    """把 data:image/png;base64,xxxx 剝成純 base64;非 data URL 原樣回傳"""
    if s.startswith(_DATA_URL_PREFIX) and "," in s:
        return s.split(",", 1)[1]
    return s


# ----------------------------------------------------------------------
# IMAGE tensor → base64 PNG
# ----------------------------------------------------------------------
def tensor_to_png_b64(image, index: int = 0, max_bytes: int = MAX_IMAGE_INPUT_BYTES) -> str:
    """
    取 IMAGE batch 的第 index 張轉成 PNG base64。
    超過 max_bytes(視覺輸入 20 MiB 上限)時拋 ValueError。
    """
    import io

    import numpy as np
    from PIL import Image

    img = image[index] if image.dim() == 4 else image
    arr = (img.cpu().numpy().clip(0.0, 1.0) * 255.0).astype(np.uint8)

    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    data = buf.getvalue()
    if max_bytes and len(data) > max_bytes:
        raise ValueError(
            f"圖片 PNG 編碼後 {len(data) / (1 << 20):.1f} MiB,"
            f"超過 xAI 視覺輸入上限 {max_bytes / (1 << 20):.0f} MiB")
    return base64.b64encode(data).decode("utf-8")


def batch_to_png_b64_list(image, limit: int = 8) -> list:
    """整個 IMAGE batch 轉成 base64 列表(最多 limit 張)"""
    count = image.shape[0] if image.dim() == 4 else 1
    if count > limit:
        print(f"⚠️ batch 有 {count} 張,只送前 {limit} 張給 Grok")
        count = limit
    return [tensor_to_png_b64(image, i) for i in range(count)]


# ----------------------------------------------------------------------
# base64 / URL → IMAGE tensor
# ----------------------------------------------------------------------
def b64_or_url_to_tensor(item: str):
    """
    b64_json 字串、data URL 或 http(s) URL 轉成 [1,H,W,C] float tensor
    """
    import io

    import numpy as np
    import torch
    from PIL import Image

    if item.startswith("http://") or item.startswith("https://"):
        import requests
        resp = requests.get(item, timeout=120)
        resp.raise_for_status()
        raw = resp.content
    else:
        raw = base64.b64decode(strip_data_url(item))

    pil = Image.open(io.BytesIO(raw)).convert("RGB")
    arr = np.asarray(pil).astype(np.float32) / 255.0
    return torch.from_numpy(arr).unsqueeze(0)


def items_to_image_batch(items: list):
    """
    多張圖組成 IMAGE batch;尺寸不一時以第一張為準縮放。
    """
    import torch
    from PIL import Image

    tensors = [b64_or_url_to_tensor(item) for item in items if item]
    if not tensors:
        raise ValueError("沒有任何圖片可以載入")

    h, w = tensors[0].shape[1], tensors[0].shape[2]
    aligned = []
    for t in tensors:
        if t.shape[1] != h or t.shape[2] != w:
            import numpy as np
            arr = (t[0].numpy() * 255.0).astype("uint8")
            pil = Image.fromarray(arr).resize((w, h), Image.LANCZOS)
            t = torch.from_numpy(
                (np.asarray(pil).astype("float32") / 255.0)).unsqueeze(0)
        aligned.append(t)
    return torch.cat(aligned, dim=0)


# ----------------------------------------------------------------------
# 影片輸出
# ----------------------------------------------------------------------
def get_output_dir(subfolder: str = "grok") -> str:
    """ComfyUI output 目錄下的子資料夾;不在 ComfyUI 環境時退回套件內 output/"""
    try:
        import folder_paths
        base = folder_paths.get_output_directory()
    except Exception:
        base = os.path.join(PLUGIN_DIR, "output")
    path = os.path.join(base, subfolder)
    os.makedirs(path, exist_ok=True)
    return path


def make_video_path(prefix: str = "grok_video", ext: str = "mp4") -> str:
    """在輸出資料夾產生帶時間戳的影片路徑"""
    filename = f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}.{ext}"
    return os.path.join(get_output_dir(), filename)
