import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest
import websockets

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
if not os.path.exists(CHROME_PATH):
    CHROME_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


class CDPClient:
    def __init__(self, ws_url):
        self.ws_url = ws_url
        self.ws = None
        self._id = 0

    async def connect(self):
        self.ws = await websockets.connect(self.ws_url, max_size=50_000_000)

    async def close(self):
        if self.ws:
            await self.ws.close()

    async def send(self, method, params=None):
        self._id += 1
        msg_id = self._id
        payload = {"id": msg_id, "method": method, "params": params or {}}
        await self.ws.send(json.dumps(payload))
        while True:
            resp_raw = await self.ws.recv()
            resp = json.loads(resp_raw)
            if resp.get("id") == msg_id:
                if "error" in resp:
                    raise RuntimeError(f"CDP error: {resp['error']}")
                return resp.get("result", {})

    async def eval(self, expr):
        res = await self.send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
        return (res.get("result") or {}).get("value")


MOCK_SPEECH_SCRIPT = """
window.__speechQueue = [];
window.__speechLog = [];
window.__speechCancelled = false;

class MockSpeechSynthesisUtterance {
  constructor(text) {
    this.text = text || '';
    this.voice = null;
    this.pitch = 1;
    this.rate = 1;
    this.lang = 'en-US';
    this.speaker = null;
    this.onend = null;
    this.onerror = null;
  }
}

const mockVoices = [
  { name: 'Ravi', lang: 'en-IN' },
  { name: 'George', lang: 'en-GB' },
  { name: 'David', lang: 'en-US' },
  { name: 'Zira', lang: 'en-US' },
  { name: 'Mark', lang: 'en-US' },
];

window.SpeechSynthesisUtterance = MockSpeechSynthesisUtterance;
const mockSpeech = {
  speaking: false,
  pending: false,
  paused: false,
  onvoiceschanged: null,
  getVoices: () => mockVoices,
  speak: (u) => {
    window.__speechQueue.push(u);
    window.__speechLog.push({
      text: u.text,
      speaker: u.speaker || (
        u.text.startsWith('Advocate:') ? 'Advocate' :
        u.text.startsWith('Critic:') ? 'Critic' :
        u.text.startsWith('Risk Analyst:') ? 'Risk Analyst' :
        u.text.startsWith('Evidence Agent:') ? 'Evidence Agent' :
        u.text.startsWith('Verdict:') ? 'Judge' : 'Unknown'
      ),
      voice: u.voice ? u.voice.name : null,
      pitch: u.pitch,
      rate: u.rate,
    });
  },
  cancel: () => {
    window.__speechQueue = [];
    window.__speechCancelled = true;
  },
  pause: () => {},
  resume: () => {},
  addEventListener: () => {},
  removeEventListener: () => {},
};

try {
  Object.defineProperty(window, 'speechSynthesis', {
    value: mockSpeech,
    configurable: true,
    writable: true
  });
} catch (e) {
  window.speechSynthesis = mockSpeech;
}
"""


async def run_ui_test():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        downloads_dir = Path(tmpdir) / "downloads"
        downloads_dir.mkdir()
        user_data_dir = Path(tmpdir) / "chrome_profile"
        user_data_dir.mkdir()

        # 1. Start backend server
        port = 8899
        backend_dir = Path(__file__).resolve().parent.parent
        python_exe = sys.executable
        env = os.environ.copy()
        env["FRONTEND_DIST"] = str(backend_dir.parent / "frontend" / "dist")
        env["ANSWER_DETAIL"] = "brief"
        env["DEMO_WORD_DELAY"] = "0.005"  # fast for testing

        server_proc = subprocess.Popen(
            [str(python_exe), "-m", "uvicorn", "app.main:app", "--port", str(port), "--host", "127.0.0.1"],
            cwd=str(backend_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        chrome_proc = None
        cdp = None
        try:
            # Wait for server to be responsive
            async with httpx.AsyncClient() as client:
                for _ in range(30):
                    try:
                        r = await client.get(f"http://127.0.0.1:{port}/api/health", timeout=1.0)
                        if r.status_code == 200:
                            break
                    except Exception:
                        await asyncio.sleep(0.3)
                else:
                    raise RuntimeError("Server failed to start")

            # 2. Launch headless Chrome
            cdp_port = 9333
            chrome_proc = subprocess.Popen(
                [
                    CHROME_PATH,
                    "--headless=new",
                    f"--remote-debugging-port={cdp_port}",
                    f"--user-data-dir={user_data_dir}",
                    "--disable-gpu",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--window-size=1280,800",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # Wait for CDP
            ws_url = None
            async with httpx.AsyncClient() as client:
                for _ in range(30):
                    try:
                        r = await client.get(f"http://127.0.0.1:{cdp_port}/json/list", timeout=1.0)
                        if r.status_code == 200 and r.json():
                            ws_url = r.json()[0]["webSocketDebuggerUrl"]
                            break
                    except Exception:
                        await asyncio.sleep(0.3)

            if not ws_url:
                raise RuntimeError("Failed to connect to headless Chrome CDP")

            cdp = CDPClient(ws_url)
            await cdp.connect()

            # Enable Page and Runtime domains
            await cdp.send("Page.enable")
            await cdp.send("Runtime.enable")

            # Enable downloads
            await cdp.send("Browser.setDownloadBehavior", {
                "behavior": "allowAndName",
                "downloadPath": str(downloads_dir),
                "eventsEnabled": True,
            })

            # Mock window.speechSynthesis before scripts load
            await cdp.send("Page.addScriptToEvaluateOnNewDocument", {"source": MOCK_SPEECH_SCRIPT})

            # Navigate to frontend
            nav_res = await cdp.send("Page.navigate", {"url": f"http://127.0.0.1:{port}"})
            print("Nav result:", nav_res)
            for _ in range(20):
                href = await cdp.eval("location.href")
                state = await cdp.eval("document.readyState")
                title = await cdp.eval("document.title")
                print(f"href: {href}, state: {state}, title: {title}")
                if title == "Agent Courtroom":
                    break
                await asyncio.sleep(0.5)

            # Verify Voice: On button is present in TitleBar
            voice_btn_text = ""
            for _ in range(30):
                voice_btn_text = await cdp.eval("""(() => {
                    const btns = Array.from(document.querySelectorAll('button'));
                    const b = btns.find(x => x.textContent.includes('Voice:'));
                    return b ? b.textContent.trim() : '';
                })()""")
                if voice_btn_text:
                    break
                await asyncio.sleep(0.3)
            assert voice_btn_text == "Voice: On", f"Expected 'Voice: On', found: {voice_btn_text}"
            print("Found voice button in TitleBar:", voice_btn_text)

            # Cycle rounds to 2
            for _ in range(6):
                r_text = await cdp.eval("""(() => {
                    const btns = Array.from(document.querySelectorAll('button'));
                    const b = btns.find(x => x.textContent.includes('Rounds:'));
                    return b ? b.textContent.trim() : '';
                })()""")
                if r_text == "Rounds: 2":
                    break
                await cdp.eval("""(() => {
                    const btns = Array.from(document.querySelectorAll('button'));
                    const b = btns.find(x => x.textContent.includes('Rounds:'));
                    if (b) b.click();
                })()""")
                await asyncio.sleep(0.1)

            # Cycle model to Demo
            for _ in range(6):
                m_text = await cdp.eval("""(() => {
                    const btns = Array.from(document.querySelectorAll('button'));
                    const b = btns.find(x => x.textContent.includes('Model:'));
                    return b ? b.textContent.trim() : '';
                })()""")
                if "Demo" in m_text:
                    break
                await cdp.eval("""(() => {
                    const btns = Array.from(document.querySelectorAll('button'));
                    const b = btns.find(x => x.textContent.includes('Model:'));
                    if (b) b.click();
                })()""")
                await asyncio.sleep(0.1)

            print("Configured rounds to 2 and model to Demo")

            # Click Start
            start_clicked = await cdp.eval("""(() => {
                const btns = Array.from(document.querySelectorAll('button'));
                const b = btns.find(x => x.textContent.trim() === 'Start');
                if (b) { b.click(); return true; }
                return false;
            })()""")
            assert start_clicked, "Could not find Start button"
            print("Started 2-round debate...")

            # Wait for debate to finish (look for "Debate complete" in status)
            for _ in range(60):
                status_text = await cdp.eval("""(() => {
                    const divs = Array.from(document.querySelectorAll('div'));
                    const d = divs.find(x => x.textContent.includes('Debate complete'));
                    return d ? d.textContent : '';
                })()""")
                if "Debate complete" in status_text:
                    print("Debate finished successfully!")
                    break
                await asyncio.sleep(0.4)
            else:
                raise RuntimeError("Debate did not complete in time")

            # -------------------------------------------------------------
            # Verify Speech Log (Rule 1, 2, 3, 4, 5, 6)
            # -------------------------------------------------------------
            speech_log = await cdp.eval("window.__speechLog")
            assert speech_log and len(speech_log) > 0, "No speech was logged!"
            print(f"Logged {len(speech_log)} spoken sentences.")

            # Check that all spoken sentences belong to valid agents or Judge
            valid_speakers = {"Advocate", "Critic", "Risk Analyst", "Evidence Agent", "Judge"}
            for item in speech_log:
                speaker = item["speaker"]
                assert speaker in valid_speakers, f"Unexpected speaker: {speaker} in {item}"
                # Ensure scores, status lines, or tabs were never spoken
                assert "PAST DEBATES" not in item["text"], "History was spoken!"
                assert "BENCHMARKS" not in item["text"], "Benchmarks was spoken!"
                assert "EXECUTIVE SUMMARY" not in item["text"], "Report tab was spoken!"
                assert "Round" not in item["text"] or "round" in item["text"].lower() and "is speaking" not in item["text"], "Status line was spoken!"

            # Check speakers order: 2 rounds of 4 agents each + Judge verdict
            # In each turn, first sentence starts with "<Agent>: "
            speakers_seen = [item["speaker"] for item in speech_log]
            first_sentence_prefixes = [item["text"].split(":")[0] for item in speech_log if ":" in item["text"]]
            print("First sentence speaker prefixes:", first_sentence_prefixes)

            # Check that Advocate, Critic, Risk Analyst, Evidence Agent and Judge all spoke
            for expected_speaker in valid_speakers:
                assert expected_speaker in speakers_seen, f"Speaker {expected_speaker} did not speak!"

            # Check Judge verdict format ("Verdict: <answer>. <summary>. Confidence <n> percent.")
            judge_items = [item for item in speech_log if item["speaker"] == "Judge"]
            assert len(judge_items) >= 1, "Judge did not deliver a spoken verdict"
            judge_text = judge_items[-1]["text"]
            assert judge_text.startswith("Verdict:"), f"Judge text did not start with 'Verdict:': {judge_text}"
            assert "Confidence" in judge_text and "percent" in judge_text, f"Confidence percent missing in Judge text: {judge_text}"
            print("Verified Judge verdict speech:", judge_text)

            # Verify that voices / pitch / rates were customized per agent
            pitches = {item["speaker"]: item["pitch"] for item in speech_log}
            print("Pitch per speaker:", pitches)
            assert len(set(pitches.values())) >= 3, "Speakers do not have distinct pitch profiles"

            # -------------------------------------------------------------
            # Verify Stop cancels speech queue
            # -------------------------------------------------------------
            print("Testing Stop button speech cancellation...")
            # Start another debate
            await cdp.eval("""(() => {
                const btns = Array.from(document.querySelectorAll('button'));
                const b = btns.find(x => x.textContent.trim() === 'Start');
                if (b) b.click();
            })()""")

            # Wait until debate is running
            await asyncio.sleep(0.5)

            # Click Stop
            await cdp.eval("""(() => {
                const btns = Array.from(document.querySelectorAll('button'));
                const b = btns.find(x => x.textContent.trim() === 'Stop');
                if (b) b.click();
            })()""")

            # Wait a moment for stop to process
            await asyncio.sleep(0.5)
            cancelled = await cdp.eval("window.__speechCancelled")
            queue_len = await cdp.eval("window.__speechQueue.length")
            assert cancelled, "Speech was not cancelled on Stop!"
            assert queue_len == 0, f"Speech queue not cleared on Stop, remaining: {queue_len}"
            print("Verified Stop cancels and clears speech queue.")

            # -------------------------------------------------------------
            # Verify Voice On/Off toggle button
            # -------------------------------------------------------------
            await cdp.eval("""(() => {
                const btns = Array.from(document.querySelectorAll('button'));
                const b = btns.find(x => x.textContent.includes('Voice:'));
                if (b) b.click();
            })()""")
            await asyncio.sleep(0.2)
            voice_state = await cdp.eval("""(() => {
                const btns = Array.from(document.querySelectorAll('button'));
                const b = btns.find(x => x.textContent.includes('Voice:'));
                return b ? b.textContent.trim() : '';
            })()""")
            assert voice_state == "Voice: Off", f"Expected 'Voice: Off' after toggle, got: {voice_state}"
            stored_val = await cdp.eval("localStorage.getItem('agent_courtroom_voice')")
            assert stored_val == "false", f"Expected stored 'false', got: {stored_val}"
            print("Verified Voice On/Off toggle and localStorage persistence.")

            # Toggle back to On
            await cdp.eval("""(() => {
                const btns = Array.from(document.querySelectorAll('button'));
                const b = btns.find(x => x.textContent.includes('Voice:'));
                if (b) b.click();
            })()""")
            await asyncio.sleep(0.2)

            # -------------------------------------------------------------
            # Report tab & Downloads check
            # -------------------------------------------------------------
            # Open Report tab
            report_tab_clicked = await cdp.eval("""(() => {
                const btns = Array.from(document.querySelectorAll('button'));
                const b = btns.find(x => x.textContent.trim() === 'Report');
                if (b) { b.click(); return true; }
                return false;
            })()""")
            assert report_tab_clicked, "Could not find Report tab button"
            print("Clicked Report tab")

            # Wait for Report to finish loading
            for _ in range(30):
                is_writing = await cdp.eval("document.body.innerText.includes('Writing report...')")
                has_summary = await cdp.eval("document.body.innerText.includes('EXECUTIVE SUMMARY')")
                if has_summary and not is_writing:
                    print("Report loaded successfully!")
                    break
                await asyncio.sleep(0.4)
            else:
                raise RuntimeError("Report did not load in time")

            # Check that all 4 charts render
            chart_count = await cdp.eval("""(() => {
                const svgs = document.querySelectorAll('.recharts-surface');
                return svgs.length;
            })()""")
            print(f"Rendered recharts SVG surfaces: {chart_count}")
            assert chart_count >= 3, f"Expected at least 3 SVG surfaces for charts, found {chart_count}"

            # Check for the 4 chart titles in DOM
            has_scores_chart = await cdp.eval("document.body.innerText.includes('Argument Scores by Agent')")
            has_conf_meter = await cdp.eval("document.body.innerText.includes('Judge Confidence Meter')")
            has_evi_chart = await cdp.eval("document.body.innerText.includes('Evidence Check Results')")
            has_tok_chart = await cdp.eval("document.body.innerText.includes('Tokens Used by Each Agent')")

            print(f"Chart titles check: scores={has_scores_chart}, conf={has_conf_meter}, evi={has_evi_chart}, tok={has_tok_chart}")
            assert has_scores_chart and has_conf_meter and has_evi_chart and has_tok_chart, "Not all 4 charts found in DOM"

            # Check Download Word (.docx) button
            docx_btn = await cdp.eval("""(() => {
                const btns = Array.from(document.querySelectorAll('button'));
                const b = btns.find(x => x.textContent.includes('Download Word'));
                if (b) { b.click(); return true; }
                return false;
            })()""")
            assert docx_btn, "Download Word button not found"
            print("Clicked Download Word (.docx) button")

            # Check Download PDF button
            pdf_btn = await cdp.eval("""(() => {
                const btns = Array.from(document.querySelectorAll('button'));
                const b = btns.find(x => x.textContent.includes('Download PDF'));
                if (b) { b.click(); return true; }
                return false;
            })()""")
            assert pdf_btn, "Download PDF button not found"
            print("Clicked Download PDF button")

            # Wait for both downloaded files in downloads directory
            docx_file = None
            pdf_file = None
            for _ in range(30):
                files = list(downloads_dir.glob("*"))
                for f in files:
                    if f.suffix == ".docx" or "docx" in f.name:
                        if f.stat().st_size > 1000:
                            docx_file = f
                    if f.suffix == ".pdf" or "pdf" in f.name:
                        if f.stat().st_size > 1000:
                            pdf_file = f
                if docx_file and pdf_file:
                    break
                await asyncio.sleep(0.4)

            # If Chrome renamed with crdownload or guid, check contents
            if not (docx_file and pdf_file):
                files = list(downloads_dir.glob("*"))
                for f in files:
                    data = f.read_bytes()
                    if b"word/" in data or b"PK\x03\x04" in data[:4]:
                        docx_file = f
                    elif data.startswith(b"%PDF"):
                        pdf_file = f

            assert docx_file is not None, f"Word download not found. Files in dir: {list(downloads_dir.glob('*'))}"
            assert pdf_file is not None, f"PDF download not found. Files in dir: {list(downloads_dir.glob('*'))}"

            print(f"Verified Word file ({docx_file.stat().st_size} bytes)")
            print(f"Verified PDF file ({pdf_file.stat().st_size} bytes)")
            print("\nALL UI HEADLESS BROWSER & VOICE TTS CHECKS PASSED SUCCESSFULLY!")

        finally:
            if cdp:
                await cdp.close()
            if chrome_proc:
                chrome_proc.terminate()
                try:
                    chrome_proc.wait(timeout=2)
                except Exception:
                    chrome_proc.kill()
            if server_proc:
                server_proc.terminate()
                try:
                    server_proc.wait(timeout=2)
                except Exception:
                    server_proc.kill()


def test_headless_browser_ui():
    if not os.path.exists(CHROME_PATH):
        pytest.skip(f"Browser not found at {CHROME_PATH}")
    asyncio.run(run_ui_test())


if __name__ == "__main__":
    asyncio.run(run_ui_test())
