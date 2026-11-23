# Agent Courtroom

AI agents argue a question from different sides (Advocate, Critic, Risk Analyst, Evidence Agent) and a Judge decides.
Frontend: React + Vite + Tailwind. Backend: Python + FastAPI + WebSocket + SQLite.

## Quick start on Windows

1. Install **Python 3.10+** (tick "Add python.exe to PATH") from https://www.python.org/downloads/
2. Double-click **`start.bat`**. It sets everything up and opens http://localhost:8000.

That is all you need to see the app working in **Demo mode** (simulated agents, no model required).
Node.js is optional: if it is installed, `start.bat` rebuilds the frontend; otherwise it uses the bundled build.

## Use real AI models (Ollama, free, runs on your laptop)

1. Install Ollama (already done if `ollama --version` works).
2. In a terminal, pull two small models. The Judge uses a different model than the debaters:

   ```
   ollama pull llama3.2:3b
   ollama pull qwen2.5:3b
   ```
3. Keep Ollama running, then reload the app. **Model: Auto** now picks them automatically.
   Click the **Model** box to cycle through Auto, Demo and every installed model.

The first message of a session can take 10 to 30 seconds while the model loads into memory. After that it streams quickly.
Larger models (for example `llama3.1:8b`) give better arguments but are slower on a laptop without a strong GPU.

### Optional: a cloud model
Copy `backend/.env.example` to `backend/.env` and set `LLM_BASE_URL`, `LLM_API_KEY` and `LLM_MODEL`
(any OpenAI-compatible API). The model then appears in the Model box. Keys stay on the backend and are never sent to the browser.

## How to use the screen

| Control | What it does |
|---|---|
| Question box | Type your question (at least 10 characters). Enter also starts. |
| **Rounds** | Click to cycle 1 to 5. |
| **Model** | Click to cycle Auto, Demo and installed models. |
| **Start / Stop** | Runs a debate live. While running, the button becomes Stop. |
| Debate tab | Live transcript, verdict, scores, tokens, cost and time. |
| History tab | Past debates. Click one to reopen it, or Delete it. |
| Benchmarks tab | Compares Direct, Step by step, Majority vote and Agent Courtroom on 5 maths problems. Needs a real model (not Demo). |
| **Report tab** | Full debate summary report with Decision Memo, 4 analysis charts, arguments, risks, evidence audit, recommendation, and download buttons for Word (.docx) and PDF. |
| **Voice: On/Off** | Click to toggle live text-to-speech for debate turns and the judge verdict (on by default). |

### Voice (Text-to-Speech)
The Debate tab includes live text-to-speech powered directly by the browser's built-in Web Speech API (`window.speechSynthesis`):
- **Real-time sentence streaming**: Agents begin speaking as soon as their first sentence is complete without waiting for the full turn to finish streaming.
- **Distinct agent voices**: Each role (Advocate, Critic, Risk Analyst, Evidence Agent, and Judge) is assigned a distinct installed English voice (preferring `en-IN`, `en-GB`, `en-US`) with unique pitch and rate profiles. Each agent announces their name before their first sentence (e.g., `Critic: ...`).
- **Judge verdict**: The Judge announces the verdict upon conclusion (`Verdict: <answer>. <summary>. Confidence <n> percent.`).
- **Sequential speech queue**: Sentences queue in order without overlapping. Stopping, starting a new debate, opening past debates, or toggling voice to Off immediately cancels speech and clears the queue.
- **Controls**: Small `Voice: On/Off` toggle at the right end of the title bar, saved in `localStorage`. Disables automatically with a status note if speech synthesis is not supported.

### Downloadable Summary Reports (.docx & .pdf)
From the **Report** tab, users can download a decision memo and report formatted for Word (.docx) and PDF:
- **Decision Memo**: Executive summary (80-120 words), arguments for and against, practical risks with mitigations, evidence check, recommendation, next steps, and limitations.
- **Visual Analytics**: 4 embedded charts (Argument scores by agent 0-10, Judge confidence meter 0-100%, Evidence distribution donut, and Token usage by agent).
- **Audit Trail**: Execution metrics (tokens, cost, elapsed time) and complete debate transcript appendix.
- **Fail-safe**: Works seamlessly across local Ollama, cloud OpenAI-compatible models, and offline Demo mode (via no-model fallback builder).

### Configuration & Settings (`backend/.env`)
| Variable | Default | Description |
|---|---|---|
| `OLLAMA_NUM_CTX` | `8192` | Context window size for Ollama requests to avoid prompt cutoff. |
| `ANSWER_DETAIL` | `brief` | Detail level of debate turns: `brief` (~25 words) or `detailed` (60-80 words, max 180 tokens). |
| `ENABLE_WIKIPEDIA` | `false` | Lets Evidence Agent look up Wikipedia snippets (needs internet). |
| `PRICE_IN_PER_1M` / `PRICE_OUT_PER_1M` | `0.0` | Pricing per 1M tokens for cost tracking. |
| `DEMO_WORD_DELAY` | `0.035` | Streaming word delay for Demo mode simulation. |

### Dependencies
- **Backend** (pinned in `backend/requirements.txt`): `fastapi==0.115.6`, `uvicorn==0.32.1`, `websockets==13.1`, `httpx==0.28.1`, `python-dotenv==1.0.1`, `python-docx==1.2.0`, `matplotlib==3.11.2` (Agg backend only), `reportlab==5.1.0`.
- **Frontend** (pinned in `frontend/package.json`): `react: 18.3.1`, `react-dom: 18.3.1`, `recharts: 3.10.1`, Vite 5, Tailwind CSS 3.

The first screen shows sample values (as in the UI sketch). They are replaced as soon as you start a debate.
To hide the numbered circles from the sketch, set `SHOW_ANNOTATIONS = false` in `frontend/src/config.js` and rebuild.

## Development mode

`dev.bat` opens the backend (auto-reload) and the frontend (Vite, http://localhost:5173) in two windows.

Manual commands:

```
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000

cd frontend
npm install
npm run dev
```

Run the tests: `cd backend && python -m pytest`

## Project structure

```
backend/
  app/
    main.py        REST endpoints, WebSocket /ws/debates/{id}, serves the built frontend
    engine.py      the debate: rounds, streaming, judge, cancel
    prompts.py     the prompt for every agent
    report.py      Decision Memo generator, chart renderer (matplotlib), Word (.docx) & PDF builders
    llm.py         providers: Demo, Ollama, OpenAI-compatible; model choice
    benchmark.py   mini benchmark and scoring
    db.py          SQLite storage (backend/data/courtroom.db)
  tests/           27 tests, including report generation and headless browser UI tests
frontend/src/
  App.jsx          layout and tabs
  hooks/           useDebate (live state), useFitScale (fits any screen)
  components/      one file per part of the screen (including ReportPanel.jsx)
  api.js           calls to the backend
  data/sample.js   the sample values shown before the first debate
```

## Good to know

- **Demo mode is simulated.** Its answers are scripted, not real reasoning. The verdict card says "demo mode (simulated)".
- If only one model is installed, the Judge uses the same model (the card says "judge: same model").
- Settings live in `backend/.env`. `ENABLE_WIKIPEDIA=true` lets the Evidence Agent look up Wikipedia snippets (needs internet).
- Reset all history: stop the app and delete `backend/data/courtroom.db`.

## Troubleshooting

| Problem | Fix |
|---|---|
| "Cannot reach Ollama" | Start Ollama (open the Ollama app), then press Start again. |
| "Model ... is not installed" | Run the `ollama pull ...` command shown in the message. |
| Very slow replies | Use a smaller model (`llama3.2:3b`), close other heavy apps, and use fewer rounds. |
| Port 8000 already in use | Close the other program, or change `--port` in `start.bat`. |
| Blank page after editing the frontend | Run `npm run build` in `frontend`, then reload. |
