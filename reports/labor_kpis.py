"""
Labor KPIs — wages and payroll as a share of session revenue

Two ratios Cat asked for (2026-09-22), each at three levels:

    602001 Wages        / Total 401000 Sessions
    Total 602000 Payroll / Total 401000 Sessions

    - per studio
    - consolidated studios, excluding Head Office
    - consolidated studios, including Head Office

Head Office earns no session revenue, so including it moves the numerator only.
That is the point of the third level: the studio ratio is what a manager
controls, the loaded ratio is what the business actually costs.

Source is the accountant's imported package, not Snowflake. Run
`run.py import-financials <xlsx>` first; this reads data/financials/studios_<Mon><Year>/.
Using QuickBooks rather than the rev-rec model is deliberate: these are payroll
ratios and payroll only exists in QuickBooks.

CLI:
    python run.py labor-kpis --month YYYY-MM
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

WAGES = "602001 Wages"
PAYROLL = "Total 602000 Payroll"
SESSIONS = "Total 401000 Sessions"

HEAD_OFFICE = "HO"

STUDIO_NAMES = {
    "BK": "Berkeley", "CC": "Culver City", "CDM": "Corona Del Mar",
    "DN": "Danville", "HO": "Head Office", "LF": "Lafayette",
    "MR": "Marin", "OP": "Ocean Park", "PH": "Presidio Heights",
    "PS": "Pasadena", "RH": "Russian Hill", "SB": "Santa Barbara",
    "SM": "Santa Monica", "WP": "West Portal", "WW": "Westwood",
}


def _month_tag(month: str) -> str:
    """2026-08 -> Aug2026, matching how import-financials names its output."""
    return datetime.strptime(month, "%Y-%m").strftime("%b%Y")


def _month_label(month: str) -> str:
    """2026-08 -> 'Aug 2026', the column header the accountant's file uses."""
    return datetime.strptime(month, "%Y-%m").strftime("%b %Y")


def _read_studio(path: Path) -> dict[str, dict[str, float]]:
    """{account: {month label: value}} for one studio tab."""
    out: dict[str, dict[str, float]] = {}
    with path.open() as fh:
        reader = csv.reader(fh)
        header = next(reader)
        months = header[1:]
        for row in reader:
            if not row or not row[0]:
                continue
            vals = {}
            for i, m in enumerate(months, start=1):
                try:
                    vals[m] = float(row[i])
                except (ValueError, IndexError):
                    vals[m] = 0.0
            # Accounts can repeat across sections; the first occurrence wins,
            # which is the detail line rather than a later subtotal.
            out.setdefault(row[0].strip(), vals)
    return out


def _ratio(numerator: float, denominator: float) -> float | None:
    """None, not zero, when there is no revenue to divide by.

    West Portal carried wages with no session revenue from January to May 2026.
    Returning 0.0 there would read as "no labor cost", which is the opposite of
    the truth, so the caller prints it as not applicable instead.
    """
    if not denominator:
        return None
    return numerator / denominator * 100


def compute(month: str, root: Path | None = None, package: str | None = None) -> dict:
    """Both ratios at all three levels for one month.

    `package` is the imported package to read, as a Mon+Year tag. It defaults to
    the month's own package, but the trend passes the LATEST package for every
    month on purpose: the accountant restates prior months (July 2026 moved
    -$2,854 and January -$7,081 in the August package), and a trend assembled
    from each month's original import would show figures nobody holds any more.
    The newest package is the only one that is currently true for every month
    it covers.
    """
    root = root or Path(__file__).resolve().parent.parent
    tag = package or _month_tag(month)
    label = _month_label(month)
    folder = root / "data" / "financials" / f"studios_{tag}"
    if not folder.exists():
        raise FileNotFoundError(
            f"{folder} not found -- run `python run.py import-financials <xlsx>` first"
        )

    studios, head_office = [], None
    for path in sorted(folder.glob("*.csv")):
        code = path.name.split("_")[0]
        accounts = _read_studio(path)
        if label not in (accounts.get(WAGES) or accounts.get(PAYROLL) or {}):
            continue
        row = {
            "code": code,
            "studio": STUDIO_NAMES.get(code, code),
            "sessions": (accounts.get(SESSIONS) or {}).get(label, 0.0),
            "wages": (accounts.get(WAGES) or {}).get(label, 0.0),
            "payroll": (accounts.get(PAYROLL) or {}).get(label, 0.0),
        }
        row["wages_pct"] = _ratio(row["wages"], row["sessions"])
        row["payroll_pct"] = _ratio(row["payroll"], row["sessions"])
        if code == HEAD_OFFICE:
            head_office = row
        else:
            studios.append(row)

    studios.sort(key=lambda r: -r["sessions"])

    # Dormant sites stay in the consolidated numerator. A studio that pays
    # wages before it opens is a real cost of the estate even though it has no
    # revenue of its own to carry them.
    sess = sum(r["sessions"] for r in studios)
    wag = sum(r["wages"] for r in studios)
    pay = sum(r["payroll"] for r in studios)
    ho_w = head_office["wages"] if head_office else 0.0
    ho_p = head_office["payroll"] if head_office else 0.0

    return {
        "month": month,
        "month_label": label,
        "studios": studios,
        "head_office": head_office,
        "ex_ho": {
            "label": "Studios, excluding Head Office",
            "sessions": sess, "wages": wag, "payroll": pay,
            "wages_pct": _ratio(wag, sess), "payroll_pct": _ratio(pay, sess),
        },
        "inc_ho": {
            "label": "Studios, including Head Office",
            "sessions": sess, "wages": wag + ho_w, "payroll": pay + ho_p,
            "wages_pct": _ratio(wag + ho_w, sess),
            "payroll_pct": _ratio(pay + ho_p, sess),
        },
    }


def trailing(month: str, months_back: int = 8, root: Path | None = None) -> list[dict]:
    """The same figures for each month the imported package covers.

    The accountant's file carries the year to date, so one import gives the
    whole trend without re-reading older packages -- and it carries their
    restatements too, which is what we want the trend to show.
    """
    root = root or Path(__file__).resolve().parent.parent
    tag = _month_tag(month)
    folder = root / "data" / "financials" / f"studios_{tag}"
    sample = next(iter(sorted(folder.glob("*.csv"))), None)
    if sample is None:
        return []
    with sample.open() as fh:
        labels = next(csv.reader(fh))[1:]

    out = []
    for lab in labels[-months_back:]:
        try:
            m = datetime.strptime(lab, "%b %Y").strftime("%Y-%m")
        except ValueError:
            continue
        try:
            out.append(compute(m, root=root, package=tag))
        except FileNotFoundError:
            continue
    return out


def payload(month: str, root: Path | None = None) -> dict:
    """Portal payload: current month plus the year-to-date trend."""
    series = trailing(month, months_back=12, root=root)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "month": month,
        "current": compute(month, root=root),
        "trend": [
            {
                "month": s["month"],
                "label": s["month_label"],
                "ex_ho_wages_pct": s["ex_ho"]["wages_pct"],
                "ex_ho_payroll_pct": s["ex_ho"]["payroll_pct"],
                "inc_ho_wages_pct": s["inc_ho"]["wages_pct"],
                "inc_ho_payroll_pct": s["inc_ho"]["payroll_pct"],
                "studios": {
                    r["code"]: {
                        "wages_pct": r["wages_pct"],
                        "payroll_pct": r["payroll_pct"],
                    } for r in s["studios"]
                },
            } for s in series
        ],
    }


def write_payload(month: str, root: Path | None = None) -> Path:
    root = root or Path(__file__).resolve().parent.parent
    out = root / "dashboard" / "data" / "labor_kpis.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload(month, root=root), indent=2))
    return out


# ---------------------------------------------------------------------------
# PDF, for the monthly email to Cat
# ---------------------------------------------------------------------------
def _pct(v) -> str:
    return "n/a" if v is None else f"{v:.1f}%"


def _matrix(series: list[dict], field: str) -> tuple[list[list[str]], int]:
    """Studios down, months across, for one ratio.

    A matrix rather than a twelve-line chart: twelve studios on one set of axes
    is unreadable, and the question here is "which site, which month", which a
    reader answers by scanning a row. The two consolidated lines close it.
    """
    labels = [s["month_label"].replace(" 20", " '") for s in series]
    head = ["Studio"] + labels
    by_code: dict[str, dict] = {}
    order: list[str] = []
    for s in series:
        for r in s["studios"]:
            if r["code"] not in by_code:
                by_code[r["code"]] = {"studio": r["studio"]}
                order.append(r["code"])
            by_code[r["code"]][s["month"]] = r[field]
    # Newest month first, so the table opens on what matters now.
    order.sort(key=lambda c: -(next((r["sessions"] for r in series[-1]["studios"]
                                     if r["code"] == c), 0)))
    rows, raw = [head], [[None] * len(head)]
    for code in order:
        rec = by_code[code]
        vals = [rec.get(s["month"]) for s in series]
        rows.append([rec["studio"]] + [_pct(v) for v in vals])
        raw.append([None] + vals)
    for key in ("ex_ho", "inc_ho"):
        vals = [s[key][field] for s in series]
        rows.append([series[-1][key]["label"].replace("Studios, ", "").capitalize()]
                    + [_pct(v) for v in vals])
        raw.append([None] + vals)
    return rows, raw


# Fixed anchors, not a scale derived from the table.
#
# Two reasons. A recurring report has to mean the same thing every month: with a
# relative scale a studio's colour changes when *other* studios change, which is
# unreadable month to month. And the whole point of this table is that studios
# are comparable in absolute terms -- scaling each row to itself would make
# Santa Barbara, which has been over 100 percent all year, look like it has good
# months and bad ones.
#
# Anchors sit either side of the observed middle (wages median 53.6, payroll
# 62.3 across Jan-Aug 2026), so the consolidated lines land mid-scale and a
# studio has to be genuinely out of line to read red.
HEAT_ANCHORS = {
    "wages_pct": (35.0, 55.0, 75.0),
    "payroll_pct": (45.0, 65.0, 85.0),
}


def _heat(value, field: str):
    """Green at the good anchor through white to red at the bad one."""
    from reportlab.lib import colors

    if value is None:
        return None
    good, mid, bad = HEAT_ANCHORS[field]
    if value <= mid:
        t = max(0.0, (value - good) / (mid - good))      # 0 at good, 1 at mid
        r = 0.804 + (1.0 - 0.804) * t
        g = 0.878 + (1.0 - 0.878) * t
        b = 0.847 + (1.0 - 0.847) * t
    else:
        t = min(1.0, (value - mid) / (bad - mid))        # 0 at mid, 1 at bad
        r = 1.0
        g = 1.0 - (1.0 - 0.769) * t
        b = 1.0 - (1.0 - 0.741) * t
    return colors.Color(r, g, b)


def _trend_chart(series: list[dict], path: Path) -> Path:
    """The aggregate ratios only. Four readable lines instead of twenty-eight."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = [s["month_label"].replace(" 20", " '") for s in series]
    x = range(len(series))
    fig, ax = plt.subplots(figsize=(7.0, 2.6))
    for key, field, color, style, name in (
        ("ex_ho", "payroll_pct", "#1f6f5c", "-", "Payroll %, ex Head Office"),
        ("inc_ho", "payroll_pct", "#1f6f5c", "--", "Payroll %, inc Head Office"),
        ("ex_ho", "wages_pct", "#8a5c15", "-", "Wages %, ex Head Office"),
        ("inc_ho", "wages_pct", "#8a5c15", "--", "Wages %, inc Head Office"),
    ):
        ax.plot(x, [s[key][field] for s in series], style, color=color,
                linewidth=1.6, label=name)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=7.5)
    ax.tick_params(axis="both", length=0, labelsize=7.5, colors="#5b6b70")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.yaxis.grid(True, color="#dbe4e1", linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#c2cecb")
    ax.legend(fontsize=7, frameon=False, ncol=2, loc="upper left")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def generate_pdf(month: str, root: Path | None = None) -> Path:
    """One page: both ratios at all three levels, plus the year-to-date trend."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                    TableStyle)

    root = root or Path(__file__).resolve().parent.parent
    d = compute(month, root=root)
    series = trailing(month, months_back=12, root=root)

    out_dir = root / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"Mighty Pilates Labor KPIs {d['month_label'].replace(' ','')}.pdf"

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=15, spaceAfter=2)
    sub = ParagraphStyle("sub", parent=styles["Normal"], fontSize=9,
                         textColor=colors.HexColor("#5b6b70"), spaceAfter=10)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=10.5,
                        spaceBefore=12, spaceAfter=4)
    note = ParagraphStyle("note", parent=styles["Normal"], fontSize=7.6,
                          textColor=colors.HexColor("#5b6b70"), leading=10.5)

    ACCENT = colors.HexColor("#1f6f5c")
    LINE = colors.HexColor("#c2cecb")

    def table(data, widths, total_rows=(), heat=None, heat_field=None):
        t = Table(data, colWidths=widths, hAlign="LEFT")
        style = [
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#5b6b70")),
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, LINE),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#f7faf9")]),
        ]
        for r in total_rows:
            style += [("FONTNAME", (0, r), (-1, r), "Helvetica-Bold"),
                      ("LINEABOVE", (0, r), (-1, r), 0.8, LINE)]
        if heat is not None:
            # After the zebra striping and the total-row rules, so the shading
            # is what the eye actually sees in those cells.
            for ri, row in enumerate(heat):
                for ci, val in enumerate(row):
                    c = _heat(val, heat_field)
                    if c is not None:
                        style.append(("BACKGROUND", (ci, ri), (ci, ri), c))
        t.setStyle(TableStyle(style))
        return t

    story = [
        Paragraph("Labor KPIs", h1),
        Paragraph(
            f"Mighty Pilates &middot; {d['month_label']} &middot; "
            "wages and payroll as a share of session revenue", sub),
    ]

    # --- by studio ---------------------------------------------------------
    rows = [["Studio", "Sessions", "Wages", "Wages %", "Payroll", "Payroll %"]]
    for r in d["studios"]:
        rows.append([r["studio"], f"{r['sessions']:,.0f}", f"{r['wages']:,.0f}",
                     _pct(r["wages_pct"]), f"{r['payroll']:,.0f}",
                     _pct(r["payroll_pct"])])
    ex, inc, ho = d["ex_ho"], d["inc_ho"], d["head_office"]
    if ho:
        rows.append(["Head Office", "\u2014", f"{ho['wages']:,.0f}", "n/a",
                     f"{ho['payroll']:,.0f}", "n/a"])
    rows.append(["Studios, excluding Head Office", f"{ex['sessions']:,.0f}",
                 f"{ex['wages']:,.0f}", _pct(ex["wages_pct"]),
                 f"{ex['payroll']:,.0f}", _pct(ex["payroll_pct"])])
    rows.append(["Studios, including Head Office", f"{inc['sessions']:,.0f}",
                 f"{inc['wages']:,.0f}", _pct(inc["wages_pct"]),
                 f"{inc['payroll']:,.0f}", _pct(inc["payroll_pct"])])
    n = len(rows)
    story += [Paragraph("By studio", h2),
              table(rows, [2.0*inch, 0.95*inch, 0.9*inch, 0.75*inch, 0.9*inch,
                           0.8*inch],
                    total_rows=(n - 2, n - 1))]

    story += [Spacer(1, 6), Paragraph(
        "Wages is account 602001. Payroll is Total 602000, which carries wages plus "
        "taxes, benefits and processing fees. Both are divided by Total 401000 Sessions "
        "for the same entity, so a studio's ratio is what that studio earns against what "
        "it pays. Head Office earns no session revenue, so the including-Head-Office "
        "lines add its payroll to the numerator over the same studio revenue: the first "
        "consolidated line is what the studios control, the second is what the business "
        "actually costs. A studio with wages and no session revenue shows n/a rather "
        "than zero, and its wages still count in the consolidated totals. "
        "Figures come from the accountant's monthly package, and every month is read "
        "from the latest package, so prior months reflect any restatements.", note)]

    # --- trend -------------------------------------------------------------
    from reportlab.platypus import Image, PageBreak
    import tempfile

    chart_path = Path(tempfile.gettempdir()) / f"labor_kpi_trend_{month}.png"
    _trend_chart(series, chart_path)
    story += [Paragraph("Year to date, consolidated", h2),
              Image(str(chart_path), width=7.0*inch, height=2.6*inch)]

    story += [PageBreak(),
              Paragraph("Wages as a share of session revenue, by studio", h2)]
    wrows, wraw = _matrix(series, "wages_pct")
    mw = [1.45*inch] + [0.68*inch] * (len(wrows[0]) - 1)
    story += [table(wrows, mw, total_rows=(len(wrows) - 2, len(wrows) - 1),
                    heat=wraw, heat_field="wages_pct")]

    story += [Paragraph("Payroll as a share of session revenue, by studio", h2)]
    prows, praw = _matrix(series, "payroll_pct")
    story += [table(prows, mw, total_rows=(len(prows) - 2, len(prows) - 1),
                    heat=praw, heat_field="payroll_pct")]
    story += [Spacer(1, 4), Paragraph(
        "Shading is on a fixed scale so a cell means the same thing every month: green at "
        f"{HEAT_ANCHORS['wages_pct'][0]:.0f} percent of session revenue for wages and "
        f"{HEAT_ANCHORS['payroll_pct'][0]:.0f} for payroll, through white at the middle, to red at "
        f"{HEAT_ANCHORS['wages_pct'][2]:.0f} and {HEAT_ANCHORS['payroll_pct'][2]:.0f}. "
        "It is not scaled to each row or to this month's spread, so studios stay comparable "
        "with each other and with prior packages.", note)]



    SimpleDocTemplate(str(path), pagesize=letter,
                      leftMargin=0.6*inch, rightMargin=0.6*inch,
                      topMargin=0.6*inch, bottomMargin=0.6*inch,
                      title=f"Mighty Pilates Labor KPIs {d['month_label']}").build(story)
    return path
