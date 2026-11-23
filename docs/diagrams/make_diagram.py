"""Hand-laid system diagram for Second Look (SVG -> PNG). Coordinates are fixed so loops do not cross boxes."""
from html import escape

W, H = 1520, 640
out = []
F = "DejaVu Sans, Arial, sans-serif"

# palette
BLUE, BLUE_F, BLUE_T = "#185FA5", "#E6F1FB", "#0C447C"
PURP, PURP_F, PURP_T = "#534AB7", "#EEEDFE", "#3C3489"
GREEN, GREEN_F, GREEN_T = "#0F6E56", "#E1F5EE", "#085041"
AMBER, AMBER_F = "#854F0B", "#FAEEDA"
GREY, GREY_T = "#888780", "#5F5E5A"
RED = "#A32D2D"
INK = "#2C2C2A"


def band(x, y, w, h, fill, stroke, label, tcol, where="tl"):
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{fill}" stroke="{stroke}" stroke-width="1"/>')
    tx, anchor = (x + 12, "start") if where == "tl" else (x + w - 12, "end")
    out.append(f'<text x="{tx}" y="{y+18}" text-anchor="{anchor}" font-family="{F}" font-size="13" '
               f'fill="{tcol}">{escape(label)}</text>')


def box(x, y, w, h, lines, kind="impl", stroke=BLUE, fill="#FFFFFF", bold_first=True):
    if kind == "sim":
        stroke, fill, dash = AMBER, AMBER_F, ' stroke-dasharray="6 4"'
    elif kind == "plan":
        stroke, fill, dash = GREY, "#FFFFFF", ' stroke-dasharray="2 3"'
    else:
        dash = ""
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="1.4"{dash}/>')
    n = len(lines)
    for i, line in enumerate(lines):
        ty = y + h / 2 + (i - (n - 1) / 2) * 15 + 4
        weight = "bold" if (i == 0 and bold_first) else "normal"
        col = GREY_T if kind == "plan" else INK
        size = 12.5 if i == 0 else 11
        out.append(f'<text x="{x+w/2}" y="{ty}" text-anchor="middle" font-family="{F}" font-size="{size}" '
                   f'font-weight="{weight}" fill="{col}">{escape(line)}</text>')


def arrow(d, color=INK, width=1.4, dash=None):
    da = f' stroke-dasharray="{dash}"' if dash else ""
    mid = {"#2C2C2A": "ink", RED: "red", AMBER: "amber", BLUE: "blue", GREY: "grey"}[color]
    out.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}"{da} marker-end="url(#a-{mid})"/>')


def label(x, y, text, color=INK, size=11, anchor="middle"):
    for i, line in enumerate(text.split("\n")):
        out.append(f'<text x="{x}" y="{y + i*13}" text-anchor="{anchor}" font-family="{F}" font-size="{size}" '
                   f'fill="{color}">{escape(line)}</text>')


# ---------- header ----------
out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">')
out.append('<defs>' + "".join(
    f'<marker id="a-{n}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
    f'<path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>'
    for n, c in [("ink", INK), ("red", RED), ("amber", AMBER), ("blue", BLUE), ("grey", GREY)]) + '</defs>')
out.append(f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>')
out.append('<g transform="translate(0,-55)">')

# ---------- bands ----------
Y0, BH = 150, 175
band(120, Y0, 290, BH, "#F5F9FD", BLUE, "Interface: input", BLUE_T)
band(425, Y0, 300, BH, PURP_F, PURP, "Model side (probabilistic)", PURP_T)
band(740, Y0, 425, BH, GREEN_F, GREEN, "Code (checks)", GREEN_T, "tr")
band(1180, Y0, 320, BH, "#F5F9FD", BLUE, "Interface: output and control", BLUE_T)

# ---------- main row ----------
RY, RH = 185, 60          # row top, height
CY = RY + RH / 2
out.append(f'<ellipse cx="62" cy="{CY}" rx="46" ry="26" fill="#F1EFE8" stroke="{GREY_T}" stroke-width="1.4"/>')
label(62, CY + 4, "Person", INK, 12.5)

box(132, RY, 110, RH, ["Profile form", "goal · horizon", "risk · amount"])
box(268, RY, 130, RH, ["Confirm profile", "\"I understood…\"", "+ question · H0"])
box(440, RY, 130, RH, ["Prompt builder", "instruction v4 +", "profile, funds, question"], stroke=PURP)
box(598, RY, 112, RH, ["LLM", "Groq / Gemini", "verified models"], stroke=PURP, fill="#CECBF6")
box(758, RY, 112, RH, ["Validator", "V1–V6", "shape, not truth"], stroke=GREEN)
box(902, RY, 112, RH, ["Checker", "R1–R6", "profile vs plan"], stroke=GREEN)
box(1044, RY, 108, RH, ["Hedge", "fixed templates", ""], stroke=GREEN)
box(1192, RY, 130, RH, ["Plan cards", "badge · hedge", "Why? evidence"])
box(1352, RY, 136, RH, ["User control", "Remove · Keep · Undo", "Suggest again · Accept"])

# second-row boxes inside bands
box(598, 268, 112, 44, ["Replay", "stored outputs"], kind="sim")
box(1192, 268, 130, 44, ["Your request", "panel (R6)"])

# ---------- main flow arrows ----------
arrow(f"M108,{CY} L130,{CY}"); label(119, CY - 8, "fills", INK, 10)
arrow(f"M242,{CY} L266,{CY}")
arrow(f"M398,{CY} L438,{CY}")
arrow(f"M570,{CY} L596,{CY}")
arrow(f"M710,{CY} L756,{CY}"); label(733, CY - 8, "JSON", INK, 10)
arrow(f"M870,{CY} L900,{CY}")
arrow(f"M1014,{CY} L1042,{CY}")
arrow(f"M1152,{CY} L1190,{CY}")
arrow(f"M1322,{CY} L1350,{CY}"); label(1336, CY - 8, "decides", INK, 10)
arrow("M570,238 C585,280 585,290 596,290", AMBER, 1.2, "5 4")     # prompt -> replay
arrow("M710,290 C735,290 745,260 760,246", AMBER, 1.2, "5 4")     # replay -> validator
arrow("M1014,235 C1100,250 1150,290 1190,290")                    # checker -> R6 panel

# ---------- loops above ----------
arrow("M814,185 C814,90 333,90 333,183", AMBER, 1.6)
label(573, 105, "profile change proposed → user confirms or keeps (repair turn)", AMBER, 11)
arrow("M1420,185 C1420,95 958,95 958,183", BLUE, 1.6)
label(1189, 110, "Remove → remaining plan re-checked", BLUE, 11)

# ---------- loops below ----------
arrow("M800,245 C800,395 505,395 505,247", RED, 1.6)
label(812, 290, "invalid → retry once,\nthen decline", RED, 11, "start")
arrow("M1462,245 C1462,490 470,490 470,247", BLUE, 1.6)
label(965, 458, "Suggest again (failed rules sent back) · Keep profile (enforced by V6)", BLUE, 11)

# ---------- data and evaluation ----------
DY = 530
band(120, DY - 28, 760, 108, "#FAFAF8", GREY, "Data", GREY_T)
band(900, DY - 28, 600, 108, "#FAFAF8", GREY, "Evaluation", GREY_T)
box(140, DY, 150, 44, ["Fund list", "16 fictional funds"], kind="sim")
box(320, DY, 150, 44, ["Verified models", "working_models.json"])
box(500, DY, 150, 44, ["Session logs", "flags + actions"])
box(690, DY, 150, 44, ["Live fund data", ""], kind="plan")
box(920, DY, 170, 44, ["Tests", "rules + seeded errors"])
box(1110, DY, 170, 44, ["Batch evaluation", "prompt v1 vs v4"])
box(1300, DY, 180, 44, ["User study", "checks vs disclaimer"], kind="plan")
label(215, DY + 64, "→ prompt builder, checker", GREY_T, 10)
label(395, DY + 64, "→ model picker", GREY_T, 10)
label(575, DY + 64, "← every user action", GREY_T, 10)
label(765, DY + 64, "→ would replace fund list", GREY_T, 10)
label(1005, DY + 64, "→ checker, validator, UI", GREY_T, 10)
label(1195, DY + 64, "→ same pipeline, live model", GREY_T, 10)
label(1390, DY + 64, "← logs + display modes", GREY_T, 10)

# ---------- legend ----------
LY = 668
out.append(f'<rect x="120" y="{LY-12}" width="26" height="16" rx="4" fill="#FFFFFF" stroke="{BLUE}" stroke-width="1.4"/>')
label(152, LY + 1, "implemented", INK, 11, "start")
out.append(f'<rect x="250" y="{LY-12}" width="26" height="16" rx="4" fill="{AMBER_F}" stroke="{AMBER}" stroke-width="1.4" stroke-dasharray="6 4"/>')
label(282, LY + 1, "simulated", INK, 11, "start")
out.append(f'<rect x="365" y="{LY-12}" width="26" height="16" rx="4" fill="#FFFFFF" stroke="{GREY}" stroke-width="1.4" stroke-dasharray="2 3"/>')
label(397, LY + 1, "planned", INK, 11, "start")
for x, col, txt in [(490, INK, "main flow"), (600, RED, "error path"), (715, AMBER, "repair"), (805, BLUE, "user control")]:
    arrow(f"M{x},{LY-4} L{x+28},{LY-4}", col, 1.6)
    label(x + 34, LY + 1, txt, INK, 11, "start")
label(W - 20, LY + 1, "Second Look: components, flows and AI behaviour", GREY_T, 11, "end")

out.append("</g>")
out.append("</svg>")
open("system_diagram.svg", "w").write("\n".join(out))
print("ok")
