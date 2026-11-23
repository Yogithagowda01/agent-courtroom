"""Prompt text for every agent. Role tags like [ROLE:critic] are also used by Demo mode."""
from __future__ import annotations

from .config import settings

LABEL = {"advocate": "Advocate", "critic": "Critic", "risk": "Risk Analyst", "evidence": "Evidence Agent"}


def get_style() -> str:
    if getattr(settings, "answer_detail", "brief") == "detailed":
        return " Reply in about 60 to 80 words (three to four short sentences). Plain text only: no lists, no markdown, no role label."
    return " Reply in at most 25 words (one or two short sentences). Plain text only: no lists, no markdown, no role label."


OPINION_SYSTEM = {
    "advocate": (
        "[ROLE:advocate] You are the Advocate in a courtroom-style debate between AI agents. "
        "Argue FOR the most defensible 'yes' side of the question. In later rounds, answer the Critic's last point."
    ),
    "critic": (
        "[ROLE:critic] You are the Critic in a courtroom-style debate between AI agents. "
        "Argue AGAINST: challenge the Advocate's strongest point or name the biggest flaw."
    ),
    "risk": (
        "[ROLE:risk] You are the Risk Analyst in a courtroom-style debate between AI agents. "
        "Name the most important practical risk (cost, time, effort or upkeep) of going ahead."
    ),
    "evidence": (
        "[ROLE:evidence] You are the Evidence Agent in a courtroom-style debate between AI agents. "
        "Pick ONE factual claim made so far. You must start by naming the claim (e.g. 'Claim: ...') and then explicitly label it supported, unsupported or contradicted, followed by your reasoning and snippet evidence."
    ),
}

_QA_STYLE = " Use at most 40 words. Plain text only. End with 'Answer: <number>'."

QA_SYSTEM = {
    "advocate": "[ROLE:advocate] [MODE:qa] You solve maths word problems. Show the key steps briefly." + _QA_STYLE,
    "critic": (
        "[ROLE:critic] [MODE:qa] You check a colleague's solution to a maths word problem. "
        "Say if it is right; if it is wrong, give the corrected solution." + _QA_STYLE
    ),
    "evidence": (
        "[ROLE:evidence] [MODE:qa] You recompute a maths word problem independently, step by step, "
        "and compare with the earlier answers." + _QA_STYLE
    ),
}

JUDGE_OPINION = (
    "[ROLE:judge] You are the Judge of a courtroom-style debate between AI agents. "
    "Weigh evidence quality, logic, answers to rebuttals and practicality. "
    "Return ONLY a JSON object with these keys: "
    '"answer" (max 3 words, for example Yes, No, Not now, It depends), '
    '"summary" (max 10 words: your recommendation), '
    '"confidence" (integer 0 to 100), '
    '"scores" (object with integer 0 to 10 for advocate, critic, evidence and risk).'
)

JUDGE_QA = (
    "[ROLE:judge] [MODE:qa] You are the Judge. Several agents solved a maths word problem. "
    'Decide the correct final number. Return ONLY a JSON object like {"final_answer": 42}.'
)

DECISION_MEMO_SYSTEM = (
    "[ROLE:judge] You are the presiding Judge. Write a comprehensive, objective Decision Memo summarizing the full courtroom debate. "
    "Rules: Use ONLY content from the debate. Do not invent facts, metrics, or numbers. Mark any assumptions clearly. "
    "You must return ONLY a valid JSON object with the following exact keys:\n"
    '- "executive_summary": string synthesizing the debate and rationale (80-120 words)\n'
    '- "arguments_for": list of strings detailing key arguments in favor\n'
    '- "arguments_against": list of strings detailing key arguments against\n'
    '- "risks": list of objects, each with "risk" (string) and "mitigation" (string)\n'
    '- "evidence_notes": list of strings evaluating verified, unsupported, or contradicted claims\n'
    '- "recommendation": string with your clear final recommendation\n'
    '- "next_steps": list of strings with concrete recommended next steps\n'
    '- "limitations": string describing analytical constraints and scope limitations'
)


def _transcript_lines(transcript: list[dict], last: int | None = None) -> list[str]:
    items = transcript[-last:] if last else transcript
    return [f"{LABEL.get(t['agent'], t['agent'].capitalize())}: {t['text']}" for t in items]


def turn_messages(agent: str, mode: str, question: str, transcript: list[dict], round_no: int, rounds: int, snippets: str) -> list[dict]:
    if mode == "qa":
        system = QA_SYSTEM[agent]
    else:
        system = OPINION_SYSTEM[agent] + get_style()
    parts = [f"QUESTION: {question}", f"ROUND: {round_no} of {rounds}"]
    if transcript:
        parts.append("DEBATE SO FAR:")
        parts.extend(_transcript_lines(transcript, last=8))
    if agent == "evidence" and snippets:
        parts.append("REFERENCE SNIPPETS:\n" + snippets)
    parts.append(f"Now speak as the {LABEL[agent]}.")
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n".join(parts)}]


def judge_messages(mode: str, question: str, transcript: list[dict]) -> list[dict]:
    system = JUDGE_QA if mode == "qa" else JUDGE_OPINION
    parts = [f"QUESTION: {question}", "DEBATE SO FAR:"]
    parts.extend(_transcript_lines(transcript))
    parts.append("Give your verdict now as JSON.")
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n".join(parts)}]


def memo_messages(question: str, transcript: list[dict], verdict: dict) -> list[dict]:
    parts = [
        f"QUESTION: {question}",
        f"FINAL VERDICT ANSWER: {verdict.get('answer', 'Unknown')}",
        f"VERDICT SUMMARY: {verdict.get('summary', '')}",
        f"CONFIDENCE: {verdict.get('confidence', 50)}%",
        "FULL DEBATE TRANSCRIPT:",
    ]
    parts.extend(_transcript_lines(transcript))
    parts.append("Generate the complete Decision Memo as JSON now according to the system instructions.")
    return [{"role": "system", "content": DECISION_MEMO_SYSTEM}, {"role": "user", "content": "\n".join(parts)}]
