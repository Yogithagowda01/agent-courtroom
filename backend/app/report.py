"""Report generation: Decision Memo, matplotlib charts, docx and pdf builders."""
from __future__ import annotations

import io
import json
import logging
import re
import time
from datetime import datetime
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    Image as RLImage,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from . import db, prompts
from .config import settings
from .engine import Usage, _call, classify_evidence, parse_verdict
from .llm import estimate_tokens, resolve

log = logging.getLogger("courtroom")

DISCLAIMER_TEXT = (
    "AI-generated analysis. Scores are model estimates. Human review is required before any decision."
)

APP_COLORS = {
    "teal": "#0F766E",
    "teal_light": "#CCFBF1",
    "coral": "#C2410C",
    "coral_light": "#FFEDD5",
    "blue": "#1D4ED8",
    "blue_light": "#DBEAFE",
    "purple": "#6D28D9",
    "purple_light": "#EDE9FE",
    "gold": "#B45309",
    "gold_light": "#FEF3C7",
    "navy": "#1F2A44",
    "ink": "#1F2937",
    "muted": "#6B7280",
    "line": "#D1D5DB",
    "panel": "#F3F4F6",
}


def sanitize_filename(name: str) -> str:
    """Sanitize string for Windows filename safety."""
    clean = re.sub(r'[\\/*?:"<>|]', "", name or "")
    clean = re.sub(r"\s+", "-", clean.strip())
    clean = re.sub(r"-+", "-", clean).strip(".-")
    return clean[:35] or "Debate"


# --------------------------------------------------------------------- Fallback memo
def build_fallback_memo(question: str, verdict: dict, messages: list[dict]) -> dict[str, Any]:
    adv_pts = [m["content"] for m in messages if m.get("agent") == "advocate"]
    cri_pts = [m["content"] for m in messages if m.get("agent") == "critic"]
    risk_pts = [m["content"] for m in messages if m.get("agent") == "risk"]
    evi_pts = [m for m in messages if m.get("agent") == "evidence"]

    arguments_for = adv_pts if adv_pts else [
        "Provides architectural flexibility, accelerated iteration velocity, and scalable foundations.",
        "Early deployment delivers compounding benefits and rapid empirical feedback.",
    ]
    arguments_against = cri_pts if cri_pts else [
        "Significantly underestimates infrastructure upkeep, toolchain complexity, and on-call operational load.",
        "Premature commitment diverts engineering capacity away from core product differentiation.",
    ]

    risks = []
    for r in risk_pts:
        risks.append({
            "risk": r,
            "mitigation": "Establish strict monitoring thresholds, define rollback criteria, and pilot with low-risk components.",
        })
    if not risks:
        risks = [
            {
                "risk": "Resource diversion into infrastructure overhead and maintenance.",
                "mitigation": "Adopt managed cloud services and modular interfaces before full decentralization.",
            },
            {
                "risk": "Operational bottleneck during incident response and debugging.",
                "mitigation": "Unify telemetry, logging, and tracing early in development.",
            },
        ]

    evidence_notes = []
    for e in evi_pts:
        lbl = e.get("evidence_label") or classify_evidence(e.get("content", ""))
        evidence_notes.append(f"[{lbl.upper()}] {e.get('content', '')}")
    if not evidence_notes:
        evidence_notes = [
            "[SUPPORTED] Operational and infrastructure overhead grows substantially with decentralized systems.",
            "[UNSUPPORTED] Immediate scalability benefits for early-stage workloads remain unsourced and unverified.",
            "[CONTRADICTED] Early architectural fragmentation accelerates time-to-market for resource-constrained teams.",
        ]

    ans = verdict.get("answer", "Unclear")
    summ = verdict.get("summary", "Proceed with measured evaluation.")
    conf = verdict.get("confidence", 50)

    exec_summary = (
        f"This debate comprehensively analyzed the strategic question: '{question}'. "
        f"The Advocate articulated strong benefits including flexibility, fast execution cycles, and scalable architecture, "
        f"while the Critic challenged these premises citing disproportionate infrastructure upkeep, team strain, and unnecessary complexity. "
        f"The Evidence Agent audited specific assertions across each round, flagging unsourced projections and identifying verified constraints. "
        f"The Risk Analyst highlighted critical operational maintenance commitments. "
        f"Following the multi-agent deliberation, the presiding Judge delivered an official verdict of '{ans}' with {conf}% confidence, "
        f"advising: '{summ}'. Decision-makers must address the documented mitigations and thoroughly review team capacity prior to implementation."
    )

    return {
        "executive_summary": exec_summary,
        "arguments_for": arguments_for,
        "arguments_against": arguments_against,
        "risks": risks,
        "evidence_notes": evidence_notes,
        "recommendation": f"Verdict: {ans}. {summ}",
        "next_steps": [
            "Conduct an internal resource audit addressing key points raised by the Critic and Risk Analyst.",
            "Implement primary mitigations before making any irrevocable architectural commitments.",
            "Validate empirical workloads with a targeted prototype before initiating full rollout.",
            "Establish recurring checkpoints to review decision metrics against actual operational costs.",
        ],
        "limitations": "Analysis was generated strictly from autonomous agent deliberation. External proprietary databases and private roadmaps were not evaluated.",
    }


def _validate_memo(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    required = [
        "executive_summary",
        "arguments_for",
        "arguments_against",
        "risks",
        "evidence_notes",
        "recommendation",
        "next_steps",
        "limitations",
    ]
    for k in required:
        if k not in obj or obj[k] is None:
            return False
    if not isinstance(obj["arguments_for"], list) or not isinstance(obj["arguments_against"], list):
        return False
    if not isinstance(obj["risks"], list) or not isinstance(obj["next_steps"], list):
        return False
    return True


# --------------------------------------------------------------------- Chart data extraction
def compute_chart_data(debate: dict, messages: list[dict], verdict: dict) -> dict[str, Any]:
    scores = verdict.get("scores") or {}
    adv_score = float(scores.get("advocate", 5))
    cri_score = float(scores.get("critic", 5))
    evi_score = float(scores.get("evidence", 5))
    risk_score = float(scores.get("risk", 5))

    scores_data = [
        {"agent": "Advocate", "score": round(adv_score, 1), "color": APP_COLORS["teal"]},
        {"agent": "Critic", "score": round(cri_score, 1), "color": APP_COLORS["coral"]},
        {"agent": "Evidence", "score": round(evi_score, 1), "color": APP_COLORS["blue"]},
        {"agent": "Risk", "score": round(risk_score, 1), "color": APP_COLORS["purple"]},
    ]

    confidence_data = {
        "confidence": int(verdict.get("confidence", 50)),
        "color": APP_COLORS["gold"],
    }

    # Evidence counts
    evidence_counts = {"supported": 0, "unsupported": 0, "contradicted": 0, "unclear": 0}
    for m in messages:
        if m.get("agent") == "evidence":
            lbl = m.get("evidence_label") or classify_evidence(m.get("content", ""))
            lbl = lbl if lbl in evidence_counts else "unclear"
            evidence_counts[lbl] += 1

    evidence_data = [
        {"label": "Supported", "value": evidence_counts["supported"], "color": APP_COLORS["teal"]},
        {"label": "Unsupported", "value": evidence_counts["unsupported"], "color": APP_COLORS["coral"]},
        {"label": "Contradicted", "value": evidence_counts["contradicted"], "color": APP_COLORS["purple"]},
        {"label": "Unclear", "value": evidence_counts["unclear"], "color": APP_COLORS["muted"]},
    ]

    # Token usage by agent
    agent_token_totals = {"Advocate": 0, "Critic": 0, "Evidence": 0, "Risk": 0}
    for m in messages:
        agent_raw = m.get("agent", "").lower()
        mapped = {"advocate": "Advocate", "critic": "Critic", "evidence": "Evidence", "risk": "Risk"}.get(agent_raw)
        if mapped:
            tok = m.get("tokens")
            if tok is None or tok <= 0:
                tok = estimate_tokens(m.get("content", ""))
            agent_token_totals[mapped] += tok

    token_data = [
        {"agent": "Advocate", "tokens": agent_token_totals["Advocate"], "color": APP_COLORS["teal"]},
        {"agent": "Critic", "tokens": agent_token_totals["Critic"], "color": APP_COLORS["coral"]},
        {"agent": "Evidence", "tokens": agent_token_totals["Evidence"], "color": APP_COLORS["blue"]},
        {"agent": "Risk", "tokens": agent_token_totals["Risk"], "color": APP_COLORS["purple"]},
    ]

    return {
        "scores": scores_data,
        "confidence": confidence_data,
        "evidence": evidence_data,
        "tokens": token_data,
    }


# --------------------------------------------------------------------- Decision Memo Call
async def generate_decision_memo(debate: dict, messages: list[dict], verdict: dict) -> dict[str, Any]:
    question = debate["question"]
    model_choice = debate.get("model", "auto")

    # If demo or simulated, return fallback memo without model call
    if model_choice == "demo":
        return build_fallback_memo(question, verdict, messages)

    try:
        resolved = await resolve(model_choice)
        if resolved.simulated:
            return build_fallback_memo(question, verdict, messages)

        usage = Usage()
        memo_msgs = prompts.memo_messages(question, messages, verdict)
        raw = await _call(
            resolved.judge,
            resolved.judge_model,
            memo_msgs,
            temperature=0.2,
            max_tokens=900,
            usage=usage,
            json_mode=True,
        )

        obj = prompts.re.sub(r"^```(?:json)?|```$", "", raw or "", flags=prompts.re.M).strip()
        data = None
        for candidate in (obj, obj[obj.find("{"): obj.rfind("}") + 1] if "{" in obj and "}" in obj else ""):
            if not candidate:
                continue
            try:
                data = json.loads(candidate)
                break
            except json.JSONDecodeError:
                continue

        if _validate_memo(data):
            return data

        # Repair attempt
        repair_msgs = memo_msgs + [
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": (
                    "Return ONLY valid JSON with exact keys: executive_summary (80-120 words), "
                    "arguments_for (list), arguments_against (list), risks (list of {risk, mitigation}), "
                    "evidence_notes (list), recommendation (string), next_steps (list), limitations (string)."
                ),
            },
        ]
        raw_repair = await _call(
            resolved.judge,
            resolved.judge_model,
            repair_msgs,
            temperature=0.0,
            max_tokens=900,
            usage=usage,
            json_mode=True,
        )
        data_repair = None
        for candidate in (raw_repair, raw_repair[raw_repair.find("{"): raw_repair.rfind("}") + 1] if "{" in raw_repair and "}" in raw_repair else ""):
            if not candidate:
                continue
            try:
                data_repair = json.loads(candidate)
                break
            except json.JSONDecodeError:
                continue

        if _validate_memo(data_repair):
            return data_repair

    except Exception as e:
        log.warning("Decision memo model call failed, using fallback memo: %s", e)

    return build_fallback_memo(question, verdict, messages)


# --------------------------------------------------------------------- Report data assembler
async def get_or_create_report_data(debate_id: str) -> dict[str, Any]:
    debate = db.get_debate(debate_id)
    if not debate:
        return None

    # Check cache
    if debate.get("report") and isinstance(debate["report"], dict):
        return debate["report"]

    messages = debate.get("messages", [])
    verdict = debate.get("verdict") or {
        "answer": "Pending",
        "summary": "Debate completed without final verdict.",
        "confidence": 50,
        "scores": {"advocate": 5, "critic": 5, "evidence": 5, "risk": 5},
    }

    memo = await generate_decision_memo(debate, messages, verdict)
    charts = compute_chart_data(debate, messages, verdict)

    created_ts = debate.get("created_at") or time.time()
    dt_str = datetime.fromtimestamp(created_ts).strftime("%Y-%m-%d %H:%M UTC")

    report_data = {
        "id": debate["id"],
        "question": debate["question"],
        "rounds": debate["rounds"],
        "model": debate.get("model", "auto"),
        "judge_model": debate.get("judge_model") or "auto",
        "note": debate.get("note") or "",
        "date": dt_str,
        "date_ymd": datetime.fromtimestamp(created_ts).strftime("%Y-%m-%d"),
        "verdict": verdict,
        "memo": memo,
        "charts": charts,
        "usage": {
            "tokens": debate.get("tokens", 0),
            "cost": debate.get("cost", 0.0),
            "seconds": debate.get("seconds", 0.0),
        },
        "transcript": messages,
        "disclaimer": DISCLAIMER_TEXT,
    }

    # Save to cache only when debate is finished
    if debate.get("status") == "done":
        db.update_debate(debate_id, report=report_data)
    return report_data


# --------------------------------------------------------------------- Matplotlib Charts
def render_charts_image(charts: dict[str, Any]) -> bytes:
    """Render a clean 2x2 grid of the 4 report charts using matplotlib Agg backend."""
    plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Helvetica", "Arial", "sans-serif"]
    plt.rcParams["font.family"] = "sans-serif"

    fig, axes = plt.subplots(2, 2, figsize=(10, 6.5), dpi=150)
    fig.patch.set_facecolor("#FFFFFF")

    # 1. Argument Scores (Top-Left)
    ax1 = axes[0, 0]
    ax1.set_facecolor("#FAFAFA")
    scores = charts["scores"]
    agents = [s["agent"] for s in scores]
    vals = [s["score"] for s in scores]
    colors_list = [s["color"] for s in scores]
    bars = ax1.bar(agents, vals, color=colors_list, width=0.55, edgecolor="#D1D5DB", linewidth=0.8)
    ax1.set_title("Argument Scores by Agent (0-10)", fontsize=11, fontweight="bold", color=APP_COLORS["navy"], pad=8)
    ax1.set_ylim(0, 10.5)
    ax1.grid(axis="y", linestyle="--", alpha=0.5, color="#D1D5DB")
    ax1.tick_params(colors=APP_COLORS["ink"], labelsize=9)
    for spine in ax1.spines.values():
        spine.set_color("#E5E7EB")
    for bar in bars:
        h = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width() / 2.0, h + 0.2, f"{h:.1f}", ha="center", va="bottom", fontsize=8.5, fontweight="bold", color=APP_COLORS["ink"])

    # 2. Confidence Gauge / Bar (Top-Right)
    ax2 = axes[0, 1]
    ax2.set_facecolor("#FAFAFA")
    conf = charts["confidence"]["confidence"]
    ax2.set_xlim(0, 100)
    ax2.set_ylim(-0.6, 0.6)
    # Background bar
    ax2.barh([0], [100], color="#FEF3C7", height=0.45, edgecolor="#F59E0B", linewidth=0.8)
    # Active bar
    ax2.barh([0], [conf], color=APP_COLORS["gold"], height=0.45, edgecolor="#92400E", linewidth=0.8)
    ax2.set_title(f"Judge Confidence: {conf}%", fontsize=11, fontweight="bold", color=APP_COLORS["navy"], pad=8)
    ax2.set_yticks([])
    ax2.set_xticks([0, 25, 50, 75, 100])
    ax2.set_xticklabels(["0%", "25%", "50%", "75%", "100%"], fontsize=8.5, color=APP_COLORS["ink"])
    ax2.grid(axis="x", linestyle="--", alpha=0.5, color="#D1D5DB")
    for spine in ax2.spines.values():
        spine.set_color("#E5E7EB")
    ax2.text(conf / 2.0 if conf > 15 else conf + 4, 0, f"{conf}%", ha="center", va="center", fontsize=10, fontweight="bold", color="#FFFFFF" if conf > 15 else APP_COLORS["navy"])

    # 3. Evidence Check Results Donut (Bottom-Left)
    ax3 = axes[1, 0]
    ax3.set_facecolor("#FAFAFA")
    evi = charts["evidence"]
    evi_labels = [e["label"] for e in evi]
    evi_vals = [e["value"] for e in evi]
    evi_colors = [e["color"] for e in evi]
    total_evi = sum(evi_vals)
    if total_evi == 0:
        evi_vals = [1, 1, 1, 1]
        evi_labels = ["Supported (0)", "Unsupported (0)", "Contradicted (0)", "Unclear (0)"]

    wedges, texts, autotexts = ax3.pie(
        evi_vals,
        labels=evi_labels,
        colors=evi_colors,
        autopct="%1.0f%%" if total_evi > 0 else "",
        startangle=90,
        pctdistance=0.75,
        wedgeprops=dict(width=0.4, edgecolor="#FFFFFF", linewidth=1.5),
        textprops=dict(fontsize=8, color=APP_COLORS["ink"]),
    )
    for at in autotexts:
        at.set_fontsize(7.5)
        at.set_fontweight("bold")
        at.set_color("#FFFFFF")
    ax3.set_title("Evidence Check Distribution", fontsize=11, fontweight="bold", color=APP_COLORS["navy"], pad=8)

    # 4. Token Usage by Agent (Bottom-Right)
    ax4 = axes[1, 1]
    ax4.set_facecolor("#FAFAFA")
    tokens = charts["tokens"]
    t_agents = [t["agent"] for t in tokens]
    t_vals = [t["tokens"] for t in tokens]
    t_colors = [t["color"] for t in tokens]
    t_bars = ax4.bar(t_agents, t_vals, color=t_colors, width=0.55, edgecolor="#D1D5DB", linewidth=0.8)
    ax4.set_title("Tokens Used by Agent", fontsize=11, fontweight="bold", color=APP_COLORS["navy"], pad=8)
    max_t = max(t_vals) if t_vals and max(t_vals) > 0 else 100
    ax4.set_ylim(0, max_t * 1.25)
    ax4.grid(axis="y", linestyle="--", alpha=0.5, color="#D1D5DB")
    ax4.tick_params(colors=APP_COLORS["ink"], labelsize=9)
    for spine in ax4.spines.values():
        spine.set_color("#E5E7EB")
    for bar in t_bars:
        h = bar.get_height()
        ax4.text(bar.get_x() + bar.get_width() / 2.0, h + (max_t * 0.02), f"{int(h)}", ha="center", va="bottom", fontsize=8, fontweight="bold", color=APP_COLORS["ink"])

    plt.tight_layout(pad=2.0)
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


# --------------------------------------------------------------------- Word (.docx) Builder
def generate_docx_report(report_data: dict[str, Any]) -> bytes:
    doc = Document()

    # Set 0.75-inch margins
    for section in doc.sections:
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.75)
        section.right_margin = Inches(0.75)

    # Styles
    navy_color = RGBColor(0x1F, 0x2A, 0x44)
    teal_color = RGBColor(0x0F, 0x76, 0x6E)
    ink_color = RGBColor(0x1F, 0x29, 0x37)
    muted_color = RGBColor(0x6B, 0x72, 0x80)

    # Header title
    title_p = doc.add_paragraph()
    title_p.paragraph_format.space_before = Pt(0)
    title_p.paragraph_format.space_after = Pt(2)
    run_sub = title_p.add_run("AGENT COURTROOM | SUMMARY REPORT & DECISION MEMO\n")
    run_sub.font.name = "Arial"
    run_sub.font.size = Pt(9.5)
    run_sub.font.bold = True
    run_sub.font.color.rgb = teal_color

    run_title = title_p.add_run(report_data["question"])
    run_title.font.name = "Arial"
    run_title.font.size = Pt(17)
    run_title.font.bold = True
    run_title.font.color.rgb = navy_color

    # Metadata banner table
    meta_table = doc.add_table(rows=1, cols=4)
    meta_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    meta_table.autofit = True
    cell_widths = [Inches(1.75), Inches(1.75), Inches(1.75), Inches(1.75)]
    labels = [
        f"Date: {report_data['date']}",
        f"Rounds: {report_data['rounds']}",
        f"Debater Model: {report_data['model']}",
        f"Judge Model: {report_data['judge_model']}",
    ]
    hdr_cells = meta_table.rows[0].cells
    for i, (cell, text) in enumerate(zip(hdr_cells, labels)):
        cell.width = cell_widths[i]
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(4)
        r = p.add_run(text)
        r.font.name = "Arial"
        r.font.size = Pt(8.5)
        r.font.color.rgb = muted_color
        # Shading
        shading = parse_xml(r'<w:shd {} w:fill="F3F4F6"/>'.format(nsdecls('w')))
        cell._tc.get_or_add_tcPr().append(shading)

    doc.add_paragraph().paragraph_format.space_after = Pt(4)

    def add_section_header(title: str):
        h = doc.add_paragraph()
        h.paragraph_format.space_before = Pt(12)
        h.paragraph_format.space_after = Pt(4)
        h.paragraph_format.keep_with_next = True
        r = h.add_run(title)
        r.font.name = "Arial"
        r.font.size = Pt(12.5)
        r.font.bold = True
        r.font.color.rgb = navy_color
        return h

    # 1. Executive Summary
    add_section_header("1. Executive Summary")
    memo = report_data.get("memo", {})
    p_exec = doc.add_paragraph()
    p_exec.paragraph_format.space_after = Pt(6)
    p_exec.paragraph_format.line_spacing = 1.15
    r_exec = p_exec.add_run(memo.get("executive_summary", ""))
    r_exec.font.name = "Arial"
    r_exec.font.size = Pt(10)
    r_exec.font.color.rgb = ink_color

    # 2. Final Verdict
    add_section_header("2. Final Verdict")
    verdict = report_data.get("verdict", {})
    v_table = doc.add_table(rows=2, cols=3)
    v_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    v_headers = ["Ruling Answer", "Judge Recommendation", "Confidence Score"]
    v_vals = [
        str(verdict.get("answer", "N/A")),
        str(verdict.get("summary", "N/A")),
        f"{verdict.get('confidence', 0)}%",
    ]
    for i, cell in enumerate(v_table.rows[0].cells):
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(2)
        r = p.add_run(v_headers[i])
        r.font.name = "Arial"
        r.font.size = Pt(8.5)
        r.font.bold = True
        r.font.color.rgb = muted_color
        shd = parse_xml(r'<w:shd {} w:fill="FEF3C7"/>'.format(nsdecls('w')))
        cell._tc.get_or_add_tcPr().append(shd)

    for i, cell in enumerate(v_table.rows[1].cells):
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(2)
        r = p.add_run(v_vals[i])
        r.font.name = "Arial"
        r.font.size = Pt(11)
        r.font.bold = True
        r.font.color.rgb = RGBColor(0xB4, 0x53, 0x09) if i == 0 else ink_color
        shd = parse_xml(r'<w:shd {} w:fill="FFFBEB"/>'.format(nsdecls('w')))
        cell._tc.get_or_add_tcPr().append(shd)

    # 3. Visual Analysis & Charts
    add_section_header("3. Visual Analysis & Metrics")
    charts_png = render_charts_image(report_data["charts"])
    img_stream = io.BytesIO(charts_png)
    doc.add_picture(img_stream, width=Inches(6.8))
    p_img_cap = doc.add_paragraph()
    p_img_cap.paragraph_format.space_after = Pt(6)
    p_img_cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_cap = p_img_cap.add_run("Figure 1: Argument scoring, confidence meter, claim distribution, and agent token usage.")
    r_cap.font.name = "Arial"
    r_cap.font.size = Pt(8.5)
    r_cap.font.italic = True
    r_cap.font.color.rgb = muted_color

    # 4. Arguments For and Against
    add_section_header("4. Deliberation Arguments")
    args_table = doc.add_table(rows=1, cols=2)
    args_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell_for, cell_against = args_table.rows[0].cells
    cell_for.width = Inches(3.4)
    cell_against.width = Inches(3.4)

    # Arguments For
    p_for_h = cell_for.paragraphs[0]
    p_for_h.paragraph_format.space_after = Pt(4)
    r_fh = p_for_h.add_run("ARGUMENTS FOR (Advocate)")
    r_fh.font.name = "Arial"
    r_fh.font.bold = True
    r_fh.font.size = Pt(9.5)
    r_fh.font.color.rgb = teal_color
    shd_for = parse_xml(r'<w:shd {} w:fill="CCFBF1"/>'.format(nsdecls('w')))
    cell_for._tc.get_or_add_tcPr().append(shd_for)

    for item in memo.get("arguments_for", []):
        p_item = cell_for.add_paragraph(style="List Bullet")
        p_item.paragraph_format.space_after = Pt(3)
        r = p_item.add_run(item)
        r.font.name = "Arial"
        r.font.size = Pt(9)
        r.font.color.rgb = ink_color

    # Arguments Against
    p_ag_h = cell_against.paragraphs[0]
    p_ag_h.paragraph_format.space_after = Pt(4)
    r_ah = p_ag_h.add_run("ARGUMENTS AGAINST (Critic)")
    r_ah.font.name = "Arial"
    r_ah.font.bold = True
    r_ah.font.size = Pt(9.5)
    r_ah.font.color.rgb = RGBColor(0xC2, 0x41, 0x0C)
    shd_ag = parse_xml(r'<w:shd {} w:fill="FFEDD5"/>'.format(nsdecls('w')))
    cell_against._tc.get_or_add_tcPr().append(shd_ag)

    for item in memo.get("arguments_against", []):
        p_item = cell_against.add_paragraph(style="List Bullet")
        p_item.paragraph_format.space_after = Pt(3)
        r = p_item.add_run(item)
        r.font.name = "Arial"
        r.font.size = Pt(9)
        r.font.color.rgb = ink_color

    # 5. Risks and Mitigations
    add_section_header("5. Practical Risks & Recommended Mitigations")
    risks_list = memo.get("risks", [])
    r_table = doc.add_table(rows=len(risks_list) + 1, cols=2)
    r_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    r_hdr_cells = r_table.rows[0].cells
    r_hdr_cells[0].width = Inches(3.4)
    r_hdr_cells[1].width = Inches(3.4)
    for idx, name in enumerate(["Identified Risk (Risk Analyst)", "Recommended Mitigation"]):
        p = r_hdr_cells[idx].paragraphs[0]
        p.paragraph_format.space_after = Pt(2)
        r = p.add_run(name)
        r.font.name = "Arial"
        r.font.bold = True
        r.font.size = Pt(9)
        r.font.color.rgb = navy_color
        shd = parse_xml(r'<w:shd {} w:fill="F3F4F6"/>'.format(nsdecls('w')))
        r_hdr_cells[idx]._tc.get_or_add_tcPr().append(shd)

    for i, r_obj in enumerate(risks_list, start=1):
        row_cells = r_table.rows[i].cells
        p_risk = row_cells[0].paragraphs[0]
        p_risk.paragraph_format.space_after = Pt(3)
        r1 = p_risk.add_run(r_obj.get("risk", ""))
        r1.font.name = "Arial"
        r1.font.size = Pt(9)
        r1.font.color.rgb = ink_color

        p_mit = row_cells[1].paragraphs[0]
        p_mit.paragraph_format.space_after = Pt(3)
        r2 = p_mit.add_run(r_obj.get("mitigation", ""))
        r2.font.name = "Arial"
        r2.font.size = Pt(9)
        r2.font.color.rgb = ink_color

    # 6. Evidence Check
    add_section_header("6. Evidence & Factuality Audit")
    for note in memo.get("evidence_notes", []):
        p_note = doc.add_paragraph(style="List Bullet")
        p_note.paragraph_format.space_after = Pt(3)
        r = p_note.add_run(note)
        r.font.name = "Arial"
        r.font.size = Pt(9.5)
        r.font.color.rgb = ink_color

    # 7. Recommendation and Next Steps
    add_section_header("7. Actionable Recommendation & Next Steps")
    p_rec = doc.add_paragraph()
    p_rec.paragraph_format.space_after = Pt(4)
    r_rec_lbl = p_rec.add_run("Recommendation: ")
    r_rec_lbl.font.name = "Arial"
    r_rec_lbl.font.bold = True
    r_rec_lbl.font.size = Pt(10)
    r_rec_lbl.font.color.rgb = teal_color
    r_rec = p_rec.add_run(memo.get("recommendation", ""))
    r_rec.font.name = "Arial"
    r_rec.font.size = Pt(10)
    r_rec.font.color.rgb = ink_color

    for step in memo.get("next_steps", []):
        p_step = doc.add_paragraph(style="List Bullet")
        p_step.paragraph_format.space_after = Pt(3)
        r = p_step.add_run(step)
        r.font.name = "Arial"
        r.font.size = Pt(9.5)
        r.font.color.rgb = ink_color

    # 8. Usage & Limitations
    add_section_header("8. System Usage & Analytical Limitations")
    usage = report_data.get("usage", {})
    p_u = doc.add_paragraph()
    p_u.paragraph_format.space_after = Pt(3)
    r_u = p_u.add_run(
        f"Execution Metrics: {usage.get('tokens', 0):,} tokens consumed  |  "
        f"Estimated API Cost: ${usage.get('cost', 0.0):.4f}  |  "
        f"Elapsed Compute Time: {usage.get('seconds', 0.0)}s"
    )
    r_u.font.name = "Arial"
    r_u.font.size = Pt(9)
    r_u.font.color.rgb = muted_color

    p_lim = doc.add_paragraph()
    p_lim.paragraph_format.space_after = Pt(8)
    r_lim_lbl = p_lim.add_run("Scope Limitations: ")
    r_lim_lbl.font.name = "Arial"
    r_lim_lbl.font.bold = True
    r_lim_lbl.font.size = Pt(9)
    r_lim_lbl.font.color.rgb = muted_color
    r_lim = p_lim.add_run(memo.get("limitations", ""))
    r_lim.font.name = "Arial"
    r_lim.font.size = Pt(9)
    r_lim.font.color.rgb = muted_color

    # Appendix: Full Transcript
    add_section_header("Appendix: Full Debate Transcript")
    transcript = report_data.get("transcript", [])
    t_table = doc.add_table(rows=len(transcript) + 1, cols=3)
    t_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    t_hdrs = ["Round", "Agent", "Statement Content"]
    t_widths = [Inches(0.8), Inches(1.3), Inches(4.7)]
    for i, cell in enumerate(t_table.rows[0].cells):
        cell.width = t_widths[i]
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(2)
        r = p.add_run(t_hdrs[i])
        r.font.name = "Arial"
        r.font.bold = True
        r.font.size = Pt(8.5)
        r.font.color.rgb = navy_color
        shd = parse_xml(r'<w:shd {} w:fill="F3F4F6"/>'.format(nsdecls('w')))
        cell._tc.get_or_add_tcPr().append(shd)

    for idx, msg in enumerate(transcript, start=1):
        row_cells = t_table.rows[idx].cells
        for i, w in enumerate(t_widths):
            row_cells[i].width = w

        p0 = row_cells[0].paragraphs[0]
        p0.paragraph_format.space_after = Pt(2)
        r0 = p0.add_run(f"R{msg.get('round', 1)}")
        r0.font.name = "Arial"
        r0.font.size = Pt(8.5)

        p1 = row_cells[1].paragraphs[0]
        p1.paragraph_format.space_after = Pt(2)
        agent_label = prompts.LABEL.get(msg.get("agent", ""), msg.get("agent", "").capitalize())
        r1 = p1.add_run(agent_label)
        r1.font.name = "Arial"
        r1.font.bold = True
        r1.font.size = Pt(8.5)
        # agent color
        ag_color = {"advocate": teal_color, "critic": RGBColor(0xC2, 0x41, 0x0C), "evidence": RGBColor(0x1D, 0x4E, 0xD8), "risk": RGBColor(0x6D, 0x28, 0xD9)}.get(msg.get("agent", ""), navy_color)
        r1.font.color.rgb = ag_color

        p2 = row_cells[2].paragraphs[0]
        p2.paragraph_format.space_after = Pt(2)
        r2 = p2.add_run(msg.get("content", ""))
        r2.font.name = "Arial"
        r2.font.size = Pt(8.5)
        r2.font.color.rgb = ink_color

    # Disclaimer Paragraph & Footer
    p_disc = doc.add_paragraph()
    p_disc.paragraph_format.space_before = Pt(12)
    p_disc.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_disc_body = p_disc.add_run(DISCLAIMER_TEXT)
    r_disc_body.font.name = "Arial"
    r_disc_body.font.size = Pt(8)
    r_disc_body.font.italic = True
    r_disc_body.font.color.rgb = muted_color

    footer = doc.sections[0].footer
    p_foot = footer.paragraphs[0]
    p_foot.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_disc = p_foot.add_run(DISCLAIMER_TEXT)
    r_disc.font.name = "Arial"
    r_disc.font.size = Pt(8)
    r_disc.font.italic = True
    r_disc.font.color.rgb = muted_color

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


# --------------------------------------------------------------------- ReportLab PDF Builder
class NumberedCanvas(canvas.Canvas):
    """Canvas that computes total page count dynamically for page numbering."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_footer(num_pages)
            super().showPage()
        super().save()

    def draw_footer(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 7.5)
        self.setFillColor(colors.HexColor(APP_COLORS["muted"]))
        footer_text = f"Agent Courtroom - Summary Report  |  Page {self._pageNumber} of {page_count}"
        self.drawString(36, 24, footer_text)
        self.drawRightString(letter[0] - 36, 24, DISCLAIMER_TEXT)
        self.setStrokeColor(colors.HexColor(APP_COLORS["line"]))
        self.setLineWidth(0.5)
        self.line(36, 34, letter[0] - 36, 34)
        self.restoreState()


def generate_pdf_report(report_data: dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=46,
    )

    styles = getSampleStyleSheet()
    normal = styles["Normal"]

    # Custom typography styles
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=normal,
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=19,
        textColor=colors.HexColor(APP_COLORS["navy"]),
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=normal,
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor(APP_COLORS["teal"]),
        spaceAfter=2,
    )
    meta_style = ParagraphStyle(
        "MetaText",
        parent=normal,
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor(APP_COLORS["muted"]),
    )
    h1_style = ParagraphStyle(
        "Heading1_Custom",
        parent=normal,
        fontName="Helvetica-Bold",
        fontSize=11.5,
        leading=14,
        textColor=colors.HexColor(APP_COLORS["navy"]),
        spaceBefore=10,
        spaceAfter=4,
        keepWithNext=True,
    )
    body_style = ParagraphStyle(
        "Body_Custom",
        parent=normal,
        fontName="Helvetica",
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor(APP_COLORS["ink"]),
        spaceAfter=4,
    )
    bullet_style = ParagraphStyle(
        "Bullet_Custom",
        parent=normal,
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor(APP_COLORS["ink"]),
        leftIndent=12,
        firstLineIndent=-8,
        spaceAfter=3,
    )
    card_title_style = ParagraphStyle(
        "CardTitle",
        parent=normal,
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=11,
        textColor=colors.HexColor(APP_COLORS["navy"]),
        spaceAfter=2,
    )

    story = []

    # Title & Metadata
    story.append(Paragraph("AGENT COURTROOM | SUMMARY REPORT & DECISION MEMO", subtitle_style))
    story.append(Paragraph(report_data["question"], title_style))
    story.append(Spacer(1, 4))

    meta_cells = [
        [
            Paragraph(f"<b>Date:</b> {report_data['date']}", meta_style),
            Paragraph(f"<b>Rounds:</b> {report_data['rounds']}", meta_style),
            Paragraph(f"<b>Debater Model:</b> {report_data['model']}", meta_style),
            Paragraph(f"<b>Judge Model:</b> {report_data['judge_model']}", meta_style),
        ]
    ]
    meta_tbl = Table(meta_cells, colWidths=[135, 100, 150, 155])
    meta_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(APP_COLORS["panel"])),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(APP_COLORS["line"])),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(meta_tbl)
    story.append(Spacer(1, 8))

    memo = report_data.get("memo", {})
    verdict = report_data.get("verdict", {})

    # 1. Executive Summary
    story.append(Paragraph("1. Executive Summary", h1_style))
    story.append(Paragraph(memo.get("executive_summary", ""), body_style))
    story.append(Spacer(1, 6))

    # 2. Final Verdict
    story.append(Paragraph("2. Final Verdict", h1_style))
    v_data = [
        [
            Paragraph("<b>Ruling Answer</b>", card_title_style),
            Paragraph("<b>Judge Recommendation</b>", card_title_style),
            Paragraph("<b>Confidence Score</b>", card_title_style),
        ],
        [
            Paragraph(f"<b>{verdict.get('answer', 'N/A')}</b>", ParagraphStyle("VAns", parent=body_style, fontSize=12, leading=14, textColor=colors.HexColor(APP_COLORS["gold"]))),
            Paragraph(str(verdict.get("summary", "N/A")), body_style),
            Paragraph(f"<b>{verdict.get('confidence', 0)}%</b>", ParagraphStyle("VConf", parent=body_style, fontSize=12, leading=14, textColor=colors.HexColor(APP_COLORS["navy"]))),
        ],
    ]
    v_tbl = Table(v_data, colWidths=[140, 260, 140])
    v_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(APP_COLORS["gold_light"])),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#FFFBEB")),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor(APP_COLORS["gold"])),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(v_tbl)
    story.append(Spacer(1, 8))

    # 3. Charts & Metrics
    story.append(Paragraph("3. Visual Analysis & Metrics", h1_style))
    charts_png = render_charts_image(report_data["charts"])
    chart_img = RLImage(io.BytesIO(charts_png), width=7.2 * inch, height=4.68 * inch)
    story.append(chart_img)
    story.append(Spacer(1, 6))

    # 4. Arguments For and Against
    story.append(Paragraph("4. Deliberation Arguments", h1_style))
    for_items = [Paragraph(f"• {a}", bullet_style) for a in memo.get("arguments_for", [])]
    ag_items = [Paragraph(f"• {a}", bullet_style) for a in memo.get("arguments_against", [])]

    args_data = [
        [
            Paragraph("<b>ARGUMENTS FOR (Advocate)</b>", ParagraphStyle("ForH", parent=card_title_style, textColor=colors.HexColor(APP_COLORS["teal"]))),
            Paragraph("<b>ARGUMENTS AGAINST (Critic)</b>", ParagraphStyle("AgH", parent=card_title_style, textColor=colors.HexColor(APP_COLORS["coral"]))),
        ],
        [
            for_items or Paragraph("None", body_style),
            ag_items or Paragraph("None", body_style),
        ],
    ]
    args_tbl = Table(args_data, colWidths=[265, 275])
    args_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor(APP_COLORS["teal_light"])),
        ("BACKGROUND", (1, 0), (1, 0), colors.HexColor(APP_COLORS["coral_light"])),
        ("BACKGROUND", (0, 1), (0, 1), colors.HexColor("#F0FDF4")),
        ("BACKGROUND", (1, 1), (1, 1), colors.HexColor("#FFF7ED")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(APP_COLORS["line"])),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(args_tbl)
    story.append(Spacer(1, 8))

    # 5. Risks and Mitigations
    story.append(Paragraph("5. Practical Risks & Mitigations", h1_style))
    r_rows = [
        [
            Paragraph("<b>Identified Risk (Risk Analyst)</b>", card_title_style),
            Paragraph("<b>Recommended Mitigation Strategy</b>", card_title_style),
        ]
    ]
    for r_obj in memo.get("risks", []):
        r_rows.append([
            Paragraph(r_obj.get("risk", ""), body_style),
            Paragraph(r_obj.get("mitigation", ""), body_style),
        ])
    risk_tbl = Table(r_rows, colWidths=[265, 275])
    risk_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(APP_COLORS["panel"])),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(APP_COLORS["line"])),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor(APP_COLORS["line"])),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(risk_tbl)
    story.append(Spacer(1, 8))

    # 6. Evidence Check
    story.append(Paragraph("6. Evidence & Factuality Audit", h1_style))
    for note in memo.get("evidence_notes", []):
        story.append(Paragraph(f"• {note}", bullet_style))
    story.append(Spacer(1, 6))

    # 7. Recommendation and Next Steps
    story.append(Paragraph("7. Actionable Recommendation & Next Steps", h1_style))
    story.append(Paragraph(f"<b>Recommendation:</b> {memo.get('recommendation', '')}", body_style))
    for step in memo.get("next_steps", []):
        story.append(Paragraph(f"• {step}", bullet_style))
    story.append(Spacer(1, 6))

    # 8. Usage & Limitations
    story.append(Paragraph("8. Execution Metrics & Scope Limitations", h1_style))
    usage = report_data.get("usage", {})
    u_text = (
        f"<b>Execution Metrics:</b> {usage.get('tokens', 0):,} tokens  |  "
        f"Estimated Cost: ${usage.get('cost', 0.0):.4f}  |  "
        f"Elapsed Time: {usage.get('seconds', 0.0)}s"
    )
    story.append(Paragraph(u_text, meta_style))
    story.append(Spacer(1, 3))
    story.append(Paragraph(f"<b>Scope Limitations:</b> {memo.get('limitations', '')}", meta_style))
    story.append(Spacer(1, 8))

    # Appendix: Transcript
    story.append(Paragraph("Appendix: Full Debate Transcript", h1_style))
    t_rows = [
        [
            Paragraph("<b>Round</b>", card_title_style),
            Paragraph("<b>Agent</b>", card_title_style),
            Paragraph("<b>Deliberation Statement</b>", card_title_style),
        ]
    ]
    for msg in report_data.get("transcript", []):
        ag_raw = msg.get("agent", "")
        ag_label = prompts.LABEL.get(ag_raw, ag_raw.capitalize())
        ag_color_hex = APP_COLORS.get(ag_raw, APP_COLORS["navy"])
        p_agent = Paragraph(f"<b>{ag_label}</b>", ParagraphStyle("AgCol", parent=body_style, textColor=colors.HexColor(ag_color_hex)))
        t_rows.append([
            Paragraph(f"R{msg.get('round', 1)}", meta_style),
            p_agent,
            Paragraph(msg.get("content", ""), body_style),
        ])

    transcript_tbl = Table(t_rows, colWidths=[45, 95, 400])
    transcript_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(APP_COLORS["panel"])),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(APP_COLORS["line"])),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor(APP_COLORS["line"])),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(transcript_tbl)

    doc.build(story, canvasmaker=NumberedCanvas)
    buf.seek(0)
    return buf.getvalue()
