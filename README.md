# GrowthTwin backend

One FastAPI project, **two dashboards**, one Supabase schema:

| | What | UI | API prefix |
|---|---|---|---|
| **Section 1** | Advisor: should I grow crop X? (rules → 3-scenario economics → rating → narrative) | `/` | `/advisor`, `/expert`, `/meta` |
| **Section 2** | Plot twin: full crop life, day 0 → harvest/death, sensors, auto-irrigation, questions | `/` (same page, second tab) | `/twin` |

---

## 1. Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill SUPABASE_*; leave blank to run fully in-memory
# Supabase: paste supabase/schema.sql into the SQL editor once (creates Section 1 + Section 2 tables)
uvicorn app.main:app --reload   # http://localhost:8000
pytest -q
```

### URLs (local → replace `http://localhost:8000` with your deployed domain)

| URL | Purpose |
|---|---|
| `http://localhost:8000/` | Section 1 dashboard (চাষের পরামর্শ) |
| `http://localhost:8000/demo.html` | Sentinel demo console (simulated sensor scenarios + field checklist) |
| `http://localhost:8000/docs` | Swagger UI (try every endpoint in the browser) |
| `http://localhost:8000/redoc` | ReDoc reference |
| `http://localhost:8000/openapi.json` | Machine-readable API spec (generate a Next.js/TS client from this) |
| `http://localhost:8000/health` | Health check → `{"ok":true,"store":"memory"\|"supabase"}` |

The UIs are served from the same origin as the API, so no CORS setup is needed for them.
A separate frontend (e.g. Next.js on `http://localhost:3000`) must be listed in `CORS_ORIGINS`.

### Environment variables (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `APP_ENV` | `dev` | `prod` refuses to boot unless `AUTH_REQUIRED=true` |
| `AUTH_REQUIRED` | `false` | `true` = verify Supabase JWT; `false` = trust dev headers (never in prod) |
| `SENSOR_INGEST_TOKEN` | empty | Long random secret for ESP32 `X-Sensor-Token`; empty disables device ingestion |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed origins |
| `SUPABASE_URL` | empty | Project URL. Empty (with key) = in-memory store, data lost on restart |
| `SUPABASE_SERVICE_KEY` | empty | **service_role** key, server only, never in the browser/git |
| `SUPABASE_ANON_KEY` | empty | Public anon key. Needed for `/auth/login`, `/auth/register`, `/auth/refresh` when `AUTH_REQUIRED=true` |
| `SIGNUP_ENABLED` | `true` | `false` closes public registration |
| `XAI_API_KEY` | empty | Optional Grok key. Without it, Bengali template text is used |
| `GROK_MODEL` | `grok-4` | Check the current name in the xAI console |
| `SMS_PROVIDER` | `none` | `none` = SMS simulated (logged as `sms` events only); `webhook` = POST `{"to","text"}` to `SMS_WEBHOOK_URL` |
| `SMS_WEBHOOK_URL` | empty | Your SMS gateway adapter URL (provider-agnostic) |
| `DISEASE_MIN_SCORE` | `0.70` | Photo model score below this → result is "unknown" |
| `DISEASE_REVIEW_SCORE` | `0.85` | A disease label below this → also queued for expert review |

---

## 2. Authentication (all endpoints except `/health`, `/meta/*`, `/twin/meta`, static pages)

**Dev mode** (`AUTH_REQUIRED=false`): send headers
```
X-Dev-User: farmer1          # who you are (default "anon")
X-Dev-Role: farmer           # farmer | expert | admin (default farmer)
```
**Prod** (`AUTH_REQUIRED=true`): sign in with Supabase Auth, then send
```
Authorization: Bearer <supabase_access_token>
```
Role comes from the user's **app_metadata** (`{"role":"expert"}`), set from the dashboard/server only (never `user_metadata`, which users can edit).
The built-in UIs read the token from `localStorage["gt_token"]` if present.

Ownership: sessions (Section 1) and plots (Section 2) belong to the user who created them. Other farmers get 403/404; `expert` and `admin` can read all.

### Common errors
| Code | Meaning |
|---|---|
| 400 | Invalid action/answer/value (message in Bengali in `detail`) |
| 401 | Missing/invalid bearer token (prod mode) |
| 403 | Not your session, or role not allowed |
| 404 | Session/plot not found (also returned for another user's plot) |
| 422 | Request body failed validation |

---

### Login, register, roles (Supabase Auth)
Supabase dashboard: Authentication > Providers > Email enabled. Decide whether "Confirm email" is on (on = register returns `confirm_email`, off = signed in at once).
| Endpoint | Body | Result |
|---|---|---|
| `GET /auth/config` | | `{auth_required, signup_enabled, configured, roles}` |
| `POST /auth/register` | `{email, password(8+, letters+digits), full_name, phone?, role_request: farmer\|expert}` | `{status:"signed_in", access_token, refresh_token, user}` or `{status:"confirm_email"}` |
| `POST /auth/login` | `{email, password}` | `{access_token, refresh_token, expires_in, user}` |
| `POST /auth/refresh` | `{refresh_token}` | new session |
| `POST /auth/logout` | (Bearer) | `{ok:true}` |
| `GET /auth/me` | (Bearer) | `{id, email, role, full_name}` |
| `GET /admin/users` | admin | users with `role` and `role_request` |
| `POST /admin/users/{id}/role` | admin, `{role}` | sets `app_metadata.role` |
Everyone registers as **farmer**. `role_request: expert` is only a note; an admin approves it in the Expert/Admin page. First admin (SQL editor, once):
```sql
update auth.users set raw_app_meta_data = coalesce(raw_app_meta_data,'{}'::jsonb) || '{"role":"admin"}' where email = 'you@example.com';
```
The UI (`/`) shows a login/register dialog, keeps the token in `localStorage` (`gt_token`, `gt_refresh`), refreshes it on 401 and shows the Expert/Admin page only to those roles. With `AUTH_REQUIRED=false` it shows a dev-user picker instead.

## 3. Section 1: Advisor API

### `GET /health` · `GET /meta/crops`
`/meta/crops` → `[{id, name_bn, name_en, seasons:[{id,name_bn}]}]` (crop ids: `boro aman aus wheat maize potato tomato mustard lentil jute`).

### `POST /advisor/analyze`  (any signed-in user)
Body (all optional but at least one of prompt/answers/sensors/session_id):
```json
{ "session_id": "string<=64", "prompt": "string<=1500",
  "answers": {"slot": "value"}, "sensors": {"ph": 6.1} }
```
Flow:
1. First call: `{"prompt": "আমার ৩০ শতাংশ জমি আছে, গত ৪ বছর ধান চাষ করেছি, এখন ভুট্টা চাষ করতে চাই।"}`
   → `{"session_id","status":"need_info","round":1,"questions":[{"slot","text_bn","options":[...]}]}` (max 3 questions/round, max 2 rounds)
2. Answer: `{"session_id":"…","answers":{"irrigation":"good","soil_type":"unknown"}}` (`"unknown"` = জানি না → default assumed, confidence lowered)
3. Done: `{"session_id","status":"done","round":n,"report":{summary{headline_bn,confidence}, inputs, comparison, ranking, evidence, narrative…}}`

Slots: `target_crop, land_decimal, last_crop, season, irrigation, soil_type, ph, years_same, location`.
Enums: `season` = `rabi|kharif1|kharif2`; `soil_type` = `doash|entel|beley`; `irrigation` = `good|partial|none`.

```bash
curl -s localhost:8000/advisor/analyze -H 'Content-Type: application/json' -H 'X-Dev-User: farmer1' \
  -d '{"prompt":"আমার ৩০ শতাংশ জমি আছে, গত ৪ বছর ধান চাষ করেছি, এখন ভুট্টা চাষ করতে চাই।"}'
```

### `GET /advisor/report/{sid}`
→ `{session_id, report, review_status: none|pending|reviewed, review_note}`. 404 if no report yet.

### `POST /advisor/report/{sid}/request-review`
→ `{session_id, review_status:"pending"}` (puts it in the expert queue).

### Expert (role `expert` or `admin`)
- `GET /expert/queue` → `[{session_id, headline_bn, confidence, inputs}]`
- `POST /expert/review/{sid}` body `{"verdict":"agree|adjust|disagree","note":"<=2000 chars"}` → `{session_id, review_status:"reviewed"}`

---

## 4. Section 2: Plot Twin API (`/twin`)

Concepts: a **plot** = one field part with one crop, its own soil, random seed (replayable weather), config and full history.
Time only moves when you call `advance` (simulation). Status: `growing → ready → harvested | dead`.

### Enumerations
| Name | Values |
|---|---|
| `soil_type` | `doash` (দোআঁশ), `entel` (এঁটেল), `beley` (বেলে) |
| `crop_id` | `boro aman aus wheat maize potato tomato mustard lentil jute` (see `GET /twin/meta`) |
| action `type` | `irrigate`, `pump`, `fertilize`, `lime`, `spray`, `harvest` |
| photo status | `no_model`, `unknown`, `ok` |
| review verdict | `disease`, `healthy`, `unsure` |
| `nutrient` | `N` (ইউরিয়া), `P` (টিএসপি), `K` (এমওপি) |
| alert `level` | `info`, `warn`, `action`, `critical` (`action`/`critical` stop `advance` when `stop_on_alert=true`) |
| event `kind` | `alert`, `action` (you), `auto_action` (system), `question`, `answer`, `status`, `photo`, `review`, `sms` |
| question ids | `germination leaf_color wilting leaf_spots pests standing_water` |

### `GET /twin/meta`  (public)
→ `{crops:[{id,name_bn,duration_days,stages:[name_bn…]}], soils:[{id,name_bn}]}`

### `POST /twin/plots`  — create a plot
```json
{ "crop_id": "boro", "name": "পূর্বের জমি", "area_decimal": 30, "soil_type": "doash",
  "ph": 6.3, "ec": 1.0, "start_date": "2026-11-20", "seed": 3,
  "auto_irrigation": true, "auto_inputs": false }
```
Required: `crop_id`, `area_decimal` (>0, ≤5000). Optional: `name`, `soil_type` (default doash), `ph` (3.5–9.5, default 6.3),
`ec` dS/m (0–20, default 1.0; set 3+ to simulate coastal salinity), `start_date` (default today), `seed` (same seed = same weather),
`auto_irrigation` (default true), `auto_inputs` (auto fertilizer/lime/spray, default false),
`sms_enabled` + `phone` (BD mobile `01XXXXXXXXX`; urgent alerts are also sent by SMS). Max 20 plots per user.
→ plot snapshot (see below). `warnings` lists wrong-season / wrong-soil / pH-out-of-range notes.

### `GET /twin/plots`  — my plots
→ `[{id,name,crop:{id,name_bn},day,duration,status,health,date}]`

### `GET /twin/plots/{id}`  — full snapshot
Abbreviated shape:
```json
{ "id":"…","name":"…","crop":{"id":"boro","name_bn":"বোরো ধান"},"soil":"doash","area":30,
  "day":42,"date":"2027-01-01","duration":140,"status":"growing","end_reason":null,"result":null,
  "stage":{"id":"tiller","name_bn":"কুশি","idx":2},
  "stages":[{"id":"germ","name_bn":"…","start_day":0,"end_day":14}, …],
  "health":98,"pump_on":false,
  "pump":{"on":false,"manual":false,"days_running":0,"max_days":7},   // manual (remote) pump max_days = 2
  "config":{"auto_irrigation":true,"auto_inputs":false,"sms_enabled":false,"phone_set":false,"phone_masked":""},"warnings":[],
  "soil_now":{"aw":118,"ph":6.28,"ec":1.1,"N":41,"P":50,"K":52,"disease_risk":12},
  "thresholds":{"irrigate_below":110,"emergency_below":67,"stop_at":130,"ph_min":5.5,"ph_max":7.5,"ec_tol":3.0,"low_level":38,"light_need_h":6},
  "weather":{"date","tmax","tmin","tmean","rain_mm","rh","et0","storm","daylight_h","sun_h"},
  "forecast":[{"date","lead_days","rain_mm","prob","tmax","normal_mm","vs_normal":"more|less|normal"} ×5],
  "factors":{"water","nutrient","ph","temp","salt","disease","light"},   // 1.0 = no stress
  "totals":{"water_l","irrig_mm","urea_kg","tsp_kg","mop_kg","lime_kg","rain_mm","sprays"},
  "estimate":{"yield_kg","revenue","cost","profit","yield_factor"},
  "pending_actions":[{"type","nutrient?","key","title_bn","day"}],
  "alerts":[{"key","level","title_bn","text_bn","action","why":{"rule_bn","facts":[{"label_bn","value"}]},"day"}],  // newest first
  "photo_reviews":[{"id","day","label","score","status":"pending"}],
  "questions":[{"id","text_bn","day_asked","options":[{"value","label_bn"}]}] }
```
`soil_now.aw` = plant-available water % (100 = field capacity; >100 = saturated/ponded, normal for rice).

### `POST /twin/plots/{id}/advance`  — move time forward
```json
{ "days": 7, "stop_on_alert": true, "auto_harvest": false }
```
`days` 1–400. With `stop_on_alert=true` it stops at the first new `action`/`critical` alert (so you can decide).
`days:400, stop_on_alert:false, auto_harvest:true` = "run to the end" (auto-harvests when ripe).
→ `{plot, days_run, stopped_for, events:[…], logs:[daily records…]}`.
Each log record: `{day,date,stage,stage_bn,status,wx,aw,w_mm,ph,ec,N,P,K,dis,pump_on,irrigation_mm,health,factors,est_yield_kg}`.

### `POST /twin/plots/{id}/action`  — manual control (remote irrigation etc.)
| Body | Effect |
|---|---|
| `{"type":"pump","on":true}` / `{"type":"pump","on":false}` | Pump ON/OFF. ON delivers water each simulated day until the target level, then turns itself off |
| `{"type":"irrigate","mm":20}` | One-off irrigation (0–60 mm; omit `mm` = enough to reach target, max 25) |
| `{"type":"fertilize","nutrient":"N"}` | Apply urea/TSP/MoP dose |
| `{"type":"lime"}` or `{"type":"lime","kg_per_decimal":3}` | Lime (default = computed dose to bring pH into range) |
| `{"type":"spray"}` | Fungicide/pest spray (7 days protection) |
| `{"type":"harvest"}` | Only when `status="ready"`, else 400 |
→ `{plot, event}`. Not allowed after the plot has ended (400).

### `POST /twin/plots/{id}/answers`  — answer the twin's questions
```json
{ "answers": { "leaf_color": "lower_yellow" } }
```
Valid values come from the question's `options[].value` (`questions` in the snapshot). Answers correct the hidden state
(e.g. yellow lower leaves → nitrogen estimate lowered). → `{plot, notes:[Bengali explanation…]}`

### GrowthTwin Sentinel sensor ingestion (prototype)

1. Set `SENSOR_INGEST_TOKEN` to a long random secret in the backend environment. Restart the backend after changing it. Never place a Supabase service-role key on the ESP32.
2. As an authenticated farmer, register the node and calibration on the target plot:

```http
POST /twin/plots/{plot_id}/sensor-calibration
Content-Type: application/json

{"device_id":"esp32-plot-1","adc_at_wilting_point":3000,"adc_at_field_capacity":1500,"adc_min":0,"adc_max":4095}
```

The ADC values above are illustrative only. Measure them for the actual probe and soil; do not copy them as real calibration values. The backend supports probes whose ADC reading increases or decreases as the soil gets wetter. The response includes a randomly generated `device_token`; copy it securely to that ESP32 now because it is not recoverable from the backend later. Only its SHA-256 digest is stored. Re-provisioning rotates the token.

3. Send device readings to `POST /twin/device/readings` with `X-Sensor-Token: <device_token>` and a JSON body like:

```json
{"plot_id":"YOUR_PLOT_ID","device_id":"esp32-plot-1","sequence":1,"timestamp":"2026-10-13T12:00:00Z","raw_moisture_adc":2250}
```

The backend checks the per-device token, registered device, timestamp (timezone required, no older than 24 hours or over 5 minutes in the future), calibration, and strictly increasing sequence number. The shared `SENSOR_INGEST_TOKEN` remains a server-side feature-enable secret; new device registrations authenticate with their own token. Legacy registrations without a stored device-token digest can temporarily use the shared token and should be re-provisioned.

Server-side health checks flag readings as `suspect` when they fall outside the calibrated span, show an implausible ADC jump (>1500 counts), or repeat the same ADC value for five consecutive readings. Suspect readings are retained for audit but do not correct the twin state. Health reasons are included in the reading response and plot-state audit record. Thresholds are conservative prototype defaults, not validated sensor diagnostics.

A starter sketch is in `../hardware/esp32_moisture_node/esp32_moisture_node.ino`. Configure Wi-Fi, plot ID, device token, API URL, and the API host's real TLS root CA before uploading. It uses NTP time and persistent sequence numbers. It does not yet queue readings during outages; implement a durable offline queue before field deployment.

**Calibration limitation:** the two-point linear mapping is a prototype approximation. A real field trial should validate it against reference soil-moisture measurements, document sensor placement/soil texture, and tune the Reality Gap blend coefficient on calibration data separate from evaluation data. The global token is suitable only for a controlled prototype; production needs per-device credentials and revocation.

### `POST /twin/plots/{id}/readings`  — real sensor values (pH strip, EC, soil moisture / ESP32)
`{"ph":5.8,"ec":1.2,"moisture_pct":72}` (all optional, at least one) replaces the simulated value → `{plot, event}`. `moisture_pct` is plant-available water % (100 = field capacity).

### `POST /twin/plots/{id}/photo`  — leaf photo → per-crop disease model (advisory only)
```json
{ "image_b64": "<base64 JPEG/PNG/WebP, <= 2 MB, shrink to ~512 px on the phone first>" }
```
→ `{prediction, plot, notes}` where `prediction` is `{"status":"no_model"}` | `{"status":"unknown","score"}` | `{"status":"ok","label","label_bn","score","healthy","needs_review"}`.
The image is **not stored**. A disease label only raises a warning, opens the leaf-spots question and (if `needs_review`, or `unknown`) queues an expert review.
It never changes disease risk, the pump or any dose. Crops without a model return `no_model` and keep the rule-based risk + questions.

### `GET /twin/plots/{id}/why/{key}`  — the "Why?" button
`key` = an alert key (`emergency`, `irrigate`, `fert_N`, `lime`, `spray`, `storm`, `heat_soon`, `photo_disease`, `pump_failsafe`…) or an automatic action key
(`pump_on`, `pump_off`, `pump_failsafe`, `auto_fert_N`, `auto_lime`, `auto_spray`).
→ `{key, title_bn, day, rule_bn, facts:[{label_bn,value}]}` (404 if none yet). Rule-based text, no LLM.

### `POST /twin/plots/{id}/config`
`{"auto_irrigation": true, "auto_inputs": false, "sms_enabled": true, "phone": "01712345678"}` (all optional) → snapshot.

### Harvest history (feeds Section 1)
- `GET /twin/harvests` → my finished plots `[{crop_id, area, yield_kg, yield_kg_per_decimal, revenue, cost, profit, days, health, start_date}]`
- `GET /twin/harvests/stats` → `[{crop_id, harvests, avg_yield_kg_per_decimal, best, worst}]` (my real yields; Section 1 can compare with the CSV yield range)
A record is written once when a plot is harvested or dies (`outcome`); Section 1 uses harvested ones only.

### Expert review of uncertain photos (role `expert` / `admin`)
- `GET /twin/expert/reviews` → `[{plot_id, review_id, crop, day, label, score, reason: "unknown"|"low_confidence"}]`
- `POST /twin/expert/reviews/{plot_id}/{review_id}` body `{"verdict":"disease|healthy|unsure","label":"","note":""}`
  `disease` marks the problem as confirmed (the normal spray recommendation can then fire); `healthy` lowers the disease risk.

### `GET /twin/plots/{id}/logs?since_day=0`  → daily records (for charts)
### `GET /twin/plots/{id}/events`  → latest 100 alerts/actions/answers/status events (newest first)
### `GET /twin/plots/{id}/summary`  → `{text, source:"template"|"llm"}` Bengali status summary
### `DELETE /twin/plots/{id}`  → `{ok:true}` (also deletes logs/events)

```bash
H='-H Content-Type:application/json -H X-Dev-User:farmer1'
# 1. create
curl -s localhost:8000/twin/plots $H -d '{"crop_id":"boro","area_decimal":30,"soil_type":"doash","seed":3,"start_date":"2026-11-20"}'
# 2. run 30 days (stops early on urgent alerts)
curl -s localhost:8000/twin/plots/PLOT_ID/advance $H -d '{"days":30}'
# 3. remote pump ON
curl -s localhost:8000/twin/plots/PLOT_ID/action $H -d '{"type":"pump","on":true}'
# 4. apply the suggested urea
curl -s localhost:8000/twin/plots/PLOT_ID/action $H -d '{"type":"fertilize","nutrient":"N"}'
# 5. answer a question
curl -s localhost:8000/twin/plots/PLOT_ID/answers $H -d '{"answers":{"wilting":"noon"}}'
# 6. run to the end
curl -s localhost:8000/twin/plots/PLOT_ID/advance $H -d '{"days":400,"stop_on_alert":false,"auto_harvest":true}'
```

### How the twin decides (no trained model, no LLM in the control loop)
- **Irrigation**: ON when soil water < `irrigate_below` (skipped if ≥10 mm rain is likely in 2 days); **emergency ON** below `emergency_below`
  even if rain is forecast; OFF at `stop_at` (hysteresis). Paused if a storm (≥60 mm) is forecast. Last stage (ripening) is never irrigated.
- **Fertilizer**: dose recommended when N/P/K < 38 (not before rain ≥15 mm is expected). **Lime**: when pH < crop minimum − 0.15.
- **Disease risk**: rises on warm (20–32 °C), humid (≥85 %) days; spray recommended at ≥60.
- **Health** falls when combined stress < 0.9; 0 = dead (cause reported: drought, waterlogging, nutrients, pH, heat/cold, salt, disease).
- **Light**: daylight and sun hours come from the (simulated) weather; fewer sun hours than the crop needs slows growth a little; 4 cloudy days in a row raises an info alert.
- **Pump safety**: a remotely started pump stops by itself at the target level or after 2 days; auto mode after 7 days (alert raised). A storm forecast pauses a non-emergency pump.
- **Questions**: at most 3 unanswered at a time (priority: leaf spots, wilting, standing water, germination, leaf colour, pests).
- **SMS**: when `sms_enabled` + a valid phone, `critical`/`action` alerts are also sent (max 3 per call). With `SMS_PROVIDER=none` they are only logged as `sms` events (status `simulated`); the system cannot detect "farmer is offline" by itself.
- **Forecast**: simulated 5-day rain and max temperature with growing error; `vs_normal` compares with the monthly normal for that day.
- Weather is deterministic per `(seed, date)`: replayable. Real sensors / Open-Meteo replace `weather_sim.py` and the soil values in `twin_engine.step()` later.

---

## 4b. Section 4: Farmers' Trust (`/trust`)
`GET /trust/crop/{crop_id}` (signed-in) shows what happened when OTHER farmers grew the same crop: `n_farmers`, `growing_now`, and (only when `n_farmers >= TRUST_MIN_FARMERS`, default 5) `profit_share`, `failed`, median/p25/p75/best/worst profit per decimal, median yield, a profit histogram, plus `mine` (your own finished plots with `better_than` = share of other farmers you beat).
- Anonymous: no names or user ids; below the minimum only counts are returned.
- Honest: failed (dead) plots are recorded and counted; every record has `source` (`simulation` today). The UI labels it as simulation. Do not present simulation results as real field outcomes.
- **Re-run `supabase/schema.sql`** (adds `outcome`, `source` to `harvest_records`). Until then harvest records are skipped with a log line instead of breaking the farmer's action.
- For a demo with few users set `TRUST_MIN_FARMERS=1` (the UI still labels the data as simulation).

## 5. Database (Supabase) — `supabase/schema.sql`
Section 1: `advisor_sessions`, `report_cache`, `rag_chunks` (+ `match_rag_chunks()`).
Section 2: `twin_plots` (state jsonb, `needs_review` flag), `twin_logs` (one row/day, PK `plot_id,day`), `twin_events` (alerts/actions/answers/photos/reviews/sms), `harvest_records` (one row per harvested plot).
**Existing database?** Re-run `supabase/schema.sql`: everything is `if not exists`, and it adds the `needs_review` column and `harvest_records` table.
RLS is enabled with no policies: only the backend (service-role key) can read/write; the public anon key can do nothing.

## 6. Code map
```
app/main.py                 routers + static UIs
app/api/{advisor,expert,meta,twin}.py
app/core/{auth,config,db,store,twin_store}.py
app/services/               Section 1: extractor, slot_manager, rules, economics, decision, compare, rag, llm, validator, report, pipeline…
                            Section 2: crop_stages, weather_sim, twin_engine, twin_questions, twin_summary, disease_models, notify
app/models/<crop>/          optional per-crop disease model (model.onnx + labels.json), see app/models/README.md
app/csv_data/*.csv          SAMPLE crop data (verify!)
app/static/{index,twin}.html  the two dashboards
tests/{test_flow,test_twin}.py
```

## 7. Data you MUST verify before trusting any output
- `app/csv_data/*.csv` (Section 1) hold SAMPLE values: crop requirements, yields, prices, costs, rotation rules. Replace with BARI/BRRI/DAE/BBS/DAM numbers and have an agriculture expert check them. Bump `DATA_VERSION` in `services/pipeline.py` after editing.
- `services/crop_stages.py` and `services/weather_sim.py` (Section 2): stage lengths, water thresholds, fertilizer/lime doses, temperature ranges, monthly climate are all SAMPLE-VERIFY.

## 8. Status of the combined workflow (Section 2)
| Block | Status |
|---|---|
| Day 0 setup, daily loop, plain-code decision core (water, N-P-K, lime, light, heat, salt, disease risk) | Built |
| Sensors | Simulated by default; typed or ESP32 values via `POST /twin/plots/{id}/readings`. No device token / auto-push yet |
| Forecast (rain + max temp), questions (max 3 open), "Why?" | Built |
| Photo → per-crop disease model, registry, "unknown" fallback, expert review | Built as an optional, advisory-only framework. **No model ships**: every crop returns `no_model` until you add one (`app/models/README.md`). The ONNX loader is untested |
| Alerts + SMS | App alerts built. SMS via webhook or simulated; no gateway adapter included |
| Farmer acts, logs it; remote pump with max run-time | Built |
| Harvest record | Built. Section 1 now attaches the farmer's own yields (`report.own_yields`) |
| Bangla briefing | Template + optional Grok with number check; browser voice button (`bn-BD`, depends on the phone). No memory cache |
| Expert review UI | Built in the Expert/Admin page of `/` |

## 9. Known limits
- Section 2 API endpoints were not run against a live FastAPI server in the build environment (no network to install it). Engine logic and the dashboard render are tested; run `pytest -q` locally, which also covers the API tests.
- All simulation coefficients are SAMPLE-VERIFY. Real hardware additionally needs a device-command queue (desired pump state in Supabase, device polls/MQTT and confirms) and a local fail-safe on the device.

## GrowthTwin Sentinel sensor monitoring

The ESP32 prototype posts timestamped raw ADC values to `POST /twin/device/readings` using the per-device `X-Sensor-Token` header. Configure `SENSOR_INGEST_TOKEN` on the backend as the ingestion feature-enable secret, then register the device and **measured** wilting-point/field-capacity ADC endpoints at `POST /twin/plots/{plot_id}/sensor-calibration`. Save the one-time returned `device_token` to that node. Re-provision to rotate a lost token. Server-side checks flag out-of-span readings, large ADC jumps, and five-reading flatlines as suspect; these readings are audited but not blended into the twin state.

Apply the `sensor_readings` section at the end of `supabase/schema.sql` in the Supabase SQL editor before enabling ingestion against Supabase. It creates normalized, indexed telemetry history with a unique `(plot_id, device_id, sequence)` key. The in-memory development store keeps readings only for the lifetime of the process.

The live monitoring page is available at `/sentinel.html` after opening the main GrowthTwin app and signing in. Its API data comes from `GET /twin/plots/{plot_id}/sensor-readings` and `GET /twin/plots/{plot_id}/reality-gap`.

For an independent evaluation, create a CSV with `reference_moisture_pct`, `predicted_moisture_pct`, and `corrected_moisture_pct` columns, where each row aligns to the same reference observation. Run:

```bash
python scripts/evaluate_reality_gap.py path/to/held_out_readings.csv
```

Keep the evaluation set separate from the data used to choose the correction coefficient or sensor calibration. The script reports MAE, RMSE, and bias; it does not assume the corrected model is better.

## Sentinel evaluation against reference measurements (Milestone 6)

Do not assess sensor accuracy from the same readings used to calibrate the probe. Collect paired measurements from a documented independent reference method (for example, a validated gravimetric soil-moisture procedure), record timestamps and device/plot IDs, and retain suspect observations rather than silently deleting them. Start from `data/reference_measurements_template.csv`.

Required CSV columns:

- `reference_moisture_pct`: independent reference value, in the same explicitly defined moisture scale as the calibrated sensor value.
- `calibrated_moisture_pct`: sensor-derived value.

Optional grouping columns are `plot_id`, `device_id`, `quality`, and `timestamp`. Run from the backend directory:

```bash
python scripts/evaluate_sensor_accuracy.py data/paired_reference_measurements.csv --tolerance 5 --out evaluation_report.json
```

The report includes sample count, MAE, RMSE, signed bias, median absolute error, and the share of paired measurements within the selected absolute-error tolerance, both overall and by quality/device. Missing or non-finite numeric pairs are excluded and counted. The tolerance is in percentage points, not percent relative error. Evaluate on held-out plots/devices and report sample sizes and collection conditions; these metrics alone do not prove crop-yield improvements or water savings.

## Field-trial evidence report (Milestone 7)

Generate a self-contained HTML report from paired sensor/reference readings:

```bash
python scripts/build_field_trial_report.py data/paired_reference_measurements.csv \
  --name "North plot trial" --tolerance 5 \
  --notes "Record reference method, probe depth, soil type, and sampling conditions" \
  --out field_trial_report.html
```

The report includes overall and quality-group sensor-agreement metrics, valid/excluded pair counts, blank-field coverage, and distinct plot/device/calibration metadata counts. It does not invent results or claim yield gains/water savings. Use independent reference measurements and held-out plots/devices. The required columns are `reference_moisture_pct` and `calibrated_moisture_pct`; optional metadata fields are listed in the script.


## WhatsApp & SMS (Section 1 advice, Section 2 photo + alerts)

| Channel | What the farmer gets |
|---|---|
| WhatsApp | Crop advice (questions one at a time, answer with a number) · leaf photo → disease hint for the plot · urgent plot alerts (`critical`/`action`, max 3 per call) |
| SMS | Crop advice only, short text (≤ `SMS_MAX_CHARS`, Bangla SMS = 67 chars per part). No photos, no alerts from this module |

**Endpoints** (`app/api/messaging.py`): `POST /messaging/link-code`, `GET /messaging/status`, `DELETE /messaging/link` (logged-in farmer);
`GET|POST /messaging/whatsapp/webhook` (Meta); `POST /messaging/sms/inbound` (any gateway, header `X-Channel-Secret`, body `{"from","text","id"}`).

**Linking a phone to an account** (needed for photos and alerts): logged-in user calls `POST /messaging/link-code` → sends `LINK 123456` on WhatsApp within 10 minutes. WhatsApp proves the sender's number, so nobody can claim another person's number. Without linking, the advisor still works (anonymous session per phone).

**Commands** (WhatsApp/SMS): any text = new question · `১/২/৩…` = answer · `শুরু` = restart · `সাহায্য` = menu · `বন্ধ`/`চালু` = alerts off/on.

**WhatsApp setup (Meta Cloud API):** create a Meta app with WhatsApp → set `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET` (`.env.example`) → webhook URL `https://<your-https-host>/messaging/whatsapp/webhook`, subscribe to `messages`. Locally use a tunnel (e.g. ngrok). In `APP_ENV=prod` an unsigned webhook is refused.
Alerts are business-initiated messages: plain text works only within 24 h after the farmer last wrote; later ones need an approved template (`WHATSAPP_ALERT_TEMPLATE`, one body variable), otherwise the event status is `needs_template`.
With no WhatsApp settings everything is **simulated** (events/logs only), like `SMS_PROVIDER=none`.

**SMS:** outgoing uses the existing `SMS_PROVIDER=webhook` adapter; incoming: point your gateway's "incoming SMS" callback to `/messaging/sms/inbound`. Set `CHANNEL_SECRET`.

Tables: `channel_links`, `channel_link_codes` (re-run `supabase/schema.sql`). Event kind `whatsapp` is stored next to `sms`.
Known limits: two messages from one phone at the same instant can overwrite each other's chat state (last write wins); the per-phone rate limit (`CHANNEL_MSGS_PER_HOUR`) is per server process.
