import streamlit as st
import os
import sys
import time
import json
import subprocess
import signal
import pandas as pd
import plotly.graph_objects as go

# Set page configurations
st.set_page_config(
    page_title="Word Abstraction Level Dashboard",
    page_icon="📝",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Paths relative to dashboard directory
DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPT_DIR = os.path.dirname(DASHBOARD_DIR)
if SCRIPT_DIR not in sys.path:
    sys.path.append(SCRIPT_DIR)
SCRATCH_DIR = os.path.join(SCRIPT_DIR, "scratch")
os.makedirs(SCRATCH_DIR, exist_ok=True)

# Load CSS Styles
styles_path = os.path.join(DASHBOARD_DIR, 'styles.css')
if os.path.exists(styles_path):
    with open(styles_path, 'r', encoding='utf-8') as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# Helper functions
@st.cache_data
def get_sql_word_count(file_path, mtime):
    if not os.path.exists(file_path):
        return 0
    count = 0
    try:
        with open(file_path, 'rb') as f:
            for line in f:
                line_stripped = line.lstrip()
                if line_stripped and line_stripped[0] == 40:  # ASCII for '('
                    line_stripped = line_stripped.rstrip()
                    if line_stripped and line_stripped[-1] in (41, 44, 59):  # ASCII for ')', ',', ';'
                        if len(line_stripped) > 2 and (line_stripped[-1] == 41 or line_stripped[-2] == 41):
                            count += 1
    except Exception:
        pass
    return count

@st.fragment(run_every=2.0)
def render_classification_progress_fragment(progress_file_path, log_file_path):
    # Read active progress
    progress_data = read_progress(progress_file_path) if os.path.exists(progress_file_path) else None
    
    words_processed_val = 0
    total_words_val = 0
    status_text_val = "Готовий до запуску"
    progress_pct = 0.0
    phase_val = "idle"
    
    if progress_data:
        phase_val = progress_data.get("phase", "idle")
        words_processed_val = progress_data.get("current", 0)
        total_words_val = progress_data.get("total", 0)
        status_text_val = progress_data.get("status", "Обробка...")
        
        if total_words_val and total_words_val > 0:
            progress_pct = min(float(words_processed_val) / float(total_words_val), 1.0)
            
        if phase_val == "done":
            progress_pct = 1.0
            status_text_val = "Успішно завершено!"
        elif phase_val == "error":
            status_text_val = progress_data.get("status", "Помилка виконання")
            
    col_left, col_right = st.columns([3, 2])
    with col_left:
        st.markdown("#### 📈 Прогрес виконання")
        
        # Determine status color pill
        status_pill_class = "status-pill status-pill-orange"
        if phase_val == "done":
            status_pill_class = "status-pill status-pill-green"
        elif phase_val == "error":
            status_pill_class = "status-pill status-pill-red"
        elif st.session_state.get("process_active", False):
            status_pill_class = "status-pill status-pill-blue"
            
        st.markdown(f"Статус: <span class='{status_pill_class}'>{status_text_val}</span>", unsafe_allow_html=True)
        st.progress(progress_pct)
        st.caption(f"Оброблено: {progress_pct*100:.1f}% ({words_processed_val:,} з {total_words_val:,})")
        
        # Time taken metrics
        if st.session_state.get("process_active", False) and st.session_state.get("process_start_time", None):
            elapsed = time.time() - st.session_state.process_start_time
            st.write(f"⏱️ Часу минуло: **{elapsed:.1f} сек**")
            
    with col_right:
        st.subheader("📋 Консольний лог виконання")
        
        logs = ""
        if os.path.exists(log_file_path):
            try:
                with open(log_file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    logs = "".join(lines[-150:])  # Last 150 lines
            except Exception:
                pass
        
        if logs:
            st.markdown(f"<div class='log-container'>{logs.replace(chr(10), '<br>')}</div>", unsafe_allow_html=True)
        else:
            st.info("Логи відсутні. Запустіть скрипт для отримання інформації.")

@st.fragment(run_every=2.0)
def render_relationship_progress_fragment(rel_progress_file_path, rel_log_file_path):
    # Read active progress
    rel_progress_data = read_progress(rel_progress_file_path) if os.path.exists(rel_progress_file_path) else None
    
    rel_words_processed_val = 0
    rel_total_words_val = 0
    rel_status_text_val = "Готовий до запуску"
    rel_progress_pct = 0.0
    rel_phase_val = "idle"
    
    if rel_progress_data:
        rel_phase_val = rel_progress_data.get("phase", "idle")
        rel_words_processed_val = rel_progress_data.get("current", 0)
        rel_total_words_val = rel_progress_data.get("total", 0)
        rel_status_text_val = rel_progress_data.get("status", "Обробка...")
        
        if rel_total_words_val and rel_total_words_val > 0:
            rel_progress_pct = min(float(rel_words_processed_val) / float(rel_total_words_val), 1.0)
            
        if rel_phase_val == "done":
            rel_progress_pct = 1.0
            rel_status_text_val = "Успішно завершено!"
        elif rel_phase_val == "error":
            rel_status_text_val = rel_progress_data.get("status", "Помилка виконання")
            
    col_rel_left, col_rel_right = st.columns([3, 2])
    with col_rel_left:
        st.markdown("#### 📈 Прогрес виконання")
        
        # Determine status color pill
        rel_status_pill_class = "status-pill status-pill-orange"
        if rel_phase_val == "done":
            rel_status_pill_class = "status-pill status-pill-green"
        elif rel_phase_val == "error":
            rel_status_pill_class = "status-pill status-pill-red"
        elif st.session_state.get("rel_process_active", False):
            rel_status_pill_class = "status-pill status-pill-blue"
            
        st.markdown(f"Статус: <span class='{rel_status_pill_class}'>{rel_status_text_val}</span>", unsafe_allow_html=True)
        st.progress(rel_progress_pct)
        
        if rel_phase_val == "mapping":
            st.caption(f"Крок зв'язування рівнів: {rel_words_processed_val} з {rel_total_words_val} рівнів")
        elif rel_phase_val == "write":
            st.caption(f"Перезапис SQL: {rel_progress_pct*100:.1f}% ({rel_words_processed_val:,} з {rel_total_words_val:,} слів)")
        else:
            st.caption(f"Прогрес: {rel_progress_pct*100:.1f}%")
            
        # Time taken metrics
        if st.session_state.get("rel_process_active", False) and st.session_state.get("rel_process_start_time", None):
            elapsed = time.time() - st.session_state.rel_process_start_time
            st.write(f"⏱️ Часу минуло: **{elapsed:.1f} сек**")
            
    with col_rel_right:
        st.subheader("📋 Консольний лог виконання зв'язків")
        
        rel_logs = ""
        if os.path.exists(rel_log_file_path):
            try:
                with open(rel_log_file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    rel_logs = "".join(lines[-150:])  # Last 150 lines
            except Exception:
                pass
        
        if rel_logs:
            st.markdown(f"<div class='log-container'>{rel_logs.replace(chr(10), '<br>')}</div>", unsafe_allow_html=True)
        else:
            st.info("Логи відсутні. Запустіть скрипт для отримання інформації.")

def is_process_running(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

def load_cache_data(cache_path):
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def read_progress(progress_file):
    if os.path.exists(progress_file):
        try:
            with open(progress_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None

def check_neo4j_connection():
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "password")
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
        driver.close()
        return True, "Підключено"
    except ImportError:
        return False, "Драйвер neo4j не встановлено"
    except Exception as e:
        return False, f"Помилка з'єднання: {str(e)[:100]}"

def check_telegram_bot_status():
    pid_file = os.path.join(SCRATCH_DIR, "telegram_bot.pid")
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r") as f:
                pid = int(f.read().strip())
            if is_process_running(pid):
                return True, pid
        except:
            pass
    return False, None

# Sidebar Configuration
st.sidebar.markdown("### 📝 Word Classifier GUI")
st.sidebar.caption("Панель керування та аналітики")
st.sidebar.markdown("---")

st.sidebar.markdown("#### ⚙️ Файлові шляхи")

# Detect SQL files in base_of_word
base_of_word_dir = os.path.join(SCRIPT_DIR, "base_of_word")
sql_files = ["Word.v.10.sql", "test_words.sql"]
if os.path.exists(base_of_word_dir):
    detected = [f for f in os.listdir(base_of_word_dir) if f.endswith(".sql") and "level" not in f]
    for d in detected:
        if d not in sql_files:
            sql_files.append(d)

selected_input_file = st.sidebar.selectbox(
    "Вхідний SQL дамп",
    options=sql_files,
    index=0
)
input_sql_path = os.path.join(base_of_word_dir, selected_input_file)

# Default output file naming
default_output_file = selected_input_file.replace(".sql", ".level.sql")
output_sql_name = st.sidebar.text_input("Назва вихідного SQL файлу", value=default_output_file)
output_sql_path = os.path.join(base_of_word_dir, output_sql_name)

cache_file_name = st.sidebar.text_input("Файл кешу (JSON)", value="classification_cache.json")
cache_path = os.path.join(SCRIPT_DIR, cache_file_name)

st.sidebar.markdown("---")
st.sidebar.markdown("#### 🤖 Налаштування ШІ")

api_type = st.sidebar.selectbox(
    "Провайдер API",
    options=["gemini", "openai", "ollama", "rotator"],
    index=0
)

# Suggested model names based on provider
model_defaults = {
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4o-mini",
    "ollama": "qwen2.5-coder:14b",
    "rotator": "groq"
}

model_name = st.sidebar.text_input(
    "Модель (Model Name)", 
    value=model_defaults[api_type],
    help="Введіть конкретну назву моделі для обраного провайдера."
)

api_key = ""
if api_type in ["gemini", "openai"]:
    api_key = st.sidebar.text_input(
        "API Key (опціонально)", 
        type="password", 
        help="Якщо залишити порожнім, буде використано змінну оточення GEMINI_API_KEY або OPENAI_API_KEY."
    )

heuristics_only = st.sidebar.checkbox(
    "Тільки евристики",
    value=False,
    help="Використовувати виключно вбудовані правила та кеш, без звернення до ШІ."
)

st.sidebar.markdown("---")
st.sidebar.markdown("#### ⏱️ Обмеження та батчі")
limit_rows = st.sidebar.number_input(
    "Ліміт оброблених слів (0 - без ліміту)", 
    min_value=0, 
    value=0, 
    step=100,
    help="Корисно для тестування (наприклад, обробити лише перші 1000 слів)."
)
limit_val = limit_rows if limit_rows > 0 else None

st.sidebar.markdown("---")
st.sidebar.caption("© 2026 Abstraction Classifier GUI")

# Main Header
st.markdown("<h1 class='main-title'>📊 Класифікатор рівнів абстракції слів</h1>", unsafe_allow_html=True)
st.markdown("<div class='subtitle'>Інтерактивний кабінет для керування семантичним аналізом та структуруванням словникової бази</div>", unsafe_allow_html=True)

# Check state of running process
if "process_active" not in st.session_state:
    st.session_state.process_active = False
    st.session_state.process_pid = None
    st.session_state.process_start_time = None

if st.session_state.process_active and st.session_state.process_pid:
    if not is_process_running(st.session_state.process_pid):
        st.session_state.process_active = False
        st.session_state.process_pid = None

# Check state of running relationship process
if "rel_process_active" not in st.session_state:
    st.session_state.rel_process_active = False
    st.session_state.rel_process_pid = None
    st.session_state.rel_process_start_time = None

if st.session_state.rel_process_active and st.session_state.rel_process_pid:
    if not is_process_running(st.session_state.rel_process_pid):
        st.session_state.rel_process_active = False
        st.session_state.rel_process_pid = None

# Initialize logs and progress files
log_file_path = os.path.join(SCRATCH_DIR, "classification_run.log")
progress_file_path = os.path.join(SCRATCH_DIR, "classification_progress.json")

rel_log_file_path = os.path.join(SCRATCH_DIR, "relationship_run.log")
rel_progress_file_path = os.path.join(SCRATCH_DIR, "relationship_progress.json")
rel_cache_path = os.path.join(SCRIPT_DIR, "relationship_cache.json")

# Load current Cache data
cache_data = load_cache_data(cache_path)
cache_size = len(cache_data)

# Word relationship metrics
relationship_sql_path = output_sql_path.replace(".sql", ".relationship.sql")
level_mtime = os.path.getmtime(output_sql_path) if os.path.exists(output_sql_path) else 0
rel_mtime = os.path.getmtime(relationship_sql_path) if os.path.exists(relationship_sql_path) else 0
input_mtime = os.path.getmtime(input_sql_path) if os.path.exists(input_sql_path) else 0

# Progress data read
progress_data = read_progress(progress_file_path) if os.path.exists(progress_file_path) else None
rel_progress_data = read_progress(rel_progress_file_path) if os.path.exists(rel_progress_file_path) else None

# Calculate input file total count (cached)
input_words_count = get_sql_word_count(input_sql_path, input_mtime)

# Calculate level words processed
if st.session_state.process_active and progress_data:
    words_processed_val = progress_data.get("current", 0)
    total_words_val = progress_data.get("total", input_words_count)
    total_level_words = words_processed_val
else:
    total_level_words = get_sql_word_count(output_sql_path, level_mtime)
    words_processed_val = total_level_words
    total_words_val = input_words_count

# Calculate relationship words processed
if st.session_state.rel_process_active and rel_progress_data:
    total_rel_words = rel_progress_data.get("current", 0)
else:
    total_rel_words = get_sql_word_count(relationship_sql_path, rel_mtime)

words_to_process = max(0, total_level_words - total_rel_words)

# Rel cache metrics
rel_cache_data = load_cache_data(rel_cache_path)
lemmas_mapped = len(rel_cache_data)

# Columns for Metric Cards
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric(label="Розмір бази (слів)", value=f"{total_words_val:,}" if isinstance(total_words_val, int) else total_words_val)
with col2:
    st.metric(label="Оброблено слів", value=f"{words_processed_val:,}")
with col3:
    st.metric(label="Збережено лемм у кеші", value=f"{cache_size:,}")
with col4:
    active_llm_label = "ЕВРИСТИКИ" if heuristics_only else f"{api_type.upper()} ({model_name})"
    st.metric(label="Поточний режим ШІ", value=active_llm_label)

st.markdown("---")

tab_agents, tab_import, tab_run, tab_relationship, tab_explorer, tab_analytics = st.tabs(["🤖 Агентне керування", "📝 Імпорт тексту", "🚀 Класифікація слів", "🔗 Зв'язування рівнів", "🔍 Перегляд Кешу", "📊 Аналітика"])

with tab_agents:
    st.subheader("🤖 Мультиагентна система (Orchestrator)")
    
    # Check statuses
    import asyncio
    neo4j_ok, neo4j_status = check_neo4j_connection()
    tg_ok, tg_pid = check_telegram_bot_status()
    
    col_status1, col_status2 = st.columns(2)
    with col_status1:
        neo4j_color = "green" if neo4j_ok else "red"
        st.markdown(f"**Neo4j Database:** :{neo4j_color}[{neo4j_status}]")
    with col_status2:
        tg_status_text = f"Запущено (PID: {tg_pid})" if tg_ok else "Вимкнено"
        tg_color = "green" if tg_ok else "red"
        st.markdown(f"**Telegram Bot Daemon:** :{tg_color}[{tg_status_text}]")
        
        # Bot control buttons
        btn_bot1, btn_bot2 = st.columns(2)
        with btn_bot1:
            if st.button("▶️ Запустити Telegram бота", disabled=tg_ok, use_container_width=True):
                try:
                    cmd = [sys.executable, os.path.join(SCRIPT_DIR, "run_telegram_bot.py")]
                    p = subprocess.Popen(cmd, cwd=SCRIPT_DIR)
                    pid_file = os.path.join(SCRATCH_DIR, "telegram_bot.pid")
                    with open(pid_file, "w") as f:
                        f.write(str(p.pid))
                    time.sleep(1.0)
                    st.rerun()
                except Exception as e:
                    st.error(f"Помилка запуску бота: {e}")
        with btn_bot2:
            if st.button("⏹️ Зупинити Telegram бота", disabled=not tg_ok, use_container_width=True):
                try:
                    os.kill(tg_pid, signal.SIGTERM)
                    time.sleep(1.0)
                    if is_process_running(tg_pid):
                        os.kill(tg_pid, signal.SIGKILL)
                    pid_file = os.path.join(SCRATCH_DIR, "telegram_bot.pid")
                    if os.path.exists(pid_file):
                        os.remove(pid_file)
                    st.rerun()
                except Exception as e:
                    st.error(f"Помилка зупинки бота: {e}")

    st.markdown("---")
    
    # Load agent state
    state_file = os.path.join(SCRATCH_DIR, "agent_state.json")
    agent_state = {}
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                agent_state = json.load(f)
        except:
            pass
            
    agent_status = agent_state.get("status", "idle").upper()
    
    # State display
    col_ag1, col_ag2 = st.columns([3, 1])
    with col_ag1:
        st.markdown(f"#### Поточний стан Оркестратора: `{agent_status}`")
        if agent_state.get("error_msg"):
            st.error(f"⚠️ Пайплайн зупинено розробником через помилку: {agent_state['error_msg']}")
    with col_ag2:
        is_running = agent_state.get("status") == "running"
        
        btn_pipe1, btn_pipe2 = st.columns(2)
        with btn_pipe1:
            if st.button("🚀 Запустити", disabled=is_running, type="primary", use_container_width=True):
                try:
                    cmd = [sys.executable, os.path.join(SCRIPT_DIR, "run_agents.py")]
                    subprocess.Popen(cmd, cwd=SCRIPT_DIR)
                    time.sleep(1.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"Помилка: {e}")
        with btn_pipe2:
            if st.button("🛑 Зупинити", disabled=not is_running, type="secondary", use_container_width=True):
                try:
                    agent_state["status"] = "halted"
                    agent_state["error_msg"] = "Stopped by user via dashboard"
                    with open(state_file, "w", encoding="utf-8") as f:
                        json.dump(agent_state, f, ensure_ascii=False, indent=2)
                    st.rerun()
                except Exception as e:
                    st.error(f"Помилка: {e}")

    # Steps progress table
    plan_steps = agent_state.get("plan", [])
    if plan_steps:
        st.markdown("##### 📋 План виконання субагентів")
        step_data = []
        for step in plan_steps:
            icon = "⏳ Очікує"
            if step["status"] == "completed":
                icon = "✅ Завершено"
            elif step["status"] == "running":
                icon = "🚀 Виконується"
            elif step["status"] == "failed":
                icon = "❌ Помилка"
                
            step_data.append({
                "ID": step["id"],
                "Завдання (Субагент)": step["task"],
                "Статус": icon,
                "Деталі помилки": step.get("error", "-")
            })
        st.dataframe(pd.DataFrame(step_data), use_container_width=True, hide_index=True)
    else:
        st.info("План агентів ще не згенеровано. Натисніть кнопку 'Запустити' для ініціалізації.")

with tab_import:
    st.subheader("📝 Імпорт та виправлення тексту")
    st.markdown("Введіть сирий текст українською мовою. Система виправить помилки через ШІ, порівняє слова з базою даних, автоматично згенерує парадигми словоформ для нових слів та ініціює інкрементальний пайплайн обробки.")
    
    user_text = st.text_area("Введіть текст для обробки:", height=150)
    
    if st.button("🚀 Обробити та імпортувати", type="primary"):
        if not user_text.strip():
            st.warning("Будь ласка, введіть текст.")
        else:
            with st.spinner("Агент Ingester перевіряє орфографію та імпортує нові слова..."):
                from agents.spelling_ingester import SpellingIngester
                ingester = SpellingIngester()
                
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                res = loop.run_until_complete(ingester.process_user_text(user_text.strip()))
                
                if res.get("success"):
                    st.success("Обробку та імпорт завершено!")
                    st.markdown(f"**Виправлений текст:**\n_{res['corrected_text']}_")
                    
                    added = res.get("added_words", [])
                    if added:
                        st.info(f"🆕 **Додано нових слів (та їхні форми):**")
                        for w in added:
                            st.write(f"- {w}")
                        
                        st.info("🔄 Запущено автоматичний інкрементальний пайплайн (Класифікація -> Зв'язки -> Obsidian -> Neo4j)...")
                        cmd = [sys.executable, os.path.join(SCRIPT_DIR, "run_agents.py")]
                        subprocess.Popen(cmd, cwd=SCRIPT_DIR)
                    else:
                        st.info("Всі слова з тексту вже були присутні в словнику.")
                else:
                    st.error(f"Помилка імпорту: {res.get('error')}")

with tab_run:
    st.subheader("⚙️ Керування фоновим процесом")
    
    # Action Buttons (outside fragment to avoid losing state/focus)
    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        start_btn_disabled = st.session_state.process_active
        if st.button("🚀 Запустити класифікацію", use_container_width=True, type="primary", disabled=start_btn_disabled):
            # Clean up old progress file
            if os.path.exists(progress_file_path):
                try:
                    os.remove(progress_file_path)
                except:
                    pass
            
            # Write initial start file log
            with open(log_file_path, "w", encoding="utf-8") as f:
                f.write(f"=== [СТАРТ КЛАСИФІКАЦІЇ: {time.strftime('%Y-%m-%d %H:%M:%S')}] ===\n")
                f.write(f"Вхідний файл: {input_sql_path}\n")
                f.write(f"Вихідний файл: {output_sql_path}\n")
                f.write(f"Режим ШІ: {active_llm_label}\n")
                f.write(f"--------------------------------------------------\n\n")

            # Prepare Command Line Args
            cmd = [
                sys.executable,
                os.path.join(SCRIPT_DIR, "classify_words.py"),
                "--input", input_sql_path,
                "--output", output_sql_path,
                "--cache", cache_path,
                "--api-type", api_type,
                "--progress-file", progress_file_path
            ]
            if heuristics_only:
                cmd.append("--heuristics-only")
            if api_key:
                cmd.extend(["--api-key", api_key])
            if model_name:
                cmd.extend(["--model", model_name])
            if limit_val:
                cmd.extend(["--limit", str(limit_val)])
            
            # Spawn background process
            log_file = open(log_file_path, "a", encoding="utf-8")
            p = subprocess.Popen(
                cmd,
                cwd=SCRIPT_DIR,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True
            )
            
            st.session_state.process_pid = p.pid
            st.session_state.process_active = True
            st.session_state.process_start_time = time.time()
            st.rerun()

    with btn_col2:
        stop_btn_disabled = not st.session_state.process_active
        if st.button("🛑 Зупинити процес", use_container_width=True, type="secondary", disabled=stop_btn_disabled):
            if st.session_state.process_pid:
                try:
                    os.kill(st.session_state.process_pid, signal.SIGTERM)
                    time.sleep(1.0)
                    if is_process_running(st.session_state.process_pid):
                        os.kill(st.session_state.process_pid, signal.SIGKILL)
                    
                    with open(log_file_path, "a", encoding="utf-8") as f:
                        f.write("\n🛑 Процес примусово зупинено користувачем.\n")
                except Exception as e:
                    st.error(f"Помилка при зупинці процесу: {e}")
                
                st.session_state.process_active = False
                st.session_state.process_pid = None
                st.rerun()
    
    st.markdown("---")
    
    # Progress & Log Fragment (updates every 2 seconds without full page reload)
    render_classification_progress_fragment(progress_file_path, log_file_path)

with tab_relationship:
    st.subheader("🔗 Зв'язування рівнів абстракції слів")
    st.markdown("Цей інструмент логічно пов'язує слова різних рівнів абстракції (від 10 вниз до 1) та створює новий SQL-файл із збереженими зв'язками.")
    
    # Metrics Row
    rel_col1, rel_col2, rel_col3, rel_col4 = st.columns(4)
    with rel_col1:
        st.metric(label="Слів у Word.v.10.level.sql", value=f"{total_level_words:,}")
    with rel_col2:
        st.metric(label="Слів у Word.v.10.level.relationship.sql", value=f"{total_rel_words:,}")
    with rel_col3:
        st.metric(label="Необхідно обробити (різниця)", value=f"{words_to_process:,}")
    with rel_col4:
        st.metric(label="Унікальних лемм у кеші зв'язків", value=f"{lemmas_mapped:,}")
        
    st.markdown("---")
    
    st.subheader("⚙️ Керування фоновим процесом зв'язків")
    st.markdown(f"**Вхідний файл:** `{output_sql_path}` | **Вихідний файл:** `{relationship_sql_path}` | **Файл кешу:** `{rel_cache_path}`")
    
    # Action Buttons (outside fragment to avoid losing state/focus)
    btn_rel_col1, btn_rel_col2 = st.columns(2)
    with btn_rel_col1:
        rel_start_btn_disabled = st.session_state.rel_process_active
        if st.button("🚀 Запустити зв'язування", use_container_width=True, type="primary", disabled=rel_start_btn_disabled):
            # Clean up old progress file
            if os.path.exists(rel_progress_file_path):
                try:
                    os.remove(rel_progress_file_path)
                except:
                    pass
            
            # Write initial start file log
            with open(rel_log_file_path, "w", encoding="utf-8") as f:
                f.write(f"=== [СТАРТ ЗВ'ЯЗУВАННЯ: {time.strftime('%Y-%m-%d %H:%M:%S')}] ===\n")
                f.write(f"Вхідний файл: {output_sql_path}\n")
                f.write(f"Вихідний файл: {relationship_sql_path}\n")
                f.write(f"Режим ШІ: {active_llm_label}\n")
                f.write(f"--------------------------------------------------\n\n")

            # Prepare Command Line Args
            cmd = [
                sys.executable,
                os.path.join(SCRIPT_DIR, "word_relationship.py"),
                "--input", output_sql_path,
                "--output", relationship_sql_path,
                "--cache", rel_cache_path,
                "--api-type", api_type,
                "--progress-file", rel_progress_file_path
            ]
            if api_key:
                cmd.extend(["--api-key", api_key])
            if model_name:
                cmd.extend(["--model", model_name])
            if limit_val:
                cmd.extend(["--limit", str(limit_val)])
            
            # Spawn background process
            log_file = open(rel_log_file_path, "a", encoding="utf-8")
            p = subprocess.Popen(
                cmd,
                cwd=SCRIPT_DIR,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True
            )
            
            st.session_state.rel_process_pid = p.pid
            st.session_state.rel_process_active = True
            st.session_state.rel_process_start_time = time.time()
            st.rerun()

    with btn_rel_col2:
        rel_stop_btn_disabled = not st.session_state.rel_process_active
        if st.button("🛑 Зупинити зв'язування", use_container_width=True, type="secondary", disabled=rel_stop_btn_disabled):
            if st.session_state.rel_process_pid:
                try:
                    os.kill(st.session_state.rel_process_pid, signal.SIGTERM)
                    time.sleep(1.0)
                    if is_process_running(st.session_state.rel_process_pid):
                        os.kill(st.session_state.rel_process_pid, signal.SIGKILL)
                    
                    with open(rel_log_file_path, "a", encoding="utf-8") as f:
                        f.write("\n🛑 Процес примусово зупинено користувачем.\n")
                except Exception as e:
                    st.error(f"Помилка при зупинці процесу: {e}")
                
                st.session_state.rel_process_active = False
                st.session_state.rel_process_pid = None
                st.rerun()
    
    st.markdown("---")
    
    # Progress & Log Fragment (updates every 2 seconds without full page reload)
    render_relationship_progress_fragment(rel_progress_file_path, rel_log_file_path)


with tab_explorer:
    st.subheader("🔍 Пошук по локальному кешу класифікацій")
    st.markdown("Ви можете переглянути слова, які вже мають визначений рівень абстракції, та змінити/перевірити їх.")
    
    if cache_data:
        search_query = st.text_input("Введіть лемму для пошуку (код або слово):", "").strip().lower()
        
        # Prepare list for table representation
        rows = [{"Код лемми (main_form_code)": k, "Рівень абстракції": v} for k, v in cache_data.items()]
        df = pd.DataFrame(rows)
        
        if search_query:
            filtered_df = df[df["Код лемми (main_form_code)"].str.lower().str.contains(search_query)]
            st.dataframe(filtered_df, use_container_width=True)
            st.caption(f"Знайдено збігів: {len(filtered_df)}")
        else:
            st.dataframe(df.head(100), use_container_width=True)
            st.caption("Показуємо перші 100 лемм з кешу. Використайте пошуковий рядок вище для детального пошуку.")
    else:
        st.info("Кеш порожній або файл кешу не знайдено. Запустіть класифікацію для наповнення кешу.")

with tab_analytics:
    st.subheader("📊 Розподіл рівнів абстракції")
    st.markdown("Візуальний розподіл класифікованих лемм з файлу кешу за шкалою абстракції (від 1 до 10).")
    
    if cache_data:
        levels = list(cache_data.values())
        level_counts = {i: levels.count(i) for i in range(1, 11)}
        
        levels_desc = {
            10: "10. Абсолют (Буття)",
            9: "9. Сутність (Концепт)",
            8: "8. Матеріальність (Тіло)",
            7: "7. Походження (Генезис)",
            6: "6. Призначення (Роль)",
            5: "5. Категорія (Кластер)",
            4: "4. Рід (Гіперонім)",
            3: "3. Вид (Гіпонім)",
            2: "2. Модель (Варіація)",
            1: "1. Одиниця (Індивід)"
        }
        
        # Plotly chart configuration in Macha Tea theme colors
        x_data = [levels_desc[i] for i in range(1, 11)]
        y_data = [level_counts[i] for i in range(1, 11)]
        
        fig = go.Figure(data=[
            go.Bar(
                x=x_data,
                y=y_data,
                marker=dict(
                    color='#87A96B', # Matcha green accent
                    line=dict(color='#4B6B40', width=1.5) # Forest green outline
                ),
                hovertemplate='%{x}<br>Кількість: %{y} лемм<extra></extra>'
            )
        ])
        
        fig.update_layout(
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            xaxis=dict(
                gridcolor='rgba(135, 169, 107, 0.1)',
                tickfont=dict(size=11)
            ),
            yaxis=dict(
                gridcolor='rgba(135, 169, 107, 0.1)',
                title="Кількість слів у кеші"
            ),
            margin=dict(l=40, r=20, t=20, b=40),
            height=400
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
        # Display numerical table
        st.markdown("#### Детальні статистичні дані")
        stat_rows = []
        for i in reversed(range(1, 11)):
            stat_rows.append({
                "Рівень абстракції": levels_desc[i],
                "Кількість лемм у кеші": level_counts[i],
                "Відсоток від загального кешу": f"{(level_counts[i]/cache_size)*100:.2f}%" if cache_size > 0 else "0%"
            })
        st.table(pd.DataFrame(stat_rows))
        
    else:
        st.info("Немає даних для побудови графіків. Будь ласка, запустіть класифікацію для наповнення кешу.")
