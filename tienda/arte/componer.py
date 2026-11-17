import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from icono import icono
F = "/usr/share/fonts/opentype/inter/"
CAP = "/tmp/claude-0/cap/v6/"
def fondo(w, h):
    yy, xx = np.mgrid[0:h, 0:w]
    a, b = np.array((14, 19, 34)), np.array((24, 38, 78))
    f = (yy / h * 0.75 + xx / w * 0.25)[..., None]
    arr = a + (b - a) * f
    # brillo azul arriba
    cx, cy = w / 2, h * 0.22
    r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / (max(w, h) * 0.55)
    glow = np.clip(1 - r, 0, 1)[..., None] ** 2
    arr = arr + glow * np.array((47, 111, 222)) * 0.55
    return Image.fromarray(np.clip(arr, 0, 255).astype("uint8")).convert("RGBA")
def texto_centrado(d, w, y, t, fuente, color):
    x = (w - d.textlength(t, font=fuente)) / 2
    d.text((x, y), t, font=fuente, fill=color)
def captura(ruta, ancho, radio):
    c = Image.open(ruta).convert("RGBA")
    c = c.resize((ancho, int(c.height * ancho / c.width)), Image.LANCZOS)
    m = Image.new("L", c.size, 0); ImageDraw.Draw(m).rounded_rectangle((0, 0, c.width, c.height), radio, fill=255)
    c.putalpha(m); return c
def pegar_con_sombra(base, img, x, y, desenfoque):
    s = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sm = Image.new("RGBA", img.size, (0, 0, 0, 170)); sm.putalpha(img.getchannel("A").point(lambda v: v * 170 // 255))
    s.alpha_composite(sm, (x, y + desenfoque // 2)); s = s.filter(ImageFilter.GaussianBlur(desenfoque))
    base.alpha_composite(s); base.alpha_composite(img, (x, y))
    borde = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(borde).rounded_rectangle((x, y, x + img.width - 1, y + img.height - 1), 28, outline=(255, 255, 255, 40), width=3)
    base.alpha_composite(borde)
LEMA = "Tu computadora, en orden. Sola."
def poster(w=1440, h=2160):
    im = fondo(w, h); d = ImageDraw.Draw(im)
    ic = icono(560); im.alpha_composite(ic, ((w - 560) // 2, 210))
    texto_centrado(d, w, 840, "GESTOR", ImageFont.truetype(F + "InterDisplay-ExtraBold.otf", 200), (255, 255, 255))
    texto_centrado(d, w, 1080, LEMA, ImageFont.truetype(F + "InterDisplay-Medium.otf", 66), (190, 205, 235))
    c = captura(CAP + "01-inicio.png", 1300, 30)
    pegar_con_sombra(im, c, (w - 1300) // 2, 1300, 40)
    return im.convert("RGB")
def caja(w=2160, h=2160):
    im = fondo(w, h); d = ImageDraw.Draw(im)
    ic = icono(520); im.alpha_composite(ic, ((w - 520) // 2, 170))
    texto_centrado(d, w, 740, "GESTOR", ImageFont.truetype(F + "InterDisplay-ExtraBold.otf", 210), (255, 255, 255))
    texto_centrado(d, w, 990, LEMA, ImageFont.truetype(F + "InterDisplay-Medium.otf", 72), (190, 205, 235))
    c = captura(CAP + "01-inicio.png", 1880, 34)
    pegar_con_sombra(im, c, (w - 1880) // 2, 1210, 46)
    return im.convert("RGB")
if __name__ == "__main__":
    import os; o = "/mnt/project-files/gestor/arte-store/"; os.makedirs(o, exist_ok=True)
    p = poster(); p.save(o + "poster-1440x2160.png"); p.resize((720, 1080), Image.LANCZOS).save(o + "poster-720x1080.png")
    b = caja(); b.save(o + "caja-2160x2160.png"); b.resize((1080, 1080), Image.LANCZOS).save(o + "caja-1080x1080.png")
    l = icono(2160); l.save(o + "logo-2160x2160.png"); icono(300).save(o + "logo-300x300.png")
    # vista previa
    v = Image.new("RGB", (720 + 1080 + 300 + 40, 1080), (40, 40, 40))
    v.paste(p.resize((720, 1080)), (0, 0)); v.paste(b.resize((1080, 1080)), (740, 0)); v.paste(icono(300), (1840, 0), icono(300))
    v.save("/tmp/claude-0/arte/vista.png")
