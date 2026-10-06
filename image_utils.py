from __future__ import annotations

import base64
from io import BytesIO
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_PROFILE_PHOTO_BYTES = 1024 * 1024  # 1024 KB (1 MB)


def processar_foto_perfil(data: bytes) -> str:
    """Valida, faz corte quadrado centralizado 160x160 e gera base64 leve de foto de perfil."""
    if not data or len(data) > MAX_PROFILE_PHOTO_BYTES:
        raise ValueError("A foto de perfil deve ter no máximo 1024 KB (1 MB).")
    try:
        with Image.open(BytesIO(data), formats=("JPEG", "PNG", "WEBP")) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode in {"RGBA", "LA"}:
                rgba = img.convert("RGBA")
                bg = Image.new("RGB", rgba.size, "white")
                bg.paste(rgba, mask=rgba.getchannel("A"))
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")

            # Recorte inteligente centralizado 1:1 e redimensionamento proporcional
            cropped = ImageOps.fit(img, (160, 160), Image.Resampling.LANCZOS)
            buf = BytesIO()
            cropped.save(buf, format="JPEG", quality=85, optimize=True)
            encoded = base64.b64encode(buf.getvalue()).decode("ascii")
            return f"data:image/jpeg;base64,{encoded}"
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Formato de imagem inválido para o perfil. Envie JPG, PNG ou WEBP.") from exc
