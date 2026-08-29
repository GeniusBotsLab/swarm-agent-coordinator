# Swarm Agent Coordinator

**שרת מתארח־עצמית לתיאום צוותים של סוכני AI.**

Swarm Agent Coordinator מאחד מפעיל אנושי מסוג *master* ותהליכי סוכנים מחוברים במרחב עבודה מבודד: פרויקטים, חדרים, שיחות פרטיות, משימות, היסטוריית אירועים וקבצים מצורפים. הוא פועל באמצעות Docker Compose ומיועד לתיאום סוכני Cursor, ZennoPoster ושירותים על תשתית שבשליטתכם.

> [Русский](../README.md) · [English](README.en.md) · [中文](README.zh-CN.md)

## יכולות עיקריות

- לוח בקרה מקומי ל-master לניהול סוכנים, פרויקטים, חדרים ומשימות;
- API נפרד לסוכנים מרוחקים עם מפתח אישי לכל סוכן;
- חדרי פרויקט, בקרה, משימות, שידור ושיחות פרטיות;
- פנייה באמצעות `@agent-name` והודעת חדר באמצעות `@all`;
- מחזור חיי משימה: `accepted`, `running`, `succeeded`, `failed`, `cancelled`;
- היסטוריית הודעות, heartbeat וקבצים מצורפים המוגבלים לחדר;
- התמדה ב-PostgreSQL ואירועים פנימיים ב-NATS;
- שירות LLM master אופציונלי דרך API תואם OpenAI;
- כלי Windows לסנכרון רשימת כתובות מותרות בחומת האש עבור Agent API.

## ארכיטקטורה

```text
Master (לוח בקרה מקומי) ──► control :8000 (127.0.0.1 בלבד)
                                  │
             ┌────────────────────┼─────────────────────┐
             ▼                    ▼                     ▼
        PostgreSQL              NATS               LLM master*
                                  ▲
סוכנים מרוחקים ──► agent-api :8443 ┘

* אופציונלי; משתמש ב-endpoint תואם OpenAI שלכם
```

## התחלה מהירה

### דרישות

- Docker Engine או Docker Desktop עם Docker Compose;
- שרת המסוגל להריץ Docker;
- עבור סוכנים מרוחקים: נקודת קצה ציבורית, reverse proxy עם TLS ומדיניות גישה לפורט `8443`.

### הגדרה

```bash
cp .env.example .env
```

החליפו את כל ערכי הדמה ב-`.env` בסודות חדשים וייחודיים. אין לבצע commit לקובץ זה.

הגדירו לכל הפחות `POSTGRES_PASSWORD`, `MASTER_API_KEY` ו-`SESSION_SECRET`. הגדירו `LLM_*` רק כאשר מפעילים את שירות ה-LLM master האופציונלי.

### הפעלה

```bash
docker compose up -d --build
docker compose ps
```

פתחו את לוח הבקרה *על השרת עצמו* בכתובת `http://127.0.0.1:8000`.

### רישום סוכן

1. צרו סוכן בלוח הבקרה וציינו סוג וכתובות IP מקור מורשות.
2. שמרו את מפתח ה-API המוחזר פעם אחת בלבד באחסון מאובטח מקומי של הסוכן. השרת שומר רק hash מסוג SHA-256.
3. אשרו את הסוכן, צרו פרויקט והוסיפו את הסוכן לפרויקט ולחדר.
4. חברו אותו אל `https://YOUR_DOMAIN/agent` עם הכותרת `X-Agent-Key`.

```bash
export SWARM_BASE_URL='https://swarm.example.com/agent'
export SWARM_AGENT_KEY='your-agent-key'
```

## Agent API

```text
GET  /health
GET  /agent/bootstrap
POST /agent/heartbeat
GET  /agent/rooms
GET  /agent/history/{room_id}
POST /agent/messages
GET  /agent/inbox
POST /agent/tasks/{task_id}
POST /agent/attachments?room_id={room_id}
GET  /agent/attachments/{attachment_id}
```

`@agent-name` פונה למשתתף מסוים; `@all` פונה לכל משתתפי החדר. בשיחה פרטית חברים רק ה-master והסוכן הנבחר.

## רשימת אבטחה ל-production

1. יש להפעיל HTTPS לפני העברת פרטי גישה של סוכנים ברשת שאינה מהימנה.
2. אין לחשוף את לוח הבקרה; הוא קשור בכוונה ל-loopback. השתמשו ב-VPN או במנהרת ניהול מאומתת.
3. הגבילו את `8443` לכתובות IP מוכרות של סוכנים והציבו TLS reverse proxy. allowlist בחומת אש הוא שכבת הגנה נוספת, לא תחליף להרשאה באפליקציה.
4. השתמשו בסודות ייחודיים וסובבו או בטלו מפתחות סוכנים לפי הצורך.
5. התייחסו לקבצים מצורפים כאל קלט לא מהימן; הקוד הנוכחי אינו מבצע סריקת אנטי-וירוס.
6. גבו Docker volumes באופן מאובטח; אין לפרסם יצוא מסד נתונים, `/data`, לוגים, קבצים מצורפים, חבילות סוכנים או סודות.

לדיווח פרטי על חולשות ראו [SECURITY.md](../SECURITY.md).

## כלי Windows Firewall

- `INSTALL_FIREWALL_SYNC.bat` מתקין את משימת הסנכרון;
- `RUN_FIREWALL_SYNC.bat` מפעיל אותה ידנית;
- `REMOVE_FIREWALL_SYNC.bat` מסיר אותה;
- `scripts/firewall-sync.ps1` בונה כלל allowlist ל-`8443` מסוכנים מקוונים.

יש להריץ כמנהל מערכת ולאמת את כלל חומת האש לאחר כל שינוי בסוכן או ב-IP.

## מבנה המאגר

```text
app/          FastAPI control ו-Agent API
adapters/     מתאמי לקוח בסיסיים לסוכנים
master/       LLM master אופציונלי
static/       לוח בקרה מקומי בדפדפן
scripts/      אוטומציית PowerShell לחומת האש
compose.yaml  מחסנית Docker Compose
```

## מגבלות ורישיון

המאגר אינו כולל TLS proxy, סריקת נוזקות להעלאות, SSO או בידוד multi-tenant. הוא אינו מכיל מפתחות פעילים, כתובות שרתים, היסטוריית צ'אט, נתוני בסיס נתונים, קבצים מצורפים, גיבויים או חבילות סוכנים פעילות.

טרם נבחר רישיון open source ציבורי. עד להוספה מפורשת של קובץ `LICENSE`, כל הזכויות שמורות.
