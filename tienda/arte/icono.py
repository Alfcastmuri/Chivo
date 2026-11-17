from PIL import Image, ImageDraw, ImageFilter
def icono(t, sombra=True):
    import numpy as np
    S = max(4, -(-t * 2 // 256)); N = 256 * S; k = S
    im = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    # degradado diagonal
    a, b = np.array((107, 160, 245)), np.array((36, 86, 192))
    yy, xx = np.mgrid[0:N, 0:N]
    f = ((xx + yy) / (2 * N))[..., None]
    arr = (a + (b - a) * f).astype("uint8")
    g = Image.fromarray(np.dstack([arr, np.full((N, N), 255, "uint8")]), "RGBA")
    m = Image.new("L", (N, N), 0); ImageDraw.Draw(m).rounded_rectangle((8*k, 8*k, 248*k, 248*k), 52*k, fill=255)
    im.paste(g, (0, 0), m)
    d = ImageDraw.Draw(im)
    if sombra:
        sh = Image.new("RGBA", (N, N), (0, 0, 0, 0)); ImageDraw.Draw(sh).rounded_rectangle((55*k, 100*k, 201*k, 192*k), 16*k, fill=(10, 30, 90, 55))
        sh = sh.filter(ImageFilter.GaussianBlur(8*k)); im.alpha_composite(sh)
    d.rounded_rectangle((55*k, 74*k, 132*k, 112*k), 14*k, fill=(224, 236, 255, 255))
    d.rounded_rectangle((55*k, 93*k, 201*k, 186*k), 16*k, fill=(255, 255, 255, 255))
    for y in (118, 136, 156):
        x2 = 170 if y != 156 else 140
        d.rounded_rectangle((75*k, (y-4)*k, x2*k, (y+4)*k), 4*k, fill=(47, 111, 222, 255))
    cx, cy, r = 177, 164, 12
    d.ellipse(((cx-r)*k, (cy-r)*k, (cx+r)*k, (cy+r)*k), fill=(36, 86, 192, 255))
    d.line([((cx-6)*k, cy*k), ((cx-2)*k, (cy+4)*k), ((cx+6)*k, (cy-4)*k)], fill=(255, 255, 255, 255), width=3*k, joint="curve")
    return im.resize((t, t), Image.LANCZOS)
if __name__ == "__main__":
    a = icono(256); o = Image.open("/home/user/chivo/recursos/gestor.png").convert("RGBA")
    c = Image.new("RGBA", (512, 256), "white"); c.alpha_composite(o, (0, 0)); c.alpha_composite(a, (256, 0)); c.save("comparar.png")
