import os
import sys
import json
import subprocess
import signal
import time
import asyncio

# Add parent directory to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.append(PARENT_DIR)

from agents.spelling_ingester import SpellingIngester
from agents.auditor import Auditor

STATE_PATH = os.path.join(PARENT_DIR, "scratch", "agent_state.json")

def get_agent_status():
    """
    Reads the global orchestrator status.
    """
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"status": "unknown", "plan": []}

def setup_bot_handlers(bot):
    """
    Attaches handlers to the telebot instance.
    """
    
    @bot.message_handler(commands=['start', 'help'])
    def send_welcome(message):
        welcome_text = (
            "🤖 **Мультиагентна система керування словником**\n\n"
            "Я Telegram-бот для взаємодії з агентами та базою знань. Ось мої команди:\n\n"
            "⚙️ **Керування пайплайном:**\n"
            "/status - Отримати поточний стан системи та прогрес обробки\n"
            "/verify - Запустити Аудитора для перевірки бази знань\n"
            "/run    - Запустити повний цикл класифікації та зв'язків слів\n"
            "/stop   - Зупинити активні фонові процеси\n\n"
            "📝 **Імпорт нових слів:**\n"
            "Надішліть мені будь-який український текст. Я автоматично:\n"
            "1. Виправлю орфографічні помилки через ШІ.\n"
            "2. Перевірю наявність слів у SQL-базі.\n"
            "3. Згенерую відсутні словоформи через LLM та запишу їх у базу.\n"
            "4. Інкрементально запущу класифікацію та зв'язування для нових слів.\n"
            "5. Додам нотатки в Obsidian та завантажу їх в Neo4j."
        )
        bot.reply_to(message, welcome_text, parse_mode="Markdown")

    @bot.message_handler(commands=['status'])
    def show_status(message):
        status_data = get_agent_status()
        status = status_data.get("status", "idle").upper()
        error_msg = status_data.get("error_msg", "")
        
        report = f"📊 **Статус Головного агента**: `{status}`\n"
        if error_msg:
            report += f"❌ **Помилка**: `{error_msg}`\n"
            
        plan = status_data.get("plan", [])
        if plan:
            report += "\n📋 **План виконання кроків**:\n"
            for step in plan:
                icon = "⏳"
                if step["status"] == "completed":
                    icon = "✅"
                elif step["status"] == "running":
                    icon = "🚀"
                elif step["status"] == "failed":
                    icon = "❌"
                report += f"{icon} {step['id']}. {step['task']} - `{step['status']}`\n"
        
        bot.reply_to(message, report, parse_mode="Markdown")

    @bot.message_handler(commands=['run'])
    def run_pipeline(message):
        status_data = get_agent_status()
        if status_data.get("status") == "running":
            bot.reply_to(message, "⚠️ Пайплайн вже запущено та виконується.")
            return
            
        bot.reply_to(message, "🚀 Запускаю агентний пайплайн...")
        
        # Spawn run_agents.py as background process
        try:
            cmd = [sys.executable, os.path.join(PARENT_DIR, "run_agents.py")]
            # Start process in background
            p = subprocess.Popen(
                cmd,
                cwd=PARENT_DIR,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            # Give it a second to update status
            time.sleep(1.5)
            bot.reply_to(message, "✅ Пайплайн запущено у фоні. Ви можете перевірити статус за допомогою команди /status.")
        except Exception as e:
            bot.reply_to(message, f"❌ Не вдалося запустити процес: {e}")

    @bot.message_handler(commands=['stop'])
    def stop_pipeline(message):
        status_data = get_agent_status()
        if status_data.get("status") != "running":
            bot.reply_to(message, "ℹ️ Зараз немає запущених процесів класифікації.")
            return

        bot.reply_to(message, "🛑 Зупиняю фонові процеси...")
        
        # We can update status to halted to let orchestrator stop
        try:
            if os.path.exists(STATE_PATH):
                with open(STATE_PATH, "r", encoding="utf-8") as f:
                    state = json.load(f)
                state["status"] = "halted"
                state["error_msg"] = "Stopped by user via Telegram"
                with open(STATE_PATH, "w", encoding="utf-8") as f:
                    json.dump(state, f, ensure_ascii=False, indent=2)
            bot.reply_to(message, "✅ Процеси успішно зупинено.")
        except Exception as e:
            bot.reply_to(message, f"❌ Помилка при зупинці: {e}")

    @bot.message_handler(commands=['verify'])
    def run_verification(message):
        bot.reply_to(message, "🔍 Розпочинаю аудит бази знань. Зачекайте...")
        
        async def run_audit():
            auditor = Auditor()
            ok, err = await auditor.audit_all()
            if ok:
                bot.reply_to(message, "✅ **Аудит успішно завершено!**\n\nСтруктура SQL та граф Neo4j є цілісними, циклів чи сиріт не виявлено.")
            else:
                bot.reply_to(message, f"❌ **Виявлено критичні помилки аудиту!**\n\nДеталі:\n`{err}`\n\nРекомендовано перевірити дашборд для усунення проблем.")
                
        # Run async function in background
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_audit())

    @bot.message_handler(func=lambda message: True)
    def handle_text_import(message):
        text = message.text
        if text.startswith('/'):
            return # Skip commands if any fell through
            
        bot.reply_to(message, "📝 Отримано текст для імпорту. Розпочинаю обробку субагентом Ingester...")
        
        async def process_text():
            ingester = SpellingIngester()
            # Run text processing
            res = await ingester.process_user_text(text)
            if res.get("success"):
                reply = (
                    "✅ **Очищення та імпорт завершено!**\n\n"
                    f"✍️ **Виправлений текст:**\n_{res['corrected_text']}_\n\n"
                )
                added = res.get("added_words", [])
                if added:
                    reply += f"🆕 **Додано нових слів (та їхні форми):**\n- " + "\n- ".join(added)
                else:
                    reply += "ℹ️ Всі слова вже були присутні в словнику."
                    
                bot.reply_to(message, reply, parse_mode="Markdown")
                
                # Automatically trigger the incremental pipeline
                bot.send_message(message.chat.id, "🔄 Запускаю автоматичний інкрементальний пайплайн (Класифікація -> Зв'язки -> Obsidian -> Neo4j)...")
                
                cmd = [sys.executable, os.path.join(PARENT_DIR, "run_agents.py")]
                subprocess.Popen(cmd, cwd=PARENT_DIR)
                
            else:
                bot.reply_to(message, f"❌ **Помилка імпорту**: {res.get('error', 'невідомий збій')}")
                
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(process_text())
