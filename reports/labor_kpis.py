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

    def table(data, widths, total_rows=()):
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
                      ("LINEABOVE", (0, r), (-1, r), 0.8, LINE),
                      ("BACKGROUND", (0, r), (-1, r), colors.white)]
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

    # --- trend -------------------------------------------------------------
    trows = [["Month", "Wages % ex HO", "Payroll % ex HO",
              "Wages % inc HO", "Payroll % inc HO"]]
    for s in series:
        trows.append([s["month_label"],
                      _pct(s["ex_ho"]["wages_pct"]), _pct(s["ex_ho"]["payroll_pct"]),
                      _pct(s["inc_ho"]["wages_pct"]), _pct(s["inc_ho"]["payroll_pct"])])
    story += [Paragraph("Month by month", h2),
              table(trows, [1.3*inch, 1.15*inch, 1.25*inch, 1.2*inch, 1.3*inch])]

    story += [Spacer(1, 12), Paragraph(
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

    SimpleDocTemplate(str(path), pagesize=letter,
                      leftMargin=0.6*inch, rightMargin=0.6*inch,
                      topMargin=0.6*inch, bottomMargin=0.6*inch,
                      title=f"Mighty Pilates Labor KPIs {d['month_label']}").build(story)
    return path
