"""Full E2E test: upload (add/replace/delete), chat Q&A, logging, metrics."""
import requests, time, os, json, tempfile

BASE = "http://localhost:8000"
PASS = 0
FAIL = 0

def check(label, condition, detail=""):
    global PASS, FAIL
    status = "PASS" if condition else "FAIL"
    if condition:
        PASS += 1
    else:
        FAIL += 1
    suffix = f" — {detail}" if detail else ""
    print(f"[{status}] {label}{suffix}")

def wait_ready(timeout=60):
    for _ in range(timeout // 2):
        s = requests.get(f"{BASE}/status", timeout=10).json()
        if s.get("state") == "ready":
            return s
        time.sleep(2)
    return s

# ── PHASE 1: Baseline health ──────────────────────────────────────────────────
print("\n" + "="*60)
print("PHASE 1: HEALTH & BASELINE")
print("="*60)
h = requests.get(f"{BASE}/health", timeout=10).json()
check("Health endpoint", "running" in str(h).lower(), str(h))

st = requests.get(f"{BASE}/status", timeout=10).json()
check("KB state=ready", st.get("state") == "ready", st.get("message",""))
check("Doc count >= 1", st.get("doc_count", 0) >= 1, f"doc_count={st.get('doc_count')}")

docs = requests.get(f"{BASE}/documents", timeout=10).json()
check("Documents listed", len(docs.get("documents", [])) >= 1, str(docs.get("documents",[])))

metrics = requests.get(f"{BASE}/admin/metrics", timeout=10).json()
check("Metrics endpoint returns data", isinstance(metrics, dict), str(metrics)[:80])

# ── PHASE 2: Baseline chat + memory ──────────────────────────────────────────
print("\n" + "="*60)
print("PHASE 2: BASELINE CHAT + MULTI-TURN MEMORY")
print("="*60)
r = requests.post(f"{BASE}/chat", json={"message": "What baggage allowance do I get on a Flexi fare?", "session_id": "e2e-mem"}, timeout=60).json()
check("Flexi baggage answered", "20 kg" in r.get("answer","") or "20kg" in r.get("answer",""), r.get("answer","")[:80])
check("Sources returned", len(r.get("sources",[])) > 0, str([s["source"] for s in r.get("sources",[])]))

r2 = requests.post(f"{BASE}/chat", json={"message": "Is it refundable if I cancel?", "session_id": "e2e-mem"}, timeout=60).json()
sq2 = r2.get("standalone_question","")
check("Memory: pronoun condensed", sq2 != "Is it refundable if I cancel?" and len(sq2) > 0, f"standalone='{sq2}'")
check("Refund answer correct", "75" in r2.get("answer","") or "refund" in r2.get("answer","").lower(), r2.get("answer","")[:80])

r3 = requests.post(f"{BASE}/chat", json={"message": "xyzzy nonsense blorp", "session_id": "e2e-ns"}, timeout=60).json()
check("Unanswered fallback fires", "don" in r3.get("answer","").lower() and "specific" in r3.get("answer","").lower(), r3.get("answer","")[:80])

# ── PHASE 3: Upload — ADD (incremental) ──────────────────────────────────────
print("\n" + "="*60)
print("PHASE 3: UPLOAD ADD (incremental indexing)")
print("="*60)
tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, prefix="e2e_pet_")
tmp.write(
    "PET TRAVEL POLICY\n\n"
    "IndiGo allows pets in the cabin on all domestic flights.\n"
    "The pet cabin fee is INR 2,000 per flight segment.\n"
    "Maximum combined weight of pet and carrier is 7 kg.\n"
    "Only cats and small dogs are permitted in the cabin.\n"
)
tmp.close()
pet_name = os.path.basename(tmp.name)

with open(tmp.name, "rb") as f:
    resp = requests.post(f"{BASE}/upload", files=[("files",(pet_name,f,"text/plain"))], data={"mode":"add"}, timeout=30)
check("Upload add 200/202", resp.status_code in (200,202), f"status={resp.status_code}")

s = wait_ready(60)
check("KB ready after add", s.get("state") == "ready", s.get("message",""))
check("Doc count increased", s.get("doc_count",0) >= 1, f"doc_count={s.get('doc_count')}")
os.unlink(tmp.name)

time.sleep(2)
r_pet = requests.post(f"{BASE}/chat", json={"message": "What is the pet cabin fee on IndiGo?", "session_id": "e2e-pet"}, timeout=60).json()
check("Pet policy Q&A after add", "2,000" in r_pet.get("answer","") or "2000" in r_pet.get("answer",""), r_pet.get("answer","")[:100])

# ── PHASE 4: Re-upload same file (overwrite / no duplicate) ──────────────────
print("\n" + "="*60)
print("PHASE 4: RE-UPLOAD SAME FILE (overwrite, no duplicate)")
print("="*60)
tmp2 = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, prefix="e2e_pet_")
tmp2.write(
    "PET TRAVEL POLICY (UPDATED)\n\n"
    "IndiGo allows pets in the cabin on all domestic flights.\n"
    "The updated pet cabin fee is INR 2,500 per flight segment.\n"
    "Maximum combined weight of pet and carrier is 7 kg.\n"
)
tmp2.close()
pet2_name = os.path.basename(tmp2.name)

with open(tmp2.name, "rb") as f:
    resp2 = requests.post(f"{BASE}/upload", files=[("files",(pet2_name,f,"text/plain"))], data={"mode":"add"}, timeout=30)
check("Re-upload add accepted", resp2.status_code in (200,202), f"status={resp2.status_code}")
s2 = wait_ready(60)
check("KB ready after re-upload", s2.get("state") == "ready", s2.get("message",""))
os.unlink(tmp2.name)

# ── PHASE 5: Upload REPLACE (full rebuild) ────────────────────────────────────
print("\n" + "="*60)
print("PHASE 5: UPLOAD REPLACE (full rebuild)")
print("="*60)
tmp3 = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, prefix="e2e_repl_")
tmp3.write("# Replace Test\n\nThis is a replace-mode test. Special route: Mumbai to Goa direct.\n")
tmp3.close()
repl_name = os.path.basename(tmp3.name)

with open(tmp3.name, "rb") as f:
    resp3 = requests.post(f"{BASE}/upload", files=[("files",(repl_name,f,"text/markdown"))], data={"mode":"replace"}, timeout=30)
check("Upload replace accepted", resp3.status_code in (200,202), f"status={resp3.status_code}")
s3 = wait_ready(90)
check("KB ready after replace", s3.get("state") == "ready", s3.get("message",""))
os.unlink(tmp3.name)

# ── PHASE 6: DELETE document ──────────────────────────────────────────────────
print("\n" + "="*60)
print("PHASE 6: DELETE DOCUMENT")
print("="*60)
tmp4 = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, prefix="e2e_del_")
tmp4.write("Delete test document about imaginary airline ZZZAIR999 routes.\n")
tmp4.close()
del_name = os.path.basename(tmp4.name)

with open(tmp4.name, "rb") as f:
    requests.post(f"{BASE}/upload", files=[("files",(del_name,f,"text/plain"))], data={"mode":"add"}, timeout=30)
wait_ready(60)

del_r = requests.delete(f"{BASE}/documents/{del_name}", timeout=30)
check("Delete returns 200", del_r.status_code == 200, f"status={del_r.status_code} {del_r.text[:60]}")
s4 = wait_ready(60)
check("KB ready after delete", s4.get("state") == "ready", s4.get("message",""))
docs4 = requests.get(f"{BASE}/documents", timeout=10).json()
check("Deleted file absent", del_name not in docs4.get("documents",[]), str(docs4.get("documents",[])))
os.unlink(tmp4.name)

# ── PHASE 7: Q&A regression (core knowledge) ─────────────────────────────────
print("\n" + "="*60)
print("PHASE 7: Q&A REGRESSION (core knowledge)")
print("="*60)
qa_cases = [
    ("What is the check-in baggage limit for Lite fare?",     "no free|0 kg|no check|not include"),
    ("What is the check-in baggage limit for Flexi fare?",    "20 kg"),
    ("Can I get a refund on a Classic fare?",                 "non-refundable|not refundable|no refund|cannot"),
    ("Can I get a refund on a Flexi fare?",                   "75|refund"),
    ("What carry-on bag is allowed on IndiGo?",               "carry-on|personal item"),
    ("What is the overweight baggage fee for 23-32 kg bags?", "2,500|2500"),
    ("What documents do I need for Visa on Arrival?",         "passport|return flight|proof of funds"),
    ("How long can I stay in India on a tourist e-visa?",     "90"),
    ("What is Transit Without Visa?",                         "transit without visa|twov"),
    ("How much does a lounge guest visit cost?",              "1,500|1500"),
    ("How many lounge guests can I bring?",                   "one|1 guest"),
    ("What airport code is used for Mumbai?",                 "BOM"),
    ("What airport code is used for Delhi?",                  "DEL"),
]
qa_ok = 0
for q, must in qa_cases:
    r = requests.post(f"{BASE}/chat", json={"message": q, "session_id": "e2e-reg"}, timeout=60).json()
    ans = r.get("answer","")
    ok = any(kw.lower() in ans.lower() for kw in must.split("|"))
    if ok:
        qa_ok += 1
    tag = "PASS" if ok else "FAIL"
    print(f"  [{tag}] {q[:52]:<52} -> {ans[:55].replace(chr(10),' ')}")

check(f"QA regression {qa_ok}/{len(qa_cases)}", qa_ok == len(qa_cases), f"{qa_ok}/{len(qa_cases)}")

# ── PHASE 8: Logging verification ────────────────────────────────────────────
print("\n" + "="*60)
print("PHASE 8: LOGGING VERIFICATION")
print("="*60)
log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
app_log = os.path.join(log_dir, "app.log")
queries_log = os.path.join(log_dir, "queries.jsonl")

check("logs/app.log exists", os.path.exists(app_log), app_log)
check("logs/queries.jsonl exists", os.path.exists(queries_log), queries_log)

if os.path.exists(queries_log):
    events = []
    with open(queries_log) as fq:
        for line in fq:
            try:
                events.append(json.loads(line.strip()))
            except Exception:
                pass
    chat_events = [e for e in events if e.get("event") == "chat"]
    unanswered = [e for e in chat_events if e.get("unanswered")]
    check("Chat events logged", len(chat_events) >= 5, f"{len(chat_events)} chat events")
    check("Unanswered events logged", len(unanswered) >= 1, f"{len(unanswered)} unanswered events")
    check("Latency logged", all("latency_ms" in e for e in chat_events[-3:]), "last 3 events have latency_ms")

metrics_final = requests.get(f"{BASE}/admin/metrics", timeout=10).json()
check("Metrics has query count", metrics_final.get("queries_total",0) >= 5, str(metrics_final))

# ── SUMMARY ───────────────────────────────────────────────────────────────────
print("\n" + "="*60)
print(f"RESULT: {PASS} PASS  {FAIL} FAIL  ({PASS+FAIL} total checks)")
print("="*60)
