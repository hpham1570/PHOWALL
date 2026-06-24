import sqlite3, uuid, json, asyncio, traceback, os
from datetime import datetime, timezone
from pathlib import Path
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

def load_keys():
    keys = {}
    try:
        with open("env.txt", "r") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    keys[k] = v
    except Exception:
        pass
    return keys

KEYS = load_keys()
OPENAI_KEY = KEYS.get("OPENAI_API_KEY")

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, field_validator
from openai import OpenAI
from duckduckgo_search import DDGS

if not OPENAI_KEY:
    print("\n  !!! ERROR: OPENAI_API_KEY not found in env.txt !!!\n")

ai_client = OpenAI(api_key=OPENAI_KEY)

async def call_ai(system_prompt, user_prompt, json_mode=False):
    kwargs = {"model": "gpt-4o-mini", "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]}
    if json_mode: kwargs["response_format"] = {"type": "json_object"}
    response = await asyncio.to_thread(ai_client.chat.completions.create, **kwargs)
    return response.choices[0].message.content

DB_PATH = Path("agentforge.db")

def get_db():
    conn = sqlite3.connect(str(DB_PATH)); conn.row_factory = sqlite3.Row; conn.execute("PRAGMA journal_mode=WAL"); return conn

def init_db():
    conn = get_db()
    conn.executescript("""CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, topic TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', progress INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, completed_at TEXT, error TEXT);CREATE TABLE IF NOT EXISTS agent_logs (id TEXT PRIMARY KEY, job_id TEXT NOT NULL, agent TEXT NOT NULL, message TEXT NOT NULL, timestamp TEXT NOT NULL);CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY, job_id TEXT NOT NULL UNIQUE, title TEXT NOT NULL, executive_summary TEXT, sections TEXT NOT NULL, qc_score REAL NOT NULL, qc_notes TEXT, qc_passed INTEGER NOT NULL DEFAULT 0, word_count INTEGER DEFAULT 0, created_at TEXT NOT NULL);CREATE INDEX IF NOT EXISTS idx_logs_job ON agent_logs(job_id);""")
    conn.commit(); conn.close(); print("  Database ready")

def create_job(topic):
    job_id = str(uuid.uuid4())[:8]; now = datetime.now(timezone.utc).isoformat(); conn = get_db(); conn.execute("INSERT INTO jobs (id,topic,status,created_at) VALUES (?,?,?,?)", (job_id, topic, "pending", now)); conn.commit(); conn.close()
    return {"id": job_id, "topic": topic, "status": "pending", "progress": 0, "created_at": now}

def list_jobs():
    conn = get_db(); rows = conn.execute("SELECT id,topic,status,progress,created_at,completed_at FROM jobs ORDER BY created_at DESC").fetchall(); conn.close(); return [dict(r) for r in rows]

def get_job(job_id):
    conn = get_db(); row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone(); conn.close(); return dict(row) if row else None

def update_job(job_id, status, progress, error=None):
    conn = get_db(); completed = datetime.now(timezone.utc).isoformat() if status in ("complete", "failed") else None; conn.execute("UPDATE jobs SET status=?,progress=?,completed_at=?,error=? WHERE id=?", (status, progress, completed, error, job_id)); conn.commit(); conn.close()

def add_log(job_id, agent, message):
    log_id = str(uuid.uuid4())[:8]; ts = datetime.now(timezone.utc).strftime("%H:%M:%S"); conn = get_db(); conn.execute("INSERT INTO agent_logs (id,job_id,agent,message,timestamp) VALUES (?,?,?,?,?)", (log_id, job_id, agent, message, ts)); conn.commit(); conn.close()

def get_logs(job_id):
    conn = get_db(); rows = conn.execute("SELECT id,agent,message,timestamp FROM agent_logs WHERE job_id=? ORDER BY timestamp", (job_id,)).fetchall(); conn.close(); return [dict(r) for r in rows]

def save_report(job_id, report):
    report_id = str(uuid.uuid4())[:8]; now = datetime.now(timezone.utc).isoformat(); sections_json = json.dumps(report["sections"]); wc = sum(len(s["content"].split()) for s in report["sections"]) + len(report.get("executive_summary", "").split()); conn = get_db(); conn.execute("INSERT INTO reports (id,job_id,title,executive_summary,sections,qc_score,qc_notes,qc_passed,word_count,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (report_id, job_id, report["title"], report.get("executive_summary"), sections_json, report["qc_score"], report.get("qc_notes", ""), 1 if report.get("qc_passed") else 0, wc, now)); conn.commit(); conn.close()

def get_report(job_id):
    conn = get_db(); row = conn.execute("SELECT * FROM reports WHERE job_id=?", (job_id,)).fetchone(); conn.close()
    if not row: return None
    d = dict(row); d["sections"] = json.loads(d["sections"]); d["qc_passed"] = bool(d["qc_passed"]); return d

@dataclass
class JobState:
    job_id: str; topic: str; brief: dict = None; sections: list = field(default_factory=list); qc_result: dict = None; report: dict = None

class MemoryStore:
    def __init__(self): self._store = {}
    def create(self, job_id, topic): s = JobState(job_id=job_id, topic=topic); self._store[job_id] = s; return s
    def remove(self, job_id): self._store.pop(job_id, None)

mem = MemoryStore()

async def agent_intake(topic):
    sys_p = 'Return ONLY JSON: {"depth": "intermediate", "sections": [{"id": 1, "title": "Title", "focus": "Focus"}]} Decompose topic into 3-4 sections.'
    res = await call_ai(sys_p, f"Topic: {topic}", True); brief = json.loads(res); brief["topic"] = topic; return brief

async def agent_search(topic, brief):
    search_queries = [f"{topic} {sec['focus']}" for sec in brief["sections"][:2]]
    context = f"Real-time Search Results for '{topic}':\n"
    def do_search():
        results = []
        try:
            with DDGS() as ddgs:
                for r in ddgs.text(search_queries[0], max_results=3): results.append(r)
        except Exception as e: print(f"Search error: {e}")
        return results
    res = await asyncio.to_thread(do_search)
    for r in res: context += f"- {r.get('title', 'No title')}: {r.get('body', 'No content')}\n"
    return context

async def agent_assembly(topic, section, search_context):
    sys_p = f"Write a 2-3 paragraph analytical section. Topic: '{topic}'. Focus: {section['focus']}.\n\nUse these real-world facts to inform your writing:\n{search_context}"
    content = await call_ai(sys_p, f"Write section: '{section['title']}'")
    return {"section_id": section["id"], "title": section["title"], "content": content.strip(), "word_count": len(content.split())}

async def agent_qc(topic, sections, attempt=1):
    text = "\n\n".join([f"### {s['title']}\n{s['content']}" for s in sections])
    sys_p = 'You are an editor. Grade generously: 80 baseline if on-topic and coherent. +10 if specific examples. +10 if exceptionally clear. Return ONLY JSON: {"score": 85, "passed": true, "total_words": 500, "feedback": ["reason"]}'
    qc = json.loads(await call_ai(sys_p, f"Topic: {topic}\n\n{text}", True)); qc["attempt"] = attempt; return qc

async def agent_reporter(topic, brief, sections, qc):
    text = "\n\n".join([f"### {s['title']}\n{s['content']}" for s in sections])
    sys_p = 'Return ONLY JSON: {"executive_summary": "3 sentences", "conclusion": "3 sentences"}'
    edits = json.loads(await call_ai(sys_p, f"Topic: {topic}\n\n{text}", True))
    return {"title": f"Report: {topic}", "executive_summary": edits["executive_summary"], "sections": [{"id": s["section_id"], "title": s["title"], "content": s["content"]} for s in sections], "conclusion": edits["conclusion"], "qc_score": qc["score"], "qc_passed": qc["passed"], "qc_notes": "; ".join(qc.get("feedback", []))}

async def run_pipeline(job_id, topic, broadcast):
    st = mem.create(job_id, topic)
    try:
        await broadcast(job_id, {"type": "status", "status": "intake", "progress": 5})
        await broadcast(job_id, {"type": "log", "agent": "intake", "message": f'Analyzing: "{topic}"', "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S")})
        brief = await agent_intake(topic); st.brief = brief
        await broadcast(job_id, {"type": "log", "agent": "intake", "message": f"Decomposed into {len(brief['sections'])} sections", "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S")})
        
        await broadcast(job_id, {"type": "status", "status": "searching", "progress": 15})
        await broadcast(job_id, {"type": "log", "agent": "search", "message": "Searching DuckDuckGo for live data...", "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S")})
        search_context = await agent_search(topic, brief)
        await broadcast(job_id, {"type": "log", "agent": "search", "message": f"Found live context ({len(search_context)} chars)", "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S")})
        
        await broadcast(job_id, {"type": "status", "status": "assembling", "progress": 30})
        for sec in brief["sections"]:
            await broadcast(job_id, {"type": "log", "agent": f"assembly-{sec['id']}", "message": f"Drafting: {sec['title']}", "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S")})

        async def draft_and_log(sec):
            draft = await agent_assembly(topic, sec, search_context)
            await broadcast(job_id, {"type": "log", "agent": f"assembly-{sec['id']}", "message": f"Complete ({draft['word_count']} words)", "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S")})
            return draft

        results = await asyncio.gather(*[draft_and_log(sec) for sec in brief["sections"]])
        st.sections.extend(results)

        await broadcast(job_id, {"type": "status", "status": "qc", "progress": 70})
        qc = await agent_qc(topic, st.sections); st.qc_result = qc
        await broadcast(job_id, {"type": "log", "agent": "qc", "message": f"Score: {qc['score']}/100", "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S")})
        await broadcast(job_id, {"type": "status", "status": "reporting", "progress": 85})
        report = await agent_reporter(topic, brief, st.sections, qc)
        save_report(job_id, report); update_job(job_id, "complete", 100)
        await broadcast(job_id, {"type": "complete", "job_id": job_id})
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"; update_job(job_id, "failed", 0, error=msg); await broadcast(job_id, {"type": "error", "message": msg})
    finally: mem.remove(job_id)

class WSMgr:
    def __init__(self): self._c = {}
    async def connect(self, jid, ws): await ws.accept(); self._c.setdefault(jid, []).append(ws)
    def disconnect(self, jid, ws):
        c = self._c.get(jid, [])
        if ws in c: c.remove(ws)
        if not c: self._c.pop(jid, None)
    async def broadcast(self, jid, data):
        for ws in list(self._c.get(jid, [])):
            try: await ws.send_json(data)
            except: pass

wsm = WSMgr()

@asynccontextmanager
async def lifespan(app):
    init_db()
    if not OPENAI_KEY: print("\n  !!! WARNING: No OPENAI_API_KEY found !!!\n")
    yield

app = FastAPI(lifespan=lifespan)

class JobReq(BaseModel):
    topic: str
    @field_validator("topic")
    @classmethod
    def check(cls, v):
        v = v.strip()
        if not v: raise ValueError("Cannot be empty")
        return v

@app.post("/api/jobs")
async def api_new(req: JobReq):
    job = create_job(req.topic); asyncio.create_task(run_pipeline(job["id"], job["topic"], wsm.broadcast)); return job

@app.get("/api/jobs")
async def api_list(): return list_jobs()

@app.get("/api/jobs/{jid}/logs")
async def api_logs(jid: str):
    if not get_job(jid): raise HTTPException(404); return get_logs(jid)

@app.get("/api/jobs/{jid}/report")
async def api_report(jid: str):
    r = get_report(jid)
    if not r: raise HTTPException(404)
    return r

@app.websocket("/ws/jobs/{jid}")
async def ws_ep(ws: WebSocket, jid: str):
    await wsm.connect(jid, ws)
    try:
        while True: await ws.receive_text()
    except WebSocketDisconnect: wsm.disconnect(jid, ws)

@app.get("/", response_class=HTMLResponse)
async def page():
    return """<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>AgentForge</title><style>*{box-sizing:border-box;margin:0;padding:0}body{background:#0c0c10;color:#e8e8ed;font-family:system-ui,sans-serif;min-height:100vh}header{border-bottom:1px solid #2a2a35;background:rgba(22,22,29,.8);position:sticky;top:0;z-index:50}.in{max-width:720px;margin:0 auto;padding:0 24px}.hdr{height:52px;display:flex;align-items:center;justify-content:space-between}.logo{display:flex;align-items:center;gap:10px;font-weight:600;font-size:14px}.lico{width:28px;height:28px;border-radius:6px;background:#f59e0b;display:flex;align-items:center;justify-content:center}main{padding:32px 0}.cd{background:#16161d;border:1px solid #2a2a35;border-radius:12px;padding:24px;margin-bottom:24px}label{display:block;font-size:13px;color:#7a7a90;margin-bottom:12px}.row{display:flex;gap:12px}input{flex:1;background:#0c0c10;border:1px solid #2a2a35;border-radius:8px;padding:10px 16px;color:#e8e8ed;font-size:14px;outline:none}input:focus{border-color:#f59e0b}input::placeholder{color:#7a7a90}button{background:#f59e0b;color:#0c0c10;border:none;border-radius:8px;padding:10px 20px;font-weight:600;font-size:14px;cursor:pointer;transition:background .2s}button:hover{background:#fbbf24}button:disabled{opacity:.4;cursor:not-allowed}.hd{display:none!important}.mt{color:#7a7a90}.sm{font-size:13px}.xs{font-size:11px}.mn{font-family:monospace}.step{display:flex;align-items:center;margin-top:20px}.sc{display:flex;flex-direction:column;align-items:center;gap:6px;min-width:48px}.si{width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;transition:all .3s}.sl{font-size:9px;color:#7a7a90}.sln{height:2px;flex:1;margin:0 6px;transition:background .3s}.b1{background:#2a2a35;color:#7a7a90}.b2{background:#f59e0b;color:#0c0c10;animation:gl 2s infinite}@keyframes gl{0%,100%{box-shadow:0 0 0 0 rgba(245,158,11,.4)}50%{box-shadow:0 0 0 8px rgba(245,158,11,0)}}.b3{background:#10b981;color:#0c0c10}.l1{background:#2a2a35}.l3{background:#10b981}.logs{max-height:220px;overflow-y:auto;font-family:monospace;font-size:11px;line-height:1.7}.logs::-webkit-scrollbar{width:4px}.logs::-webkit-scrollbar-thumb{background:#2a2a35;border-radius:2px}.ll{animation:fi .2s}@keyframes fi{from{opacity:0;transform:translateY(3px)}to{opacity:1;transform:translateY(0)}}.ci{color:#7a7a90}.ca{color:#06b6d4}.cq{color:#f59e0b}.cr{color:#10b981}.cs{color:#a78bfa}.bg{font-size:11px;font-weight:700;padding:4px 10px;border-radius:6px;border:1px solid}.bo{background:rgba(16,185,129,.15);color:#10b981;border-color:rgba(16,185,129,.3)}.bw{background:rgba(245,158,11,.15);color:#f59e0b;border-color:rgba(245,158,11,.3)}.meta{display:flex;gap:24px;margin-top:16px;font-size:11px;color:#7a7a90}.sb{margin-bottom:32px}.sb h3{font-size:14px;font-weight:600;margin-bottom:12px;display:flex;gap:8px}.sb h3 span{color:#f59e0b;font-family:monospace;font-size:11px}.sb p{font-size:13px;color:rgba(232,232,237,.85);line-height:1.75;margin-bottom:10px;white-space:pre-wrap}.cn{border-top:1px solid #2a2a35;padding-top:24px}.cn h3{font-size:13px;font-weight:600;color:#f59e0b;margin-bottom:8px}.cn p{font-size:13px;color:#7a7a90;line-height:1.75}.ec{background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.25);border-radius:12px;padding:24px}.ec h3{font-size:13px;font-weight:600;color:#ef4444;margin-bottom:8px}.ec p{font-size:13px;color:rgba(239,68,68,.8);font-family:monospace}.hi{width:100%;display:flex;align-items:center;justify-content:space-between;background:#16161d;border:1px solid #2a2a35;border-radius:8px;padding:12px 16px;cursor:pointer;text-align:left;color:inherit}.hi:hover{border-color:rgba(245,158,11,.4)}.hl{display:flex;align-items:center;gap:12px;min-width:0}.hl .tp{font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.hr{display:flex;align-items:center;gap:12px;flex-shrink:0;margin-left:16px}.sok{color:#10b981}.sfl{color:#ef4444}.spn{color:#7a7a90}.pdf-btn{background:transparent;border:1px solid #2a2a35;color:#7a7a90;padding:6px 12px;font-size:12px;border-radius:6px;cursor:pointer}.pdf-btn:hover{border-color:#7a7a90;color:#e8e8ed}@media print{header,.cd:first-of-type,#act,#erp,#hw,.pdf-btn{display:none!important}#rpt{display:block!important}.cd{border:none!important;background:white!important}.sb p, .cn p, .sm{color:black!important}h2, h3{color:black!important}body{background:white!important}}</style></head><body><header><div class="in"><div class="hdr"><div class="logo"><div class="lico"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#0c0c10" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg></div>AgentForge</div></div></div></header><main class="in"><div class="cd"><label for="inp">What should the agents build?</label><div class="row"><input id="inp" type="text" placeholder="e.g. Newest Apple iPhone features" maxlength="500"><button id="btn" onclick="go()">&#9654; Run Pipeline</button></div></div><div id="act" class="hd"><div class="cd"><div style="display:flex;justify-content:space-between;align-items:start;margin-bottom:4px"><span class="sm" id="at"></span><span class="xs mn mt" id="ai"></span></div><div class="step" id="stp"></div></div><div class="cd"><div class="xs" style="font-weight:600;color:#7a7a90;text-transform:uppercase;letter-spacing:.05em;margin-bottom:12px">Agent Log</div><div class="logs" id="lg"></div></div></div><div id="rpt" class="hd"><div class="cd"><div style="display:flex;justify-content:space-between;align-items:start;gap:16px"><h2 id="rt" style="font-size:18px;font-weight:700;flex:1"></h2><div style="display:flex;gap:8px;align-items:center"><div id="rb"></div><button class="pdf-btn" onclick="window.print()">&#128196; PDF</button></div></div><p id="rs" class="sm mt" style="margin-top:12px;line-height:1.7"></p><div id="rm" class="meta"></div></div><div class="cd" id="rsc"></div><div class="cd"><div class="cn"><h3>Conclusion</h3><p id="rc"></p></div></div></div><div id="erp" class="hd"><div class="ec"><h3>Pipeline Failed</h3><p id="em"></p></div></div><div id="hw" class="hd"><div class="xs" style="font-weight:600;color:#7a7a90;text-transform:uppercase;letter-spacing:.05em;margin-bottom:12px">History</div><div id="hl" style="display:flex;flex-direction:column;gap:8px"></div></div></main><script>var aid=null,ws=null,jobs=[];var SK=[{k:'intake',l:'Intake',i:'&#11015;'},{k:'searching',l:'Search',i:'&#128269;'},{k:'assembling',l:'Assembly',i:'&#9881;'},{k:'qc',l:'QC',i:'&#10003;'},{k:'reporting',l:'Report',i:'&#128196;'}];var SO=SK.map(function(s){return s.k});var FN=['complete','failed'];function esc(s){var d=document.createElement('div');d.textContent=s;return d.innerHTML}function ft(iso){if(!iso)return '';var d=new Date(iso);return d.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}function sstp(cur){var el=document.getElementById('stp'),ci=SO.indexOf(cur),fn=FN.indexOf(cur)>=0,h='';SK.forEach(function(s,i){var c='b1',lc='l1';if(fn){c='b3';lc='l3'}else if(i<ci){c='b3';lc='l3'}else if(i===ci){c='b2';lc='l1'}if(i>0)h+='<div class="sln '+lc+'"></div>';h+='<div class="sc"><div class="si '+c+'">'+s.i+'</div><div class="sl">'+s.l+'</div></div>'});el.innerHTML=h}function alg(ag,msg,ts){var c=document.getElementById('lg'),d=document.createElement('div');d.className='ll';var cc=ag==='search'?'cs':ag.indexOf('assembly')===0?'ca':ag==='qc'?'cq':ag==='reporter'?'cr':'ci';d.innerHTML='<span class="mt" style="opacity:.5">'+ts+'</span> <span class="'+cc+'">['+ag+']</span> '+esc(msg);c.appendChild(d);c.scrollTop=c.scrollHeight}function shr(r){var p=document.getElementById('rpt');p.classList.remove('hd');document.getElementById('rt').textContent=r.title;document.getElementById('rs').textContent=r.executive_summary;var sc=r.qc_score,bc=sc>=85?'bo':'bw';document.getElementById('rb').innerHTML='<span class="bg mn '+bc+'">'+sc+'/100 QC</span>';document.getElementById('rm').innerHTML='<span>Words: '+(r.word_count||'&#8212;')+'</span><span>Sections: '+r.sections.length+'</span>';var sh='';r.sections.forEach(function(s,i){sh+='<div class="sb"><h3><span>'+(i+1)+'.</span>'+esc(s.title)+'</h3>';s.content.split('\\n\\n').forEach(function(pp){sh+='<p>'+esc(pp)+'</p>'});sh+='</div>'});document.getElementById('rsc').innerHTML=sh;document.getElementById('rc').textContent=r.conclusion;p.scrollIntoView({behavior:'smooth',block:'start'})}function rh(){var arr=jobs.filter(function(j){return j.id!==aid});var w=document.getElementById('hw'),l=document.getElementById('hl');if(!arr.length){w.classList.add('hd');return}w.classList.remove('hd');l.innerHTML=arr.map(function(j){var ic=j.status==='complete'?'&#10003;':j.status==='failed'?'&#10016;':'&#9675;';var cc=j.status==='complete'?'sok':j.status==='failed'?'sfl':'spn';return '<button class="hi" onclick="lj(\\''+j.id+'\\')"><div class="hl"><span class="'+cc+'">'+ic+'</span><span class="tp">'+esc(j.topic)+'</span></div><div class="hr"><span class="xs mn mt">'+j.id+'</span><span class="xs mt">'+ft(j.created_at)+'</span></div></button>'}).join('')}async function go(){var inp=document.getElementById('inp'),topic=inp.value.trim();if(!topic){inp.focus();return}var btn=document.getElementById('btn');btn.disabled=true;try{var r=await fetch('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({topic:topic})});if(!r.ok){var e=await r.json();throw new Error(e.detail||'Failed')}var job=await r.json();inp.value='';actv(job)}catch(e){alert(e.message)}finally{btn.disabled=false}}function actv(job){aid=job.id;document.getElementById('act').classList.remove('hd');document.getElementById('at').textContent=job.topic;document.getElementById('ai').textContent=job.id;sstp('intake');document.getElementById('lg').innerHTML='';document.getElementById('rpt').classList.add('hd');document.getElementById('erp').classList.add('hd');cws(job.id);jobs.unshift(job);rh();document.getElementById('act').scrollIntoView({behavior:'smooth',block:'start'})}function cws(jid){if(ws){ws.onclose=null;ws.close()}var p=location.protocol==='https:'?'wss:':'ws:';ws=new WebSocket(p+'//'+location.host+'/ws/jobs/'+jid);ws.onmessage=function(e){try{hdl(JSON.parse(e.data))}catch(err){console.error(err)}};ws.onclose=function(){}}function hdl(d){if(d.type==='status'){sstp(d.status)}if(d.type==='log')alg(d.agent,d.message,d.timestamp);if(d.type==='complete'){fetch('/api/jobs/'+d.job_id+'/report').then(function(r){return r.json()}).then(function(r){if(r)shr(r)});var j=jobs.find(function(x){return x.id===d.job_id});if(j){j.status='complete';j.progress=100}fetch('/api/jobs').then(function(r){return r.json()}).then(function(r){jobs=r;rh()})}if(d.type==='error'){document.getElementById('erp').classList.remove('hd');document.getElementById('em').textContent=d.message;var j=jobs.find(function(x){return x.id===aid});if(j)j.status='failed';rh()}}async function lj(jid){var r=await fetch('/api/jobs/'+jid+'/report');if(!r.ok){alert('Report not available');return}var report=await r.json();if(aid!==jid){document.getElementById('act').classList.add('hd');document.getElementById('erp').classList.add('hd')}shr(report)}document.getElementById('inp').addEventListener('keydown',function(e){if(e.key==='Enter')go()});fetch('/api/jobs').then(function(r){return r.json()}).then(function(r){jobs=r;rh()}).catch(function(){});</script></body></html>"""

if __name__ == "__main__":
    import uvicorn
    print("\n  AgentForge (AI + Live Search) starting...\n  Open http://localhost:8000\n")
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)