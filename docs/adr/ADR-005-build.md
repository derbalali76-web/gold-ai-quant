# ADR-005: بناء APK بلا تكلفة

**الحالة:** مقبول — 2026-11-12

**السياق:** بيئة التطوير الحالية تمنع الوصول إلى dl.google.com و maven.google.com و repo.maven.apache.org و services.gradle.org
(رفض سياسة 403 مُتحقق منه)، فلا يمكن تنزيل Android SDK أو اعتماديات Gradle هنا.

**القرار:** يُبنى APK عبر GitHub Actions (`.github/workflows/android.yml`) أو محلياً عبر Android Studio بالأوامر في README.
يُرفع APK كـ artifact من سير العمل.

**العاقبة:** كود Android في P1 **لم يُترجم بعد** حتى يعمل سير العمل أو بناء محلي. هذا مذكور في قائمة المراحل.
