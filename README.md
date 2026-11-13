# GOLD AI QUANT

محرك بحث كمي لـ XAU/USD + تطبيق Android بشاشة عربية واحدة وزر «ماذا أفعل؟».
**إشارات وتداول ورقي فقط — لا تنفيذ صفقات، ولا ضمان لأي نسبة نجاح.**

## التشغيل السحابي المجاني (موصى به)
راجع `docs/CLOUD_SETUP_AR.md`: GitHub Actions يجمع البيانات ويدرّب، وRender يخدم التطبيق. لا حاجة لحاسوب يعمل باستمرار.

## التشغيل المحلي (ويندوز)
1. ثبّت Python 3.12+.
2. (للوضع الحي) احصل على مفتاح مجاني من twelvedata.com وضعه في `start_server_windows.bat`.
3. شغّل `start_server_windows.bat`.
4. انسخ `config/calendar.example.json` إلى `backend/data/calendar.json` وحدّثه أسبوعياً من المواقع الرسمية.
5. افحص المصادر الحية مرة واحدة: `python backend/tools/live_contract_check.py`.
6. في التطبيق ← الإعدادات: `http://<IP-حاسوبك>:8000` (و الرمز السري إن ضبطت `GOLDQUANT_TOKEN`).

Linux/Mac: `./start_server.sh`. المتغيرات: `config/env.example`.

## كيف يُتخذ القرار
بيانات ← **جدار جودة البيانات** + **سجل Point-in-Time** ← الميزات وحالة السوق ← نموذج المسارات (هدف/وقف/لا شيء × 4 آفاق)
← الناقد، فخاخ السيولة، الحالات التاريخية، السياق (FRED/COT/أخبار/تقويم) ← **محكمة القرار**:
(1) قاضي الأدلة (2) قاضي الإحصاء: عائد متوقع موجب **بعد التكاليف** بنموذج مؤهل ومعاير (3) **حارس المخاطر المستقل**.
شراء/بيع فقط بالإجماع؛ غير ذلك **انتظر**. كل قرار يُسجَّل في سلسلة تدقيق مُجزّأة (`/audit/verify`).

## نقاط النهاية
`/health` `/data-status` `/decision` `/history` `/engines` `/paper` `/shadow` `/governance` `/audit/verify` `/audit/{id}`
بحث: `/model-metrics` `/research/backtest` `/research/precision` `/research/micro-edge` `/research/info-value`
`/research/granger` `/research/adversarial` `/research/integrity`

## أدوات
- `tools/live_contract_check.py` — فحص المصادر الحية
- `tools/run_precision.py` — تقييم V3 الكامل + بوابة الترقية (تُكتب `data/promotions.json`)
- `tools/run_final_backtest.py` — فترة الاختبار النهائية (تُسجَّل كل مرة)

## الاختبارات
```bash
cd backend && pip install -r requirements.txt && python -m pytest -q -o addopts=""   # 192 اختبار
cd android && ./gradlew testDebugUnitTest assembleDebug                            # يحتاج Android SDK
```

## بناء APK مجاناً
ارفع المستودع إلى GitHub فيعمل `.github/workflows/android.yml` ويرفع `gold-ai-quant-apk`، أو افتح `android/` في Android Studio.

## الصدق في النتائج
- الوضع التجريبي = أسعار اصطناعية، موسومة، بلا أي احتمالات.
- لا رقم احتمال إلا بعد اجتياز اختبارات المعايرة على **بيانات حية**.
- لا يدخل أي محرك جديد الإنتاج إلا عبر بوابة الترقية على بيانات حية؛ النتائج الاصطناعية لا تُرقّي شيئاً.
- 95% لا تُعتبر مثبتة إلا إذا كان الحد الأدنى لفاصل الثقة ≥ 95% على عينة كافية.
