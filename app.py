import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sqlite3
import io
import os

# --- 0. 安全与配置 ---
st.set_page_config(page_title="NP Clinical Assistant", layout="wide", page_icon="👩‍⚕️")

# 简单密码保护 (数据安全第一道防线)
# 默认密码是 1234，你可以自己改
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False

    if st.session_state.password_correct:
        return True

    st.title("🔒 系统登录")
    pwd = st.text_input("请输入密码 (Password)", type="password")
    if st.button("登录"):
        if pwd == "1213":  # <--- 在这里修改密码
            st.session_state.password_correct = True
            st.rerun()
        else:
            st.error("密码错误")
    return False

if not check_password():
    st.stop()

# --- 1. 数据库设置 ---
def get_db_connection():
    conn = sqlite3.connect('np_reminder.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    # 确保表格存在
    c.execute('''CREATE TABLE IF NOT EXISTS patients
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, dob TEXT, nursing_home TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS task_types
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, default_intervals TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS reminders
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id INTEGER, task_name TEXT, 
                  start_date TEXT, interval TEXT, due_date TEXT, status TEXT, notes TEXT)''')
    
    # 预设数据 (如果任务类型为空则填充)
    c.execute("SELECT count(*) FROM task_types")
    if c.fetchone()[0] == 0:
        defaults = [
            ("Blood check", "1 month,3 months,6 months,12 months"),
            ("Antibiotics post treatment", "3 days,5 days,7 days,14 days,30 days"),
            ("Routine review", "Monthly"),
            ("Medication review", "3 Monthly"),
            ("Diabetes review", "3 Monthly"),
            ("Wounds review", "Weekly,Monthly"),
            ("Medication changes review", "2 weeks")
        ]
        c.executemany("INSERT INTO task_types (name, default_intervals) VALUES (?, ?)", defaults)
        conn.commit()
    return conn

conn = init_db()

# --- 2. 核心逻辑 ---
def calculate_due_date(start_date, interval_str):
    start = pd.to_datetime(start_date)
    i_str = str(interval_str).lower().strip()
    try:
        if "monthly" in i_str:
            nums = [int(s) for s in i_str.split() if s.isdigit()]
            months = nums[0] if nums else 1
            return (start + pd.DateOffset(months=months)).date()
        elif "month" in i_str:
            nums = [int(s) for s in i_str.split() if s.isdigit()]
            months = nums[0] if nums else 1
            return (start + pd.DateOffset(months=months)).date()
        elif "week" in i_str:
            nums = [int(s) for s in i_str.split() if s.isdigit()]
            weeks = nums[0] if nums else 1
            return (start + timedelta(weeks=weeks)).date()
        elif "day" in i_str:
            nums = [int(s) for s in i_str.split() if s.isdigit()]
            days = nums[0] if nums else 1
            return (start + timedelta(days=days)).date()
        else:
            return start.date()
    except:
        return start.date()

def get_next_stage_interval(task_name, current_interval):
    try:
        df = pd.read_sql_query("SELECT default_intervals FROM task_types WHERE name = ?", conn, params=(task_name,))
        if df.empty: return None
        intervals = [x.strip().lower() for x in df.iloc[0]['default_intervals'].split(',')]
        curr = current_interval.strip().lower()
        if curr in intervals:
            idx = intervals.index(curr)
            if idx + 1 < len(intervals):
                return df.iloc[0]['default_intervals'].split(',')[idx+1].strip()
        return None
    except:
        return None

# --- 3. 导航与页面 ---
if 'page' not in st.session_state: st.session_state.page = "Dashboard"
if 'prefill_task' not in st.session_state: st.session_state.prefill_task = None

st.sidebar.title("👩‍⚕️ NP Assistant")
st.sidebar.markdown(f"User: **NP Admin**")
st.sidebar.markdown("---")

def nav(p): st.session_state.page = p; st.session_state.prefill_task = None if p != "New Task" else st.session_state.prefill_task

st.sidebar.button("📊 仪表盘 (Dashboard)", on_click=nav, args=("Dashboard",), use_container_width=True)
st.sidebar.button("➕ 新建提醒 (New Task)", on_click=nav, args=("New Task",), use_container_width=True)
st.sidebar.button("👤 病人管理 (Patients)", on_click=nav, args=("Patients",), use_container_width=True)
st.sidebar.button("📂 Excel 备份", on_click=nav, args=("Excel",), use_container_width=True)
st.sidebar.markdown("---")
st.sidebar.button("⚙️ 系统设置 (Reset)", on_click=nav, args=("Settings",), use_container_width=True)

# ================= DASHBOARD =================
if st.session_state.page == "Dashboard":
    st.title("📅 待办事项看板")
    
    # 获取数据
    df = pd.read_sql_query("""
        SELECT r.id, p.name, p.nursing_home, r.task_name, r.interval, r.due_date, r.notes, r.patient_id
        FROM reminders r
        LEFT JOIN patients p ON r.patient_id = p.id
        WHERE r.status = 'Pending'
    """, conn)
    
    if df.empty:
        st.info("👋 暂无待办任务。请去新建任务。")
    else:
        df['due_date'] = pd.to_datetime(df['due_date']).dt.date
        today = datetime.now().date()
        
        # 顶部选项
        col1, col2 = st.columns([1, 4])
        show_all = col1.checkbox("显示所有任务", value=True)
        
        # 筛选与排序
        if not show_all:
            df = df[df['due_date'] <= today + timedelta(days=7)]
        
        df = df.sort_values(by=['nursing_home', 'due_date'])
        
        # 统计
        n_overdue = len(df[df['due_date'] < today])
        n_urgent = len(df[(df['due_date'] >= today) & (df['due_date'] <= today + timedelta(days=3))])
        col2.markdown(f"🔴 逾期: **{n_overdue}** | 🟠 紧急(3天内): **{n_urgent}**")
        
        # 分组展示
        df['nursing_home'] = df['nursing_home'].fillna("未分类")
        homes = df['nursing_home'].unique()
        
        for home in homes:
            st.markdown(f"### 🏥 {home}")
            home_tasks = df[df['nursing_home'] == home]
            
            for _, row in home_tasks.iterrows():
                # --- 颜色逻辑 ---
                days_left = (row['due_date'] - today).days
                
                if days_left < 0:
                    status_color = "🔴" # 逾期
                    bg_msg = f"已逾期 {abs(days_left)} 天!"
                elif days_left <= 3:
                    status_color = "🟠" # 紧急
                    bg_msg = f"剩 {days_left} 天"
                else:
                    status_color = "🟢" # 安全
                    bg_msg = "远期规划"
                
                # 卡片标题
                card_title = f"{status_color} **{row['name']}** - {row['task_name']} ({row['interval']})"
                
                with st.expander(card_title):
                    st.caption(f"截止: **{row['due_date']}** | 状态: {bg_msg}")
                    if row['notes']: st.info(f"备注: {row['notes']}")
                    
                    c1, c2, c3 = st.columns([1, 2, 2])
                    if c1.button("✅ 完成", key=f"d_{row['id']}"):
                        conn.execute("UPDATE reminders SET status='Done' WHERE id=?", (row['id'],))
                        conn.commit()
                        st.rerun()
                        
                    if c2.button("🔄 循环 (Repeat)", key=f"r_{row['id']}"):
                        conn.execute("UPDATE reminders SET status='Done' WHERE id=?", (row['id'],))
                        conn.commit()
                        st.session_state.prefill_task = {"patient_name": row['name'], "nursing_home": row['nursing_home'], "task_name": row['task_name'], "next_interval": row['interval'], "mode": "repeat"}
                        st.session_state.page = "New Task"
                        st.rerun()
                        
                    nxt = get_next_stage_interval(row['task_name'], row['interval'])
                    if nxt:
                        if c3.button(f"➡️ 进阶 ({nxt})", key=f"n_{row['id']}"):
                            conn.execute("UPDATE reminders SET status='Done' WHERE id=?", (row['id'],))
                            conn.commit()
                            st.session_state.prefill_task = {"patient_name": row['name'], "nursing_home": row['nursing_home'], "task_name": row['task_name'], "next_interval": nxt, "mode": "stage"}
                            st.session_state.page = "New Task"
                            st.rerun()
            st.divider()

# ================= NEW TASK =================
elif st.session_state.page == "New Task":
    st.title("🔔 创建任务")
    prefill = st.session_state.prefill_task
    if prefill: st.info(f"正在为 {prefill['patient_name']} 创建: {prefill.get('mode', 'new')} 任务")

    nh_list = pd.read_sql_query("SELECT DISTINCT nursing_home FROM patients WHERE nursing_home IS NOT NULL AND nursing_home != ''", conn)['nursing_home'].tolist()
    
    if not nh_list:
        st.error("请先在 '病人管理' 添加病人！")
    else:
        idx_nh = 0
        if prefill and prefill.get('nursing_home') in nh_list: idx_nh = nh_list.index(prefill.get('nursing_home'))
        sel_nh = st.selectbox("养老院", nh_list, index=idx_nh)
        
        pts = pd.read_sql_query("SELECT id, name FROM patients WHERE nursing_home = ?", conn, params=(sel_nh,))
        if pts.empty:
            st.warning("无病人数据")
        else:
            p_names = pts['name'].tolist()
            idx_pt = 0
            if prefill and prefill.get('patient_name') in p_names: idx_pt = p_names.index(prefill.get('patient_name'))
            sel_pt = st.selectbox("病人", p_names, index=idx_pt)
            sel_pt_id = int(pts[pts['name']==sel_pt]['id'].values[0])
            
            st.divider()
            
            tasks = pd.read_sql_query("SELECT * FROM task_types", conn)
            t_names = tasks['name'].tolist()
            idx_t = 0
            if prefill and prefill.get('task_name') in t_names: idx_t = t_names.index(prefill.get('task_name'))
            sel_task = st.selectbox("项目", t_names, index=idx_t)
            
            raw_int = tasks[tasks['name']==sel_task]['default_intervals'].values[0]
            opts = [x.strip() for x in raw_int.split(',')] + ["Custom"]
            idx_int = 0
            if prefill and prefill.get('next_interval'):
                target = prefill.get('next_interval').strip().lower()
                lower_opts = [x.lower() for x in opts]
                if target in lower_opts: idx_int = lower_opts.index(target)
            sel_int = st.selectbox("周期", opts, index=idx_int)
            
            final_int = sel_int
            if sel_int == "Custom": final_int = st.text_input("输入天数", "7 days")
            
            start_date = st.date_input("开始日期", datetime.now())
            due_date = calculate_due_date(start_date, final_int)
            
            st.markdown(f"#### 🗓️ 截止: :red[{due_date}]")
            notes = st.text_area("备注")
            
            if st.button("💾 保存任务", type="primary"):
                conn.execute("INSERT INTO reminders (patient_id, task_name, start_date, interval, due_date, status, notes) VALUES (?,?,?,?,?,?,?)",
                             (sel_pt_id, sel_task, str(start_date), final_int, str(due_date), 'Pending', notes))
                conn.commit()
                st.success("✅ 保存成功！")
                st.session_state.prefill_task = None

# ================= PATIENTS =================
elif st.session_state.page == "Patients":
    st.title("👤 病人管理")
    with st.form("add_p"):
        c1, c2 = st.columns(2)
        n = c1.text_input("姓名")
        nh = c2.text_input("养老院")
        d = st.date_input("生日", min_value=datetime(1900,1,1), value=datetime(1950,1,1))
        if st.form_submit_button("添加"):
            if n and nh:
                conn.execute("INSERT INTO patients (name, dob, nursing_home) VALUES (?,?,?)", (n, str(d), nh))
                conn.commit()
                st.success("已添加")
                st.rerun()
    st.dataframe(pd.read_sql_query("SELECT * FROM patients", conn), use_container_width=True)

# ================= EXCEL =================
elif st.session_state.page == "Excel":
    st.title("📂 数据备份")
    if st.button("下载数据"):
        df_r = pd.read_sql_query("SELECT * FROM reminders", conn)
        df_p = pd.read_sql_query("SELECT * FROM patients", conn)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_r.to_excel(writer, sheet_name='Reminders', index=False)
            df_p.to_excel(writer, sheet_name='Patients', index=False)
        st.download_button("下载 .xlsx", output.getvalue(), "backup.xlsx")
        
    st.subheader("导入")
    up = st.file_uploader("上传 Excel", type=['xlsx'])
    if up:
        df = pd.read_excel(up)
        df.columns = [c.lower().strip() for c in df.columns]
        if 'name' in df.columns:
            for _, r in df.iterrows():
                nh = r['nursing_home'] if 'nursing_home' in df.columns else "Unknown"
                conn.execute("INSERT INTO patients (name, dob, nursing_home) VALUES (?,?,?)", (r['name'], "1950-01-01", nh))
            conn.commit()
            st.success("导入成功")

# ================= SETTINGS (RESET) =================
elif st.session_state.page == "Settings":
    st.title("⚙️ 系统设置")
    
    st.warning("⚠️ 危险区域：重置数据库将清空所有数据！")
    st.write("如果发现数据乱码、无法显示，或者想重新开始，请点击下方按钮。")
    
    # 双重确认
    if st.checkbox("我确定要清空所有数据"):
        if st.button("🔴 重置/清空所有数据", type="primary"):
            try:
                # 关闭连接
                conn.close()
                # 删除文件
                if os.path.exists("np_reminder.db"):
                    os.remove("np_reminder.db")
                st.success("数据库已删除。请刷新页面，系统将自动重建空表。")
            except Exception as e:
                st.error(f"重置失败: {e}")