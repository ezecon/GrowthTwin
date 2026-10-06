# GrowthTwin — Project Documentation
## Section 1: Daily Care & Monitoring | Section 2: Pre-Planting Profit & Risk Advisor | Section 3: SMS/WhatsApp/IVR Fallback

---

# 📗 Section 1: Daily Care & Monitoring

## ১.১ এই সেকশনের উদ্দেশ্য (Purpose)

গাছ লাগানোর দিন থেকে শুরু করে প্রতিদিনের পরিচর্যা পর্যন্ত পুরো প্রক্রিয়াটা sensor + CV দিয়ে monitor করা, এবং farmer-কে প্রতিদিন app-এর মাধ্যমে সহজ ভাষায় (Bangla) actionable update দেওয়া — কখন পানি দিতে হবে, কখন সার দিতে হবে, গাছের পাতা/অবস্থা কেমন, এবং কী করলে ভালো হয়।

এটা মূল **GrowthTwin** সিস্টেমের একটি সাব-মডিউল — GrowthTwin গাছের বড় হওয়ার stage (growth stage) track করে, আর এই "Daily Care" module প্রতিদিনের micro-level care (পানি, সার, রোদ, রোগ-ঝুঁকি) handle করে।

---

## ১.২ Hardware / Sensor List

| Sensor | কাজ | আনুমানিক Cost | Note |
|---|---|---|---|
| Capacitive Soil Moisture Sensor | মাটির আর্দ্রতা মাপা → পানি দেওয়ার সিদ্ধান্ত | $2–3 | সবচেয়ে সহজ ও reliable, প্রতি zone-এ একটা |
| LDR / LUX Light Sensor | গাছ কতটা রোদ পাচ্ছে | $1–2 | কম রোদের কারণে দুর্বলতা আলাদা করে চিহ্নিত করতে সাহায্য করে |
| DHT22 (Temp/Humidity) | তাপমাত্রা ও আর্দ্রতা → pest/fungal risk অনুমান | $1–3 | আগে থেকেই মূল hardware list-এ আছে |
| ESP32 (Microcontroller) | সব sensor থেকে data collect ও পাঠানো | $3–6 | প্রতি zone-এ একটা |

**pH Measurement — Hardware-free (সবচেয়ে সস্তা বিকল্প):** dedicated pH sensor hardware ($25-40 combo, এমনকি standalone probe-ও $50-90) সম্পূর্ণ বাদ দেওয়া হয়েছে। বদলে **CV-based pH Strip Reading**: বাজারের সস্তা pH test strip (৫০+ strip বক্স ~২০০-৪০০ টাকা) ব্যবহার করে, phone camera দিয়ে ছবি তুলে color-calibration chart অনুযায়ী CV দিয়ে রং থেকে pH value বের করা হবে।

**Design সিদ্ধান্ত (Important):** Sensor বসবে **zone-based** (জমির ছোট অংশ ধরে), per-plant না — কারণ কাছাকাছি মাটির condition প্রায় একই থাকে, আর per-plant sensor বসানো অবাস্তব ও ব্যয়বহুল।

---

## ১.৩ Computer Vision-এর ভূমিকা

এই "Daily Care" section sensor-heavy দেখতে হলেও, **CV হচ্ছে প্রধান ইঞ্জিন আর sensor হলো সাপোর্টিং layer**। CV চার জায়গায় কাজ করছে:

| CV কাজ | কোথায় ব্যবহার | Model/Approach |
|---|---|---|
| **Leaf Disease/Deficiency Detection** | Leaf Condition Check | ProtoFusion (CNN-ViT hybrid + prototype XAI) — আগে থেকেই তৈরি, ৯৮%+ accuracy |
| **Growth Stage Classification** | Growth Photo Timeline | GrowthTwin-এর মূল CV task — চারা→বাড়ন্ত→ফুল→ফল→পরিপক্ব, height/leaf-count estimation সহ |
| **Root Condition (Indirect)** | Root Estimation | সরাসরি CV না — wilting pattern + moisture + leaf trend মিলিয়ে অনুমান (nursery/potted হলে সরাসরি ছবি সম্ভব) |
| **pH Strip Color Reading** | Fertilizer Advisory | Test strip-এর ছবি তুলে color-calibration chart দিয়ে pH value বের করা — dedicated pH hardware-এর সস্তা বিকল্প |

**কেন sensor + CV দুটোই দরকার:** sensor দেয় মাটির ভেতরের (invisible) অবস্থা — moisture, pH। CV দেয় গাছের বাইরের (visible) অবস্থা — পাতার রং, দাগ, growth। দুটো data একসাথে মিলিয়েই Daily Advisory Agent সঠিক সিদ্ধান্ত নেয়।

আগের আলোচনায় হওয়া সব agentic CV feature (diagnostic interview, active-capture, counterfactual explanation, ensemble self-doubt, text-vision consistency) **Leaf Condition Check** অংশেই plug হবে — এটাই পুরো system-এর CV core।

---

## ১.৪ Feature List (সম্পূর্ণ তালিকা)

### A. Core Sensing & Advisory
1. **Soil Moisture-based Watering Advisory** — সেন্সর reading থেকে "আজ পানি দরকার / দরকার নেই" বলা।
2. **pH-based Fertilizer Advisory** — pH test strip-এর ছবি (CV দিয়ে রং পড়া) + leaf-CV nutrient-deficiency signal মিলিয়ে কখন সার দিতে হবে তা বলা।
3. **Fertilizer Dosage Calculator** — pH (strip reading) + leaf-CV deficiency severity + growth stage মিলিয়ে **কত পরিমাণ** সার লাগবে তা বলা।
4. **Light/Sunlight Tracking** — পর্যাপ্ত রোদ পাচ্ছে কিনা, দুর্বলতার কারণ আলাদা করা।

### B. Visual/CV-based
5. **Leaf Condition Check** — ছবি তুলে দিলে disease/nutrient-deficiency CV দিয়ে check।
6. **Root Condition (Indirect Estimation)** — wilting pattern + soil moisture + leaf trend মিলিয়ে root-সমস্যা অনুমান।
7. **Growth Photo Timeline (Visual Diary)** — প্রতি সপ্তাহে ছবি পাশাপাশি রেখে growth তুলনা।

### C. Predictive/Proactive
8. **Weather-aware Predictive Stress Alert** — আজকের sensor data + ২-৩ দিনের forecast মিলিয়ে আগে থেকে পরামর্শ।
9. **Preventive Pest/Fungal Risk Alert** — Temperature + humidity combination থেকে pest/fungal risk আগে থেকে জানানো।

### D. Farmer-facing UI/UX
10. **Daily Bangla Status Update** — প্রতিদিন app-এ "আজকের অবস্থা" card।
11. **Voice-based Daily Briefing** — Bangla voice-এ শোনার option (accessibility)।
12. **"কেন?" (Explain Why) Button** — প্রতিটা recommendation-এর কারণ সহজ ভাষায় দেখানো।
13. **Multi-Plant/Plot Dashboard** — color-coded (সবুজ/হলুদ/লাল) overview।

### E. Tracking & Comparison
14. **Water Usage Tracker + Savings Calculator** — পানি সাশ্রয় দেখানো।
15. **Seasonal Comparison/History** — এই বছরের growth এর সাথে আগের season-এর তুলনা।

---

## ১.৫ Data Flow

```
[Soil Moisture + Light + Temp/Humidity Sensors] + [pH Strip Photo]
              │
              ▼
   ESP32 (sensor data) + Phone Camera (pH strip + leaf photo)
              │
              ▼
   Phone App / Local Hub (LoRa বা WiFi এর মাধ্যমে)
              │
              ▼
   Daily Advisory Agent
   ├── পানি দরকার কিনা? (moisture + weather forecast)
   ├── সার দরকার কিনা, কতটুকু? (pH strip CV reading + leaf-CV deficiency signal + growth stage)
   ├── Pest/fungal risk আছে কিনা? (temp + humidity pattern)
   └── আলো পর্যাপ্ত কিনা?
              │
              ▼
   [+ Farmer-submitted Leaf Photo] → CV Disease/Deficiency Check
              │
              ▼
   Daily Bangla Update (Text + Voice) + "কেন?" Explanation
              │
              ▼
   App UI: Status Card + Growth Timeline + Multi-plot Dashboard
```

---

## ১.৬ GrowthTwin-এর সাথে সম্পর্ক

- **GrowthTwin** = গাছের বড় হওয়ার macro-stage track করে, দীর্ঘমেয়াদী planning (harvest timing, labor booking) করে।
- **Daily Care & Monitoring** = প্রতিদিনের micro-level care handle করে।
- দুটো module একসাথে কাজ করে: Daily Care থেকে পাওয়া growth-abnormality data GrowthTwin-এর **Anomaly Agent**-কে trigger করতে পারে, যা Disease Detection module (ProtoFusion-based) চালু করে।

---

## ১.৭ ৪০ দিনে কী Build করা Realistic

**অবশ্যই বানানো (Core, fully working):**
- Soil moisture sensor + watering advisory
- pH strip CV reading + leaf-CV deficiency signal → fertilizer advisory + dosage calculator
- Daily Bangla status update (text)
- Leaf photo CV check (ProtoFusion pipeline ব্যবহার করে)
- "কেন?" explanation button

**হালকা Proof-of-Concept হিসেবে যথেষ্ট:**
- Weather-aware predictive alert (simple rule-based)
- Voice briefing (basic TTS)
- Seasonal comparison (mock/demo data)
- Multi-plot dashboard (২-৩টা demo plot)

---

## ১.৮ Notes

- Root imaging সরাসরি field crop-এ practically কঠিন — indirect estimation ব্যবহার করা হবে।
- Sensor বসবে **per-zone**, per-plant না।
- NPK+pH sensor hardware খরচের কারণে বাদ, বদলে CV-based pH strip reading।
- নতুন feature গুলো (water tracker, seasonal comparison, voice briefing) existing sensor/CV data থেকেই generate হয়, নতুন hardware লাগে না।

---
---

# 📘 Section 2: Pre-Planting Profit & Risk Advisor

## ২.১ এই সেকশনের উদ্দেশ্য (Purpose)

কৃষক গাছ লাগানোর **আগেই** জানতে পারবে — এই মৌসুমে এই ফসল চাষ করলে সম্ভাব্য লাভ কত হতে পারে, কী কী ঝুঁকি আছে, এবং সেই ঝুঁকি কমানোর জন্য কী করা উচিত। এটা GrowthTwin-এর প্রথম ধাপ — গাছ লাগানোর আগের সিদ্ধান্ত-সহায়ক মডিউল (আগে থেকেই আলোচনা হওয়া "Pre-Planting Soil & History Advisory" ধারণার concrete, buildable version)।

---

## ২.২ Input (কৃষক কী দিবে)

- ফসলের নাম (যেমন: ধান, গম, সবজি)
- প্লট/এলাকার তথ্য (জেলা/উপজেলা, মাটির ধরন — যদি Section 1 থেকে ইতিমধ্যে soil data থাকে সেটাও ব্যবহার করা যাবে)
- চাষের মৌসুম/সময়কাল

---

## ২.৩ পাইপলাইন (Architecture)

```
Farmer Input (crop, plot location/soil, season)
              │
              ▼
   Feature Engineering
   ├── ঐতিহাসিক yield data (ওই ফসল, ওই এলাকা/মাটি)
   ├── ঐতিহাসিক বাজার দাম trend (ওই ফসলের)
   ├── আবহাওয়া/মৌসুম উপযুক্ততা
   ├── ইনপুট খরচ (বীজ, সার, শ্রম — আনুমানিক)
   └── প্লটের soil condition (Section 1-এর history data থেকে, যদি থাকে)
              │
              ▼
   Prediction Model (Regression + Classification)
   ├── লাভ/ক্ষতি অনুমান (টাকায়, একটা range সহ — honest uncertainty দেখাতে point-estimate না)
   └── Risk Factor Classification (কম/মাঝারি/বেশি + কারণ)
              │
              ▼
   RAG Layer
   ├── Retrieval: prediction output অনুযায়ী প্রাসঙ্গিক কৃষি-সম্প্রসারণ ডকুমেন্ট/best-practice guide খুঁজে বের করা
   └── Generation: prediction number + retrieved context মিলিয়ে LLM (FLAN-T5, ProtoFusion-এ ব্যবহৃত pipeline reuse) দিয়ে সহজ বাংলা feedback report লেখা
              │
              ▼
   Farmer-facing Report (UI-তে দেখানো)
```

---

## ২.৪ Model অংশ

- **Model type:** Tabular data-র জন্য XGBoost/Random Forest যথেষ্ট — deep learning দরকার নেই, তাই ৪০ দিনে realistic।
- **দুটো output:**
  1. Profit/Loss regression (range সহ, single number না)
  2. Risk classification (কম/মাঝারি/বেশি + contributing factors)
- **RAG:** structured prediction থেকে প্রাসঙ্গিক advisory document retrieve করে, তারপর LLM (FLAN-T5) দিয়ে natural Bangla report generate।

---

## ২.৫ Report-এর নমুনা (Example Output)

> "এই মৌসুমে ধান চাষে আনুমানিক লাভ: ৳১৫,০০০–২২,০০০/বিঘা। ঝুঁকি: মাঝারি। কারণ: গত ৩ বছরে এই সময়ে ধানের দাম গড়ে ৮% কমেছে ফলন বেশি হওয়ার কারণে। পরামর্শ: আগে থেকে বিক্রির চুক্তি করে রাখুন অথবা সংরক্ষণের ব্যবস্থা রাখুন।"

---

## ২.৫ক Crop Rotation Advisory (নতুন Feature)

**ধারণা:** একই জমিতে বারবার একই ফসল চাষ করলে মাটি ক্ষয় হয় (well-established agronomy fact)। এই জমিতে গত মৌসুম/বছরগুলোতে কী চাষ হয়েছিল তার history দেখে, model **rotation-friendly ফসল recommend** করবে — যেমন, গত মৌসুমে ধান হলে এই মৌসুমে ডাল/লেগিউম জাতীয় ফসল (যা মাটিতে নাইট্রোজেন ফিরিয়ে দেয়) suggest করা।

**Integration:** এটা আলাদা কোনো নতুন model না — বিদ্যমান Section 2 Prediction Model-এর **input feature হিসেবে "previous crop history" যোগ করলেই** এটা কাজ করবে, এবং RAG layer rotation-related agronomy guideline retrieve করে report-এ যোগ করবে। কোনো নতুন হার্ডওয়্যার বা আলাদা pipeline লাগছে না।

**Report-এ addition:**
> "গত মৌসুমে এই জমিতে ধান হয়েছিল। মাটির স্বাস্থ্য ভালো রাখতে এই মৌসুমে মুগ ডাল বা খেসারি চাষের পরামর্শ দেওয়া হচ্ছে।"

---

## ২.৫খ সরকারি ফসল বীমা/প্রণোদনা Scheme Matcher (নতুন Feature)

**ধারণা:** Section 2-এর risk output অনুযায়ী ("ঝুঁকি বেশি" চিহ্নিত হলে) কৃষককে প্রাসঙ্গিক **সরকারি ফসল বীমা প্রকল্প বা কৃষি প্রণোদনা** সম্পর্কে জানানো, যাতে ঝুঁকিপূর্ণ চাষে আর্থিক সুরক্ষা পাওয়া যায়।

**Integration:** এটাও নতুন model না — RAG layer-এর **knowledge base-এ সরকারি scheme-সংক্রান্ত ডকুমেন্ট যোগ করলেই** এটা কাজ করবে (risk বেশি হলে সেই ধরনের document retrieve হয়ে report-এ যুক্ত হবে)।

**Report-এ addition:**
> "যেহেতু এই চাষে ঝুঁকি বেশি, সরকারি ফসল বীমা স্কিম-এর আওতায় আবেদন করার কথা বিবেচনা করতে পারেন — এতে ফলন কম হলে বা দাম পড়ে গেলে কিছুটা ক্ষতিপূরণ পাওয়া সম্ভব।"

**Open item:** কোন নির্দিষ্ট সরকারি স্কিম-এর তথ্য RAG knowledge base-এ রাখা হবে তা এখনো ঠিক করা হয়নি — কৃষি মন্ত্রণালয়/সংশ্লিষ্ট দপ্তরের public তথ্য থেকে সংগ্রহ করতে হবে।

---

## ২.৬ যা লাগবে (Requirements & Open Questions)

- **Dataset (সবচেয়ে বড় bottleneck):** ঐতিহাসিক crop yield + market price + season/weather data — জেলা/উপজেলা-ভিত্তিক হলে ভালো। সম্ভাব্য উৎস: DAE (Department of Agricultural Extension), BBS (Bangladesh Bureau of Statistics), কৃষি মন্ত্রণালয়ের open data। **এখনো ঠিক করা হয়নি — dataset source confirm করতে হবে।**
- **RAG Knowledge Base:** কোন document ব্যবহার হবে তা এখনো ঠিক হয়নি — কৃষি সম্প্রসারণ leaflet, নিজের তৈরি summary, নাকি web-scraped advisory — এটা confirm করতে হবে।
- **Model:** XGBoost/Random Forest দিয়ে শুরু করা যায়, নতুন hardware লাগবে না — এটা pure software/data কাজ।

---

## ২.৭ Section 1 এর সাথে সম্পর্ক

Section 1 (Daily Care & Monitoring) থেকে সংগৃহীত historical soil/growth/yield data ভবিষ্যতে Section 2-এর prediction model-কে আরও accurate করতে ব্যবহার করা যাবে — একবার কয়েক মৌসুম data জমা হলে, নিজস্ব farm-এর real history দিয়েও prediction refine করা সম্ভব হবে। প্রাথমিক ভাবে external dataset দিয়েই শুরু করতে হবে।

---
---

# 📙 Section 3: Cross-Cutting Feature — SMS / WhatsApp / IVR Multi-Channel Fallback

## ৩.১ উদ্দেশ্য (Purpose)

সব কৃষকের কাছে smartphone/app/internet নেই। শুধু বেসিক **SMS**, **WhatsApp**, বা **voice-call (IVR)** দিয়ে Section 1 ও Section 2-এর মূল advisory পাওয়ার option — এতে system-এর কভারেজ বাস্তবিকভাবেই বাড়ে, কারণ feature-phone বা basic-connectivity ব্যবহারকারী কৃষকরাও বাদ পড়েন না।

## ৩.২ কীভাবে কাজ করবে

- **SMS মোড:** Daily Advisory Agent (Section 1) বা Profit/Risk Report (Section 2)-এর সংক্ষিপ্ত সারাংশ একটা ছোট SMS আকারে পাঠানো — যেমন: "আজ পানি দিন, বিকেলে। সার প্রয়োজন নেই।" ১৬০ character সীমার মধ্যে compressed summary।
- **WhatsApp মোড:** একই backend/RAG pipeline-এ পৌঁছানোর আরেকটা channel, কিন্তু SMS-এর চেয়ে সমৃদ্ধ —
  - Character সীমা নেই, তাই আরও বিস্তারিত, readable (বোল্ড/ইমোজি সহ) রিপোর্ট পাঠানো যায়।
  - **শুধু text না — ছবি ও voice note-ও পাঠানো/নেওয়া যায়** — ভবিষ্যতে কৃষক WhatsApp দিয়েই leaf photo পাঠাতে পারবে (Section 1-এর Leaf Condition Check-এর সাথে যুক্ত হতে পারে), আর reply voice note আকারেও যেতে পারে (Voice Briefing, Feature #11-এর সাথে মিলে যায়)।
  - বাংলাদেশে WhatsApp ব্যবহার তুলনামূলক common, তাই coverage-এর দিক থেকেও ভালো fit।
- **IVR মোড:** কৃষক একটা নির্দিষ্ট নম্বরে কল দিলে, pre-recorded বা TTS-generated Bangla voice দিয়ে একই তথ্য শোনানো — একই TTS pipeline reuse করা যায়।
- **Implementation:** তিনটা channel-ই একই backend/RAG pipeline-এ পৌঁছায়, শুধু "channel adapter" আলাদা — Twilio SMS API, Twilio WhatsApp API (sandbox), এবং Twilio Voice API দিয়ে prototype করা যায়। কোনো নতুন hardware লাগে না, pure software/API integration।

## ৩.৩ কেন এটা Realistic

- এটা কোনো নতুন model বা hardware তৈরি করে না — existing advisory output-কে ভিন্ন delivery channel-এ পাঠানো, তাই low effort।
- Low-cost/effort-এ high impact — বাংলাদেশে অনেক কৃষকের কাছে হয় ফিচার-ফোন (SMS/IVR উপযোগী) অথবা বেসিক স্মার্টফোনে শুধু WhatsApp চালু থাকে — দুটো channel মিলিয়ে coverage সবচেয়ে বেশি।
- Section 1 ও Section 2 দুটোরই output এখানে reuse হয় — আলাদা কোনো নতুন logic লাগে না, শুধু delivery layer যোগ হয়।

## ৩.৪ Open Item

- SMS gateway/Twilio-এর জন্য Bangladesh-এ local pricing/availability এখনো যাচাই করা হয়নি — hackathon demo-র জন্য Twilio trial account দিয়েই যথেষ্ট হবে।
- **WhatsApp Business API-এর জন্য production-এ Meta-এর business verification লাগবে**, যেটা ৪০ দিনে সম্পূর্ণ করা কঠিন হতে পারে — কিন্তু Twilio-র **WhatsApp Sandbox** (বিনামূল্যে, testing/demo-এর জন্য) দিয়ে hackathon demo সম্পূর্ণ সম্ভব। Pitch-এ honestly এই সীমাবদ্ধতা mention করা ভালো ("production-এ Meta verification প্রয়োজন হবে")।

---

## ৩.৫ SMS/WhatsApp → RAG Model → SMS/WhatsApp: Section 2-এর সাথে বিস্তারিত Flow

**ধারণা:** কৃষক শুধু SMS বা WhatsApp message পাঠিয়েই (কোনো internet browsing/app ছাড়া) Section 2 (Pre-Planting Profit & Risk Advisor)-এর পুরো সুবিধা পাবে। দুটো channel-ই একই backend পাইপলাইনে যায়, শুধু delivery adapter আলাদা।

```
কৃষকের ফোন (SMS অথবা WhatsApp message পাঠায়)
   → Structured message পাঠালো, যেমন:
     "ধান, ২ বিঘা, উত্তর এলাকা"
        │
        │  [SMS নেটওয়ার্ক অথবা WhatsApp — browsing internet লাগে না]
        ▼
Host (SMS Gateway / WhatsApp Business API — Twilio দিয়ে receive করে)
        │
        │  Parsing: message text থেকে structured input তৈরি
        │  (crop = ধান, land_size = ২ বিঘা, location = উত্তর এলাকা)
        ▼
RAG Model (Section 2 — Profit/Risk Advisor, একই model দুই channel-এই reuse)
   ├── Prediction Model: লাভ/ক্ষতি + risk factor বের করা
   └── RAG: প্রাসঙ্গিক advisory document দিয়ে summary generate করা
   │     (SMS হলে ১৬০ character-এ compressed, WhatsApp হলে বিস্তারিত + ফরম্যাটিং সহ)
        │
        ▼
Host → একই channel দিয়ে ফেরত পাঠালো
        │
        ▼
কৃষকের ফোনে reply আসলো:
"ধান, ২ বিঘা: আনুমানিক লাভ ৳৩০,০০০-৪৪,০০০। ঝুঁকি: মাঝারি (দাম কমার সম্ভাবনা)। বিস্তারিত: shortlink বা কল করুন।"
```

**Design points:**
- কোনো নতুন model লাগছে না — Section 2-এর existing prediction + RAG pipeline-ই reuse হচ্ছে, শুধু input/output channel (SMS বা WhatsApp) পরিবর্তন।
- Input format সহজ রাখতে হবে — হয় comma-separated ("ফসল, জমির পরিমাণ, এলাকা"), অথবা keyword-based short code ("RICE 2 NORTH")।
- SMS output ১৬০ character সীমার মধ্যে compressed, WhatsApp output-এ বেশি detail/formatting দেওয়া যায় (character সীমা নেই)।
- WhatsApp-এ ভবিষ্যতে ছবি (leaf photo) ও voice note input/output-ও সম্ভব — SMS-এ শুধু text।
- **সবচেয়ে বড় impact পয়েন্ট:** কোনো smartphone app/internet browsing ছাড়াই সম্পূর্ণ AI-powered risk advisory ব্যবহার করা যাচ্ছে — coverage-এর দিক থেকে এটা সবচেয়ে বড় reach দেয়।
- **Demo:** live SMS ও WhatsApp দুটোই পাঠিয়ে (Twilio trial number/sandbox দিয়ে) কয়েক সেকেন্ডে reply আসা দেখানো — judges-দের সামনে শক্তিশালী, tangible demo মুহূর্ত।

---

## ৩.৬ Backend Scheduling — Capability-Aware Job Queue

**সমস্যা:** বাস্তবে multi-channel (SMS/WhatsApp/IVR) handling-এ একাধিক backend worker/server থাকতে পারে, আর প্রতিটা কৃষকের request নির্দিষ্ট worker-এর সাথেই যেতে পারে এমন না — কোনো request শুধু একটা channel handler-এর সাথে compatible, কোনোটা একাধিকের সাথে। একটা worker ব্যস্ত থাকলে বাকি request queue-তে অপেক্ষা করে, কিন্তু blind FIFO ব্যবহার করলে এমন হতে পারে একটা worker খালি বসে আছে অথচ সে যে request serve করতে পারত সেটা queue-তে পরে আছে।

**সমাধান:** দুটো আলাদা physical server না চালিয়ে, single backend-এ একটা **capability-tagged job queue** রাখা — প্রতিটা job-এ ট্যাগ থাকবে এটা কোন worker(গুলো) handle করতে পারে, আর worker ফ্রি হলে সে queue থেকে এমন সবচেয়ে পুরনো job খুঁজে নেবে যেটা তার capability-র সাথে মেলে (শুধু FIFO না)।

```
Job আসে → queue-তে জমা হয় (সাথে allowed_servers ট্যাগ)
Worker ফ্রি হলে → queue স্ক্যান করে → নিজের capability-র সাথে মেলে এমন সবচেয়ে পুরনো job নেয়
Worker ব্যস্ত থাকলে → তার জন্য উপযুক্ত job queue-তেই অপেক্ষা করে
```

**Scope:** এটা মূলত Section 3-এর multi-channel backend-এর ইনফ্রাস্ট্রাকচার লজিক (SMS worker/WhatsApp worker আলাদা হলে এভাবে route হবে) — demo-তে সরাসরি "eye-catching" feature না, কিন্তু system-কে robust ও scalable দেখানোর জন্য ব্যাকগ্রাউন্ডে থাকা দরকার। কোনো নতুন hardware বা model লাগে না, pure backend logic।

**Reference implementation:** `capability_queue.py` — single-process Python demo যেখানে Server A/B, এবং তিনটা ভিন্ন capability-র request (শুধু B-compatible, শুধু A-compatible, দুটোই-compatible) simulate করে দেখানো হয়েছে যে worker ফ্রি হওয়ার সাথে সাথে সঠিক job তুলে নেয়। প্রোডাকশনে `Server` ক্লাসের `process()` method-এর ভেতরে sleep-এর বদলে real RAG/LLM call বসবে।

---
---

## ২.৮ Notes / এখনো Open থাকা বিষয়

- Dataset source এখনো চূড়ান্ত হয়নি — এটা প্রথমে ঠিক করতে হবে, কারণ পুরো Section 2 এর উপর নির্ভরশীল।
- RAG knowledge base-এর জন্য কোন document ব্যবহার হবে তা confirm করা বাকি।
- Profit/loss output অবশ্যই range/uncertainty সহ দেখাতে হবে, single confident number হিসেবে না — honest reporting এর জন্য গুরুত্বপূর্ণ।# GrowthTwin — Project Documentation
## Section 1: Daily Care & Monitoring | Section 2: Pre-Planting Profit & Risk Advisor | Section 3: SMS/WhatsApp/IVR Fallback

---

# 📗 Section 1: Daily Care & Monitoring

## ১.১ এই সেকশনের উদ্দেশ্য (Purpose)

গাছ লাগানোর দিন থেকে শুরু করে প্রতিদিনের পরিচর্যা পর্যন্ত পুরো প্রক্রিয়াটা sensor + CV দিয়ে monitor করা, এবং farmer-কে প্রতিদিন app-এর মাধ্যমে সহজ ভাষায় (Bangla) actionable update দেওয়া — কখন পানি দিতে হবে, কখন সার দিতে হবে, গাছের পাতা/অবস্থা কেমন, এবং কী করলে ভালো হয়।

এটা মূল **GrowthTwin** সিস্টেমের একটি সাব-মডিউল — GrowthTwin গাছের বড় হওয়ার stage (growth stage) track করে, আর এই "Daily Care" module প্রতিদিনের micro-level care (পানি, সার, রোদ, রোগ-ঝুঁকি) handle করে।

---

## ১.২ Hardware / Sensor List

| Sensor | কাজ | আনুমানিক Cost | Note |
|---|---|---|---|
| Capacitive Soil Moisture Sensor | মাটির আর্দ্রতা মাপা → পানি দেওয়ার সিদ্ধান্ত | $2–3 | সবচেয়ে সহজ ও reliable, প্রতি zone-এ একটা |
| LDR / LUX Light Sensor | গাছ কতটা রোদ পাচ্ছে | $1–2 | কম রোদের কারণে দুর্বলতা আলাদা করে চিহ্নিত করতে সাহায্য করে |
| DHT22 (Temp/Humidity) | তাপমাত্রা ও আর্দ্রতা → pest/fungal risk অনুমান | $1–3 | আগে থেকেই মূল hardware list-এ আছে |
| ESP32 (Microcontroller) | সব sensor থেকে data collect ও পাঠানো | $3–6 | প্রতি zone-এ একটা |

**pH Measurement — Hardware-free (সবচেয়ে সস্তা বিকল্প):** dedicated pH sensor hardware ($25-40 combo, এমনকি standalone probe-ও $50-90) সম্পূর্ণ বাদ দেওয়া হয়েছে। বদলে **CV-based pH Strip Reading**: বাজারের সস্তা pH test strip (৫০+ strip বক্স ~২০০-৪০০ টাকা) ব্যবহার করে, phone camera দিয়ে ছবি তুলে color-calibration chart অনুযায়ী CV দিয়ে রং থেকে pH value বের করা হবে।

**Design সিদ্ধান্ত (Important):** Sensor বসবে **zone-based** (জমির ছোট অংশ ধরে), per-plant না — কারণ কাছাকাছি মাটির condition প্রায় একই থাকে, আর per-plant sensor বসানো অবাস্তব ও ব্যয়বহুল।

---

## ১.৩ Computer Vision-এর ভূমিকা

এই "Daily Care" section sensor-heavy দেখতে হলেও, **CV হচ্ছে প্রধান ইঞ্জিন আর sensor হলো সাপোর্টিং layer**। CV চার জায়গায় কাজ করছে:

| CV কাজ | কোথায় ব্যবহার | Model/Approach |
|---|---|---|
| **Leaf Disease/Deficiency Detection** | Leaf Condition Check | ProtoFusion (CNN-ViT hybrid + prototype XAI) — আগে থেকেই তৈরি, ৯৮%+ accuracy |
| **Growth Stage Classification** | Growth Photo Timeline | GrowthTwin-এর মূল CV task — চারা→বাড়ন্ত→ফুল→ফল→পরিপক্ব, height/leaf-count estimation সহ |
| **Root Condition (Indirect)** | Root Estimation | সরাসরি CV না — wilting pattern + moisture + leaf trend মিলিয়ে অনুমান (nursery/potted হলে সরাসরি ছবি সম্ভব) |
| **pH Strip Color Reading** | Fertilizer Advisory | Test strip-এর ছবি তুলে color-calibration chart দিয়ে pH value বের করা — dedicated pH hardware-এর সস্তা বিকল্প |

**কেন sensor + CV দুটোই দরকার:** sensor দেয় মাটির ভেতরের (invisible) অবস্থা — moisture, pH। CV দেয় গাছের বাইরের (visible) অবস্থা — পাতার রং, দাগ, growth। দুটো data একসাথে মিলিয়েই Daily Advisory Agent সঠিক সিদ্ধান্ত নেয়।

আগের আলোচনায় হওয়া সব agentic CV feature (diagnostic interview, active-capture, counterfactual explanation, ensemble self-doubt, text-vision consistency) **Leaf Condition Check** অংশেই plug হবে — এটাই পুরো system-এর CV core।

---

## ১.৪ Feature List (সম্পূর্ণ তালিকা)

### A. Core Sensing & Advisory
1. **Soil Moisture-based Watering Advisory** — সেন্সর reading থেকে "আজ পানি দরকার / দরকার নেই" বলা।
2. **pH-based Fertilizer Advisory** — pH test strip-এর ছবি (CV দিয়ে রং পড়া) + leaf-CV nutrient-deficiency signal মিলিয়ে কখন সার দিতে হবে তা বলা।
3. **Fertilizer Dosage Calculator** — pH (strip reading) + leaf-CV deficiency severity + growth stage মিলিয়ে **কত পরিমাণ** সার লাগবে তা বলা।
4. **Light/Sunlight Tracking** — পর্যাপ্ত রোদ পাচ্ছে কিনা, দুর্বলতার কারণ আলাদা করা।

### B. Visual/CV-based
5. **Leaf Condition Check** — ছবি তুলে দিলে disease/nutrient-deficiency CV দিয়ে check।
6. **Root Condition (Indirect Estimation)** — wilting pattern + soil moisture + leaf trend মিলিয়ে root-সমস্যা অনুমান।
7. **Growth Photo Timeline (Visual Diary)** — প্রতি সপ্তাহে ছবি পাশাপাশি রেখে growth তুলনা।

### C. Predictive/Proactive
8. **Weather-aware Predictive Stress Alert** — আজকের sensor data + ২-৩ দিনের forecast মিলিয়ে আগে থেকে পরামর্শ।
9. **Preventive Pest/Fungal Risk Alert** — Temperature + humidity combination থেকে pest/fungal risk আগে থেকে জানানো।

### D. Farmer-facing UI/UX
10. **Daily Bangla Status Update** — প্রতিদিন app-এ "আজকের অবস্থা" card।
11. **Voice-based Daily Briefing** — Bangla voice-এ শোনার option (accessibility)।
12. **"কেন?" (Explain Why) Button** — প্রতিটা recommendation-এর কারণ সহজ ভাষায় দেখানো।
13. **Multi-Plant/Plot Dashboard** — color-coded (সবুজ/হলুদ/লাল) overview।

### E. Tracking & Comparison
14. **Water Usage Tracker + Savings Calculator** — পানি সাশ্রয় দেখানো।
15. **Seasonal Comparison/History** — এই বছরের growth এর সাথে আগের season-এর তুলনা।

---

## ১.৫ Data Flow

```
[Soil Moisture + Light + Temp/Humidity Sensors] + [pH Strip Photo]
              │
              ▼
   ESP32 (sensor data) + Phone Camera (pH strip + leaf photo)
              │
              ▼
   Phone App / Local Hub (LoRa বা WiFi এর মাধ্যমে)
              │
              ▼
   Daily Advisory Agent
   ├── পানি দরকার কিনা? (moisture + weather forecast)
   ├── সার দরকার কিনা, কতটুকু? (pH strip CV reading + leaf-CV deficiency signal + growth stage)
   ├── Pest/fungal risk আছে কিনা? (temp + humidity pattern)
   └── আলো পর্যাপ্ত কিনা?
              │
              ▼
   [+ Farmer-submitted Leaf Photo] → CV Disease/Deficiency Check
              │
              ▼
   Daily Bangla Update (Text + Voice) + "কেন?" Explanation
              │
              ▼
   App UI: Status Card + Growth Timeline + Multi-plot Dashboard
```

---

## ১.৬ GrowthTwin-এর সাথে সম্পর্ক

- **GrowthTwin** = গাছের বড় হওয়ার macro-stage track করে, দীর্ঘমেয়াদী planning (harvest timing, labor booking) করে।
- **Daily Care & Monitoring** = প্রতিদিনের micro-level care handle করে।
- দুটো module একসাথে কাজ করে: Daily Care থেকে পাওয়া growth-abnormality data GrowthTwin-এর **Anomaly Agent**-কে trigger করতে পারে, যা Disease Detection module (ProtoFusion-based) চালু করে।

---

## ১.৭ ৪০ দিনে কী Build করা Realistic

**অবশ্যই বানানো (Core, fully working):**
- Soil moisture sensor + watering advisory
- pH strip CV reading + leaf-CV deficiency signal → fertilizer advisory + dosage calculator
- Daily Bangla status update (text)
- Leaf photo CV check (ProtoFusion pipeline ব্যবহার করে)
- "কেন?" explanation button

**হালকা Proof-of-Concept হিসেবে যথেষ্ট:**
- Weather-aware predictive alert (simple rule-based)
- Voice briefing (basic TTS)
- Seasonal comparison (mock/demo data)
- Multi-plot dashboard (২-৩টা demo plot)

---

## ১.৮ Notes

- Root imaging সরাসরি field crop-এ practically কঠিন — indirect estimation ব্যবহার করা হবে।
- Sensor বসবে **per-zone**, per-plant না।
- NPK+pH sensor hardware খরচের কারণে বাদ, বদলে CV-based pH strip reading।
- নতুন feature গুলো (water tracker, seasonal comparison, voice briefing) existing sensor/CV data থেকেই generate হয়, নতুন hardware লাগে না।

---
---

# 📘 Section 2: Pre-Planting Profit & Risk Advisor

## ২.১ এই সেকশনের উদ্দেশ্য (Purpose)

কৃষক গাছ লাগানোর **আগেই** জানতে পারবে — এই মৌসুমে এই ফসল চাষ করলে সম্ভাব্য লাভ কত হতে পারে, কী কী ঝুঁকি আছে, এবং সেই ঝুঁকি কমানোর জন্য কী করা উচিত। এটা GrowthTwin-এর প্রথম ধাপ — গাছ লাগানোর আগের সিদ্ধান্ত-সহায়ক মডিউল (আগে থেকেই আলোচনা হওয়া "Pre-Planting Soil & History Advisory" ধারণার concrete, buildable version)।

---

## ২.২ Input (কৃষক কী দিবে)

- ফসলের নাম (যেমন: ধান, গম, সবজি)
- প্লট/এলাকার তথ্য (জেলা/উপজেলা, মাটির ধরন — যদি Section 1 থেকে ইতিমধ্যে soil data থাকে সেটাও ব্যবহার করা যাবে)
- চাষের মৌসুম/সময়কাল

---

## ২.৩ পাইপলাইন (Architecture)

```
Farmer Input (crop, plot location/soil, season)
              │
              ▼
   Feature Engineering
   ├── ঐতিহাসিক yield data (ওই ফসল, ওই এলাকা/মাটি)
   ├── ঐতিহাসিক বাজার দাম trend (ওই ফসলের)
   ├── আবহাওয়া/মৌসুম উপযুক্ততা
   ├── ইনপুট খরচ (বীজ, সার, শ্রম — আনুমানিক)
   └── প্লটের soil condition (Section 1-এর history data থেকে, যদি থাকে)
              │
              ▼
   Prediction Model (Regression + Classification)
   ├── লাভ/ক্ষতি অনুমান (টাকায়, একটা range সহ — honest uncertainty দেখাতে point-estimate না)
   └── Risk Factor Classification (কম/মাঝারি/বেশি + কারণ)
              │
              ▼
   RAG Layer
   ├── Retrieval: prediction output অনুযায়ী প্রাসঙ্গিক কৃষি-সম্প্রসারণ ডকুমেন্ট/best-practice guide খুঁজে বের করা
   └── Generation: prediction number + retrieved context মিলিয়ে LLM (FLAN-T5, ProtoFusion-এ ব্যবহৃত pipeline reuse) দিয়ে সহজ বাংলা feedback report লেখা
              │
              ▼
   Farmer-facing Report (UI-তে দেখানো)
```

---

## ২.৪ Model অংশ

- **Model type:** Tabular data-র জন্য XGBoost/Random Forest যথেষ্ট — deep learning দরকার নেই, তাই ৪০ দিনে realistic।
- **দুটো output:**
  1. Profit/Loss regression (range সহ, single number না)
  2. Risk classification (কম/মাঝারি/বেশি + contributing factors)
- **RAG:** structured prediction থেকে প্রাসঙ্গিক advisory document retrieve করে, তারপর LLM (FLAN-T5) দিয়ে natural Bangla report generate।

---

## ২.৫ Report-এর নমুনা (Example Output)

> "এই মৌসুমে ধান চাষে আনুমানিক লাভ: ৳১৫,০০০–২২,০০০/বিঘা। ঝুঁকি: মাঝারি। কারণ: গত ৩ বছরে এই সময়ে ধানের দাম গড়ে ৮% কমেছে ফলন বেশি হওয়ার কারণে। পরামর্শ: আগে থেকে বিক্রির চুক্তি করে রাখুন অথবা সংরক্ষণের ব্যবস্থা রাখুন।"

---

## ২.৫ক Crop Rotation Advisory (নতুন Feature)

**ধারণা:** একই জমিতে বারবার একই ফসল চাষ করলে মাটি ক্ষয় হয় (well-established agronomy fact)। এই জমিতে গত মৌসুম/বছরগুলোতে কী চাষ হয়েছিল তার history দেখে, model **rotation-friendly ফসল recommend** করবে — যেমন, গত মৌসুমে ধান হলে এই মৌসুমে ডাল/লেগিউম জাতীয় ফসল (যা মাটিতে নাইট্রোজেন ফিরিয়ে দেয়) suggest করা।

**Integration:** এটা আলাদা কোনো নতুন model না — বিদ্যমান Section 2 Prediction Model-এর **input feature হিসেবে "previous crop history" যোগ করলেই** এটা কাজ করবে, এবং RAG layer rotation-related agronomy guideline retrieve করে report-এ যোগ করবে। কোনো নতুন হার্ডওয়্যার বা আলাদা pipeline লাগছে না।

**Report-এ addition:**
> "গত মৌসুমে এই জমিতে ধান হয়েছিল। মাটির স্বাস্থ্য ভালো রাখতে এই মৌসুমে মুগ ডাল বা খেসারি চাষের পরামর্শ দেওয়া হচ্ছে।"

---

## ২.৫খ সরকারি ফসল বীমা/প্রণোদনা Scheme Matcher (নতুন Feature)

**ধারণা:** Section 2-এর risk output অনুযায়ী ("ঝুঁকি বেশি" চিহ্নিত হলে) কৃষককে প্রাসঙ্গিক **সরকারি ফসল বীমা প্রকল্প বা কৃষি প্রণোদনা** সম্পর্কে জানানো, যাতে ঝুঁকিপূর্ণ চাষে আর্থিক সুরক্ষা পাওয়া যায়।

**Integration:** এটাও নতুন model না — RAG layer-এর **knowledge base-এ সরকারি scheme-সংক্রান্ত ডকুমেন্ট যোগ করলেই** এটা কাজ করবে (risk বেশি হলে সেই ধরনের document retrieve হয়ে report-এ যুক্ত হবে)।

**Report-এ addition:**
> "যেহেতু এই চাষে ঝুঁকি বেশি, সরকারি ফসল বীমা স্কিম-এর আওতায় আবেদন করার কথা বিবেচনা করতে পারেন — এতে ফলন কম হলে বা দাম পড়ে গেলে কিছুটা ক্ষতিপূরণ পাওয়া সম্ভব।"

**Open item:** কোন নির্দিষ্ট সরকারি স্কিম-এর তথ্য RAG knowledge base-এ রাখা হবে তা এখনো ঠিক করা হয়নি — কৃষি মন্ত্রণালয়/সংশ্লিষ্ট দপ্তরের public তথ্য থেকে সংগ্রহ করতে হবে।

---

## ২.৬ যা লাগবে (Requirements & Open Questions)

- **Dataset (সবচেয়ে বড় bottleneck):** ঐতিহাসিক crop yield + market price + season/weather data — জেলা/উপজেলা-ভিত্তিক হলে ভালো। সম্ভাব্য উৎস: DAE (Department of Agricultural Extension), BBS (Bangladesh Bureau of Statistics), কৃষি মন্ত্রণালয়ের open data। **এখনো ঠিক করা হয়নি — dataset source confirm করতে হবে।**
- **RAG Knowledge Base:** কোন document ব্যবহার হবে তা এখনো ঠিক হয়নি — কৃষি সম্প্রসারণ leaflet, নিজের তৈরি summary, নাকি web-scraped advisory — এটা confirm করতে হবে।
- **Model:** XGBoost/Random Forest দিয়ে শুরু করা যায়, নতুন hardware লাগবে না — এটা pure software/data কাজ।

---

## ২.৭ Section 1 এর সাথে সম্পর্ক

Section 1 (Daily Care & Monitoring) থেকে সংগৃহীত historical soil/growth/yield data ভবিষ্যতে Section 2-এর prediction model-কে আরও accurate করতে ব্যবহার করা যাবে — একবার কয়েক মৌসুম data জমা হলে, নিজস্ব farm-এর real history দিয়েও prediction refine করা সম্ভব হবে। প্রাথমিক ভাবে external dataset দিয়েই শুরু করতে হবে।

---
---

# 📙 Section 3: Cross-Cutting Feature — SMS / WhatsApp / IVR Multi-Channel Fallback

## ৩.১ উদ্দেশ্য (Purpose)

সব কৃষকের কাছে smartphone/app/internet নেই। শুধু বেসিক **SMS**, **WhatsApp**, বা **voice-call (IVR)** দিয়ে Section 1 ও Section 2-এর মূল advisory পাওয়ার option — এতে system-এর কভারেজ বাস্তবিকভাবেই বাড়ে, কারণ feature-phone বা basic-connectivity ব্যবহারকারী কৃষকরাও বাদ পড়েন না।

## ৩.২ কীভাবে কাজ করবে

- **SMS মোড:** Daily Advisory Agent (Section 1) বা Profit/Risk Report (Section 2)-এর সংক্ষিপ্ত সারাংশ একটা ছোট SMS আকারে পাঠানো — যেমন: "আজ পানি দিন, বিকেলে। সার প্রয়োজন নেই।" ১৬০ character সীমার মধ্যে compressed summary।
- **WhatsApp মোড:** একই backend/RAG pipeline-এ পৌঁছানোর আরেকটা channel, কিন্তু SMS-এর চেয়ে সমৃদ্ধ —
  - Character সীমা নেই, তাই আরও বিস্তারিত, readable (বোল্ড/ইমোজি সহ) রিপোর্ট পাঠানো যায়।
  - **শুধু text না — ছবি ও voice note-ও পাঠানো/নেওয়া যায়** — ভবিষ্যতে কৃষক WhatsApp দিয়েই leaf photo পাঠাতে পারবে (Section 1-এর Leaf Condition Check-এর সাথে যুক্ত হতে পারে), আর reply voice note আকারেও যেতে পারে (Voice Briefing, Feature #11-এর সাথে মিলে যায়)।
  - বাংলাদেশে WhatsApp ব্যবহার তুলনামূলক common, তাই coverage-এর দিক থেকেও ভালো fit।
- **IVR মোড:** কৃষক একটা নির্দিষ্ট নম্বরে কল দিলে, pre-recorded বা TTS-generated Bangla voice দিয়ে একই তথ্য শোনানো — একই TTS pipeline reuse করা যায়।
- **Implementation:** তিনটা channel-ই একই backend/RAG pipeline-এ পৌঁছায়, শুধু "channel adapter" আলাদা — Twilio SMS API, Twilio WhatsApp API (sandbox), এবং Twilio Voice API দিয়ে prototype করা যায়। কোনো নতুন hardware লাগে না, pure software/API integration।

## ৩.৩ কেন এটা Realistic

- এটা কোনো নতুন model বা hardware তৈরি করে না — existing advisory output-কে ভিন্ন delivery channel-এ পাঠানো, তাই low effort।
- Low-cost/effort-এ high impact — বাংলাদেশে অনেক কৃষকের কাছে হয় ফিচার-ফোন (SMS/IVR উপযোগী) অথবা বেসিক স্মার্টফোনে শুধু WhatsApp চালু থাকে — দুটো channel মিলিয়ে coverage সবচেয়ে বেশি।
- Section 1 ও Section 2 দুটোরই output এখানে reuse হয় — আলাদা কোনো নতুন logic লাগে না, শুধু delivery layer যোগ হয়।

## ৩.৪ Open Item

- SMS gateway/Twilio-এর জন্য Bangladesh-এ local pricing/availability এখনো যাচাই করা হয়নি — hackathon demo-র জন্য Twilio trial account দিয়েই যথেষ্ট হবে।
- **WhatsApp Business API-এর জন্য production-এ Meta-এর business verification লাগবে**, যেটা ৪০ দিনে সম্পূর্ণ করা কঠিন হতে পারে — কিন্তু Twilio-র **WhatsApp Sandbox** (বিনামূল্যে, testing/demo-এর জন্য) দিয়ে hackathon demo সম্পূর্ণ সম্ভব। Pitch-এ honestly এই সীমাবদ্ধতা mention করা ভালো ("production-এ Meta verification প্রয়োজন হবে")।

---

## ৩.৫ SMS/WhatsApp → RAG Model → SMS/WhatsApp: Section 2-এর সাথে বিস্তারিত Flow

**ধারণা:** কৃষক শুধু SMS বা WhatsApp message পাঠিয়েই (কোনো internet browsing/app ছাড়া) Section 2 (Pre-Planting Profit & Risk Advisor)-এর পুরো সুবিধা পাবে। দুটো channel-ই একই backend পাইপলাইনে যায়, শুধু delivery adapter আলাদা।

```
কৃষকের ফোন (SMS অথবা WhatsApp message পাঠায়)
   → Structured message পাঠালো, যেমন:
     "ধান, ২ বিঘা, উত্তর এলাকা"
        │
        │  [SMS নেটওয়ার্ক অথবা WhatsApp — browsing internet লাগে না]
        ▼
Host (SMS Gateway / WhatsApp Business API — Twilio দিয়ে receive করে)
        │
        │  Parsing: message text থেকে structured input তৈরি
        │  (crop = ধান, land_size = ২ বিঘা, location = উত্তর এলাকা)
        ▼
RAG Model (Section 2 — Profit/Risk Advisor, একই model দুই channel-এই reuse)
   ├── Prediction Model: লাভ/ক্ষতি + risk factor বের করা
   └── RAG: প্রাসঙ্গিক advisory document দিয়ে summary generate করা
   │     (SMS হলে ১৬০ character-এ compressed, WhatsApp হলে বিস্তারিত + ফরম্যাটিং সহ)
        │
        ▼
Host → একই channel দিয়ে ফেরত পাঠালো
        │
        ▼
কৃষকের ফোনে reply আসলো:
"ধান, ২ বিঘা: আনুমানিক লাভ ৳৩০,০০০-৪৪,০০০। ঝুঁকি: মাঝারি (দাম কমার সম্ভাবনা)। বিস্তারিত: shortlink বা কল করুন।"
```

**Design points:**
- কোনো নতুন model লাগছে না — Section 2-এর existing prediction + RAG pipeline-ই reuse হচ্ছে, শুধু input/output channel (SMS বা WhatsApp) পরিবর্তন।
- Input format সহজ রাখতে হবে — হয় comma-separated ("ফসল, জমির পরিমাণ, এলাকা"), অথবা keyword-based short code ("RICE 2 NORTH")।
- SMS output ১৬০ character সীমার মধ্যে compressed, WhatsApp output-এ বেশি detail/formatting দেওয়া যায় (character সীমা নেই)।
- WhatsApp-এ ভবিষ্যতে ছবি (leaf photo) ও voice note input/output-ও সম্ভব — SMS-এ শুধু text।
- **সবচেয়ে বড় impact পয়েন্ট:** কোনো smartphone app/internet browsing ছাড়াই সম্পূর্ণ AI-powered risk advisory ব্যবহার করা যাচ্ছে — coverage-এর দিক থেকে এটা সবচেয়ে বড় reach দেয়।
- **Demo:** live SMS ও WhatsApp দুটোই পাঠিয়ে (Twilio trial number/sandbox দিয়ে) কয়েক সেকেন্ডে reply আসা দেখানো — judges-দের সামনে শক্তিশালী, tangible demo মুহূর্ত।

---

## ৩.৬ Backend Scheduling — Capability-Aware Job Queue

**সমস্যা:** বাস্তবে multi-channel (SMS/WhatsApp/IVR) handling-এ একাধিক backend worker/server থাকতে পারে, আর প্রতিটা কৃষকের request নির্দিষ্ট worker-এর সাথেই যেতে পারে এমন না — কোনো request শুধু একটা channel handler-এর সাথে compatible, কোনোটা একাধিকের সাথে। একটা worker ব্যস্ত থাকলে বাকি request queue-তে অপেক্ষা করে, কিন্তু blind FIFO ব্যবহার করলে এমন হতে পারে একটা worker খালি বসে আছে অথচ সে যে request serve করতে পারত সেটা queue-তে পরে আছে।

**সমাধান:** দুটো আলাদা physical server না চালিয়ে, single backend-এ একটা **capability-tagged job queue** রাখা — প্রতিটা job-এ ট্যাগ থাকবে এটা কোন worker(গুলো) handle করতে পারে, আর worker ফ্রি হলে সে queue থেকে এমন সবচেয়ে পুরনো job খুঁজে নেবে যেটা তার capability-র সাথে মেলে (শুধু FIFO না)।

```
Job আসে → queue-তে জমা হয় (সাথে allowed_servers ট্যাগ)
Worker ফ্রি হলে → queue স্ক্যান করে → নিজের capability-র সাথে মেলে এমন সবচেয়ে পুরনো job নেয়
Worker ব্যস্ত থাকলে → তার জন্য উপযুক্ত job queue-তেই অপেক্ষা করে
```

**Scope:** এটা মূলত Section 3-এর multi-channel backend-এর ইনফ্রাস্ট্রাকচার লজিক (SMS worker/WhatsApp worker আলাদা হলে এভাবে route হবে) — demo-তে সরাসরি "eye-catching" feature না, কিন্তু system-কে robust ও scalable দেখানোর জন্য ব্যাকগ্রাউন্ডে থাকা দরকার। কোনো নতুন hardware বা model লাগে না, pure backend logic।

**Reference implementation:** `capability_queue.py` — single-process Python demo যেখানে Server A/B, এবং তিনটা ভিন্ন capability-র request (শুধু B-compatible, শুধু A-compatible, দুটোই-compatible) simulate করে দেখানো হয়েছে যে worker ফ্রি হওয়ার সাথে সাথে সঠিক job তুলে নেয়। প্রোডাকশনে `Server` ক্লাসের `process()` method-এর ভেতরে sleep-এর বদলে real RAG/LLM call বসবে।

---
---

## ২.৮ Notes / এখনো Open থাকা বিষয়

- Dataset source এখনো চূড়ান্ত হয়নি — এটা প্রথমে ঠিক করতে হবে, কারণ পুরো Section 2 এর উপর নির্ভরশীল।
- RAG knowledge base-এর জন্য কোন document ব্যবহার হবে তা confirm করা বাকি।
- Profit/loss output অবশ্যই range/uncertainty সহ দেখাতে হবে, single confident number হিসেবে না — honest reporting এর জন্য গুরুত্বপূর্ণ।
