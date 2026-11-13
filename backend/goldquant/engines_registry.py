"""Honest registry of every engine in MASTER PLAN + V2: what runs, what is disabled, and what it needs."""
from __future__ import annotations

ACTIVE, BASELINE, DISABLED, PLANNED = "ACTIVE", "ACTIVE_BASELINE", "DISABLED_NO_DATA", "PLANNED"

RESEARCH = "RESEARCH_ONLY"  # runs as a research report; does not change decisions until it proves value

ENGINES = [
    # name, status, phase, note_ar, data_required
    ("Data Quality / Freshness Gates", ACTIVE, "A", "يرفض السعر القديم والشموع التالفة والسوق المغلق وتعارض المصادر", "مزوّد سعر"),
    ("Live data: Twelve Data + xaus.com cross-check", BASELINE, "A", "مكتوب ومختبر بعقود offline؛ يحتاج فحصاً حياً على جهازك", "مفتاح مجاني"),
    ("Volatility Regime (V2 #6)", ACTIVE, "B", "اتجاه قوي / عرضي / تقلب مرتفع / استثنائي", "OHLC"),
    ("Probabilistic Path (V2 #9)", BASELINE, "B",
     "3 نتائج × 4 آفاق؛ لا يُعرض إلا إذا تفوق على climatology وتحققت المعايرة (لم يتأهل حتى الآن)", "OHLC"),
    ("Anti-Trade (V2 #18)", ACTIVE, "B", "بوابة رفض مستقلة؛ الانتظار هو الافتراضي", "مخرجات المحركات"),
    ("Model Drift Sentinel (V2 #11)", ACTIVE, "B", "PSI للميزات + Brier حي من سجل التداول الورقي", "سجل التوقعات"),
    ("Adversarial Critic (V2 #8)", BASELINE, "B", "أدلة معاكسة وفيتو قواعدي؛ ليس نموذجاً لغوياً", "OHLC"),
    ("Structural Break (V2 #14)", BASELINE, "B", "CUSUM على العوائد المعيارية", "OHLC"),
    ("Uncertainty Mapping (V2 #16)", ACTIVE, "B", "يفصل عدم يقين البيانات/النموذج/السوق", "—"),
    ("Liquidity Trap (V2 #3)", BASELINE, "C", "سحب القمم/القيعان، الاختراق الفاشل، الذيول الشاذة — استدلال من شكل السعر", "OHLC"),
    ("Cross-Market Divergence (V2 #5)", DISABLED, "C", "الكود جاهز ومختبر؛ يتطلب جلب XAG/USD وEUR/USD (رصيد Twelve Data إضافي)", "XAG/USD، EUR/USD"),
    ("Market Causality — Granger (V2 #1)", RESEARCH, "C", "أسبقية تنبؤية مع ثبات زمني؛ ليست سببية — /research/granger", "تاريخ حي + FRED"),
    ("Expectation Gap (V2 #2)", DISABLED, "C", "الكود جاهز؛ يتطلب consensus وactual في data/calendar.json", "إجماع التوقعات"),
    ("Priced-In Intelligence (V2 #15)", DISABLED, "C", "الكود جاهز؛ يتطلب ≥8 أحداث تاريخية بإجماع", "إجماع التوقعات"),
    ("Missing Reaction (V2 #13)", DISABLED, "C", "الكود جاهز؛ يتطلب ≥8 أحداث تاريخية بإجماع", "إجماع التوقعات"),
    ("Institutional Footprint — CFTC COT (V2 #4)", BASELINE, "D", "مراكز Managed Money بعد تاريخ النشر فقط؛ دليل سياقي (الوضع الحي)", "CFTC"),
    ("ETF flows (World Gold Council)", DISABLED, "D", "شروط إعادة الاستخدام غير مناسبة لجلب آلي", "—"),
    ("News Propagation (V2 #10)", BASELINE, "D", "RSS رسمية، إزالة التكرار، أول ناشر وزمن الانتشار، حظر 30 دقيقة", "RSS"),
    ("Economic Calendar embargo", BASELINE, "D", "تلقائي من bls.gov (iCal) و federalreserve.gov كل 6 ساعات + ملف يدوي اختياري؛ حظر من 60 دقيقة قبل الحدث إلى 45 بعده", "bls.gov + federalreserve.gov"),
    ("Macro context — FRED (MASTER #2)", BASELINE, "D", "العائد الحقيقي والاسمي والدولار مع تأخير نشر محافظ", "FRED"),
    ("Historical Analog (V2 #7)", BASELINE, "D", "أقرب 50 حالة سابقة؛ وصفي غير معاير", "OHLC"),
    ("Counterfactual (V2 #12)", BASELINE, "D", "احتمال الوصول للسعر الأفضل وتفويت الحركة؛ تكرار تاريخي", "OHLC"),
    ("Micro-Edge Discovery (V2 #17)", RESEARCH, "E", "تصحيح Benjamini-Hochberg + تأكيد في فترة لاحقة — /research/micro-edge", "OHLC"),
    ("Information Value (V2 #19)", RESEARCH, "E", "قيمة حدّية لكل مجموعة ميزات + خريطة التكرار — /research/info-value", "OHLC"),
    ("V3 Probability Calibration", RESEARCH, "V3", "Isotonic/Platt على نافذة معايرة مستقلة + ECE + Spiegelhalter؛ الأرقام تُعرض فقط عند النجاح على بيانات حية", "OHLC"),
    ("V3 Meta-Labeling", RESEARCH, "V3", "تعزيز تدرجي على توقعات أساسية خارج العينة؛ الهدف ربح بعد التكاليف", "OHLC"),
    ("V3 Selective Prediction + Frontier", RESEARCH, "V3", "عتبة من نافذة المعايرة فقط؛ منحنى الدقة/التغطية", "OHLC"),
    ("V3 Model Consensus", RESEARCH, "V3", "logit + gradient boosting + kNN؛ قياس الاختلاف", "OHLC"),
    ("V3 Mixture of Experts", RESEARCH, "V3", "خبير لكل حالة تقلب مع بديل عام", "OHLC"),
    ("V3 Dynamic Barrier Optimization", RESEARCH, "V3", "شبكة مسبقة للوقف/الهدف؛ الاختيار في نافذة المعايرة", "OHLC"),
    ("V3 Robustness + Promotion gate", ACTIVE, "V3", "لا يدخل الإنتاج إلا ما يثبت تفوقاً مستقراً على بيانات حية", "—"),
    ("V4 Data Quality Firewall", ACTIVE, "V4", "قفزات، تجمد، طوابع مستقبلية، تأخر الشموع، تعارض المصادر، أخبار مستقبلية", "—"),
    ("V4 Point-in-Time ledger", ACTIVE, "V4", "سجل إثبات أن كل مدخل كان متاحاً وقت القرار", "—"),
    ("V4 Independent Risk Governor", ACTIVE, "V4", "حدود يومية، تهدئة بعد الخسائر، هندسة الوقف، التكاليف", "سجل ورقي"),
    ("V4 AI Decision Court", ACTIVE, "V4", "الأدلة + الإحصاء + حارس المخاطر؛ إجماع مطلوب", "—"),
    ("V4 Decision Audit Trail", ACTIVE, "V4", "سلسلة تجزئة غير قابلة للتلاعب الصامت — /audit/verify", "—"),
    ("V4 Execution Reality Simulator", ACTIVE, "V4", "سبريد حسب الجلسة والتقلب، انزلاق، تأخر تنفيذ", "—"),
    ("V4 Uncertainty Budget", ACTIVE, "V4", "مكونات رقمية مقابل ميزانية ثابتة", "—"),
    ("V4 Governance & Rollback", ACTIVE, "V4", "سجل إصدارات، تراجع تلقائي، وضع أمان", "سجل ورقي"),
    ("V4 Shadow Tournament", ACTIVE, "V4", "تقييم أمامي حي للقواعد البديلة دون تأثير — /shadow", "الوضع الحي"),
    ("V4 Adversarial Market Testing", ACTIVE, "V4", "8 سيناريوهات عدائية؛ يجب ألا يصدر شراء/بيع — /research/adversarial", "—"),
    ("V4 Research Integrity", ACTIVE, "V4", "سجل التجارب، Deflated Sharpe، التسجيل المسبق", "—"),
    ("Dukascopy history importer", BASELINE, "V5", "سنوات من بيانات الدقيقة لـ XAU وXAG وEUR وJPY (مراجعة الشروط)", "Dukascopy"),
    ("Session clock + cross-asset features", RESEARCH, "V5", "مقارنة خارج العينة — /research/feature-upgrade؛ تدخل الإنتاج بالترقية فقط", "OHLC + أسواق مرتبطة"),
    ("Setup engine", RESEARCH, "V5", "اختراق لندن، Sweep-Reclaim، اندفاع افتتاح نيويورك — /research/setups", "OHLC"),
    ("ETF flows — GLD holdings", BASELINE, "V5", "تغير الأطنان اليومي المعلن؛ دليل سياقي", "spdrgoldshares.com"),
    ("Gold volatility — GVZ", BASELINE, "V5", "مؤشر تقلب الذهب المتوقع من FRED؛ دليل سياقي", "FRED GVZCLS"),
    ("Shanghai premium / own business data", DISABLED, "V5", "لا مصدر آلي مُتحقق؛ يمكن استيراد CSV يدوياً لاحقاً", "ملف المستخدم"),
    ("Cloud mode (Render + GitHub Actions)", ACTIVE, "V5", "تدريب في CI، تنبؤ فقط على الخادم المجاني", "مستودع خاص"),
    ("Support & Resistance Strength Engine", BASELINE, "UI", "قمم وقيعان مؤكدة × 3 أطر، مناطق، 7 خصائص، أوزان بتحقق متدرج؛ أرقام القوة فقط بعد التحقق — /research/levels", "OHLC"),
    ("Market Trend score (0-100)", ACTIVE, "UI", "M15/M30/H1/H4 مع التوافق والتقلب؛ درجة تحليلية لا احتمال", "OHLC"),
    ("Daily trend filter", ACTIVE, "V6", "يمنع إشارات الساعات المعاكسة لاتجاه 200 يوم وزخم 6 أشهر (فلتر رفض فقط)", "شموع يومية"),
    ("Multi-horizon outlook (WEEK / MONTH)", BASELINE, "V6", "قاعدة ثابتة لكل أفق؛ تقييم غير متداخل بعد التكاليف؛ شراء/بيع فقط بعد التحقق — /research/outlook", "شموع يومية"),
    ("Outlook forward log", ACTIVE, "V6", "سجل أمامي يومي لتوقعات الأسبوع والشهر ونتائجها الفعلية — /outlooks/track", "مستودع البيانات"),
    ("Backtester + Paper trading (F)", ACTIVE, "F", "walk-forward بتكاليف؛ holdout مسجّل؛ سجل ورقي — /research/backtest، /paper", "OHLC"),
]


def as_dicts() -> list[dict]:
    return [{"engine": n, "status": s, "phase": p, "note_ar": note, "data_required": d}
            for n, s, p, note, d in ENGINES]
