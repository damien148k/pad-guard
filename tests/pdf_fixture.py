"""Small broadcaster-like PDF for the draft-profile tests, generated with reportlab (no PDF in the repo).

Page 1: true peak and loudness sentences, references to two norms. Page 2: timecode sentence and a table (frame rate,
sample rate). Page 3: a drawing only, no text layer.
"""

from __future__ import annotations

from pathlib import Path

PAGE1 = [
    "Consignes techniques de la chaîne de test, version 1.",
    "Mixages : le niveau des crêtes, mesuré en True Peak, ne doit pas dépasser -1 dBTP.",
    "Programmes de durée supérieure à 2'00 : la valeur cible du Loudness intégré est de -23 LUFS",
    "avec une tolérance de ± 1 LU.",
    "Le signal d'alignement 1.000 Hz est à -18 dBFS.",
    "Les mesures de loudness sont conformes à la recommandation EBU R128.",
    "Le loudness des programmes courts respecte la recommandation CST-RT-017.",
]
PAGE2 = ["Le timecode de la première image du programme est 10:00:00:00.", "Caractéristiques du fichier :"]
TABLE = [["Paramètre", "Valeur"], ["Fréquence image", "25 images par seconde"], ["Audio", "48 kHz, 24 bits"]]


def make(path: Path) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import Table
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    y = 780
    for line in PAGE1:
        c.drawString(60, y, line)
        y -= 20
    c.showPage()
    y = 780
    for line in PAGE2:
        c.drawString(60, y, line)
        y -= 20
    table = Table(TABLE)
    table.setStyle([("GRID", (0, 0), (-1, -1), 0.5, "black")])
    w, h = table.wrapOn(c, 400, 200)
    table.drawOn(c, 60, y - h)
    c.showPage()
    c.rect(100, 400, 300, 200, fill=1)  # an image-like page with no text
    c.showPage()
    c.save()
    return path
