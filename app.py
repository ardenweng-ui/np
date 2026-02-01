import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sqlite3
import io
import os

# --- 0. 配置与安全 ---
st.set_page_config(page_title="NP Clinical Assistant", layout="wide", page_icon="👩‍⚕️")

def check_password():
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False
    if st.session_state.password_correct: return True

    st.title("🔒 NP 系统登录")
    pwd = st.text_input("请输入密码", type="password")
    if st.button("登录"):
        if pwd == "1213": # 默认密码
            st.session_state.password_correct = True
            st.rerun()
        else:
            st.error("密码错误")
    return False

if not check_password(): st.stop()

# --- 1. 数据库强化 (支持动态增加列) ---
def get_db_connection():
    conn = sqlite3.connect('np_reminder.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    # 创建表
    c.execute('''CREATE TABLE IF NOT EXISTS patients
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, dob TEXT, 
                  nursing_home TEXT, ward TEXT, room TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS task_types
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, default_intervals TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS reminders
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id INTEGER, task_name TEXT, 
                  start_date TEXT, interval TEXT, due_date TEXT, status TEXT, notes TEXT)''')
    
    # 检查并更新旧表结构 (Schema Migration)
    # 如果用户是从旧版升级，可能缺 ward 和 room 列
    cursor = c.execute('PRAGMA table_info(patients)')
    columns = [row[1] for row in cursor.fetchall()]
    if 'ward' not in columns:
        c.execute('ALTER TABLE patients ADD COLUMN ward TEXT')
    if 'room' not in columns:
        c.execute('ALTER TABLE patients ADD COLUMN room TEXT')

    # 初始化默认任务
    c.execute("SELECT count(*) FROM task_types")
    if c.fetchone()[0] == 0:
        defaults = [
            ("Blood check", "1 month,3 months,6 months,12 months"),
            ("Antibiotics post treatment", "3 days,5 days,7 days,14 days,30 days"),
            ("Routine review", "Monthly"),
            ("Medication review", "3 Monthly"),
            ("Diabetes review", "3 Monthly"),
            ("Wounds review", "Weekly,Monthly")
        ]
        c.executemany("INSERT INTO task_types (name, default_intervals) VALUES (?, ?)", defaults)
    conn.commit()
    return conn

conn = init_db()

# --- 2. 工具函数 ---
def calculate_due_date(start_date, interval_str):
    start = pd.to_datetime(start_date)
    i_str = str(interval_str).lower().strip()
    try:
        nums = [int(s) for s in i_str.split() if s.isdigit()]
        num = nums[0] if nums else 1
        if "month" in i_str: return (start + pd.DateOffset(months=num)).date()
        if "week" in i_str: return (start + timedelta(weeks=num)).date()
        if "day" in i_str: return (start + timedelta(days=num)).date()
        return start.date()
    except: return start.date()

def get_next_stage(task_name, current_interval):
    df = pd.read_sql_query("SELECT default_intervals FROM task_types WHERE name = ?", conn, params=(task_name,))
    if df.empty: return None
    ints = [x.strip() for x in df.iloc[0]['default_intervals'].split(',')]
    curr = current_interval.strip()
    if curr in ints:
        idx = ints.index(curr)
        if idx + 1 < len(ints): return ints[idx+1]
    return None

# --- 3. 页面控制 ---
if 'page' not in st.session_state: st.session_state.page = "Dashboard"
if 'prefill_task' not in st.session_state: st.session_state.prefill_task = None

def nav(p): 
    st.session_state.page = p
    if p != "New Task": st.session_state.prefill_task = None

st.sidebar.title("👩‍⚕️ NP Assistant")
st.sidebar.button("📊 仪表盘", on_click=nav, args=("Dashboard",), use_container_width=True)
st.sidebar.button("➕ 新建提醒", on_click=nav, args=("New Task",), use_container_width=True)
st.sidebar.button("👤 病人管理", on_click=nav, args=("Patients",), use_container_width=True)
st.sidebar.button("📂 Excel 工具", on_click=nav, args=("Excel",), use_container_width=True)
st.sidebar.button("⚙️ 系统设置", on_click=nav, args=("Settings",), use_container_width=True)

# ================= DASHBOARD =================
if st.session_state.page == "Dashboard":
    st.title("📅 待办看板")
    df = pd.read_sql_query("""
        SELECT r.id, p.name, p.nursing_home, p.ward, p.room, r.task_name, r.interval, r.due_date, r.notes, r.patient_id
        FROM reminders r JOIN patients p ON r.patient_id = p.id WHERE r.status = 'Pending'
    """, conn)
    
    if df.empty: st.info("👋 暂无待办任务。")
    else:
        df['due_date'] = pd.to_datetime(df['due_date']).dt.date
        today = datetime.now().date()
        show_all = st.sidebar.checkbox("显示所有任务", value=True)
        if not show_all: df = df[df['due_date'] <= today + timedelta(days=7)]
        
        df = df.sort_values(by=['nursing_home', 'ward', 'room'])
        homes = df['nursing_home'].unique()
        
        for home in homes:
            st.markdown(f"### 🏥 {home}")
            home_tasks = df[df['nursing_home'] == home]
            for _, row in home_tasks.iterrows():
                days_left = (row['due_date'] - today).days
                icon = "🔴" if days_left < 0 else "🟠" if days_left <= 3 else "🟢"
                loc_str = f"[{row['ward'] or '无病区'} - {row['room'] or '无房号'}]"
                
                with st.expander(f"{icon} {row['due_date']} | {row['name']} {loc_str} - {row['task_name']}"):
                    st.write(f"**周期**: {row['interval']} | **备注**: {row['notes'] or '无'}")
                    c1, c2, c3 = st.columns(3)
                    if c1.button("✅ 完成", key=f"d_{row['id']}"):
                        conn.execute("UPDATE reminders SET status='Done' WHERE id=?", (row['id'],)); conn.commit(); st.rerun()
                    if c2.button("🔄 循环", key=f"r_{row['id']}"):
                        conn.execute("UPDATE reminders SET status='Done' WHERE id=?", (row['id'],)); conn.commit()
                        st.session_state.prefill_task = {"patient_name": row['name'], "nursing_home": row['nursing_home'], "task_name": row['task_name'], "next_interval": row['interval'], "mode": "repeat"}
                        st.session_state.page = "New Task"; st.rerun()
                    nxt = get_next_stage(row['task_name'], row['interval'])
                    if nxt and c3.button(f"➡️ 进阶({nxt})", key=f"n_{row['id']}"):
                        conn.execute("UPDATE reminders SET status='Done' WHERE id=?", (row['id'],)); conn.commit()
                        st.session_state.prefill_task = {"patient_name": row['name'], "nursing_home": row['nursing_home'], "task_name": row['task_name'], "next_interval": nxt, "mode": "stage"}
                        st.session_state.page = "New Task"; st.rerun()
            st.divider()

# ================= NEW TASK =================
elif st.session_state.page == "New Task":
    st.title("➕ 创建新提醒")
    prefill = st.session_state.prefill_task
    
    all_nh = pd.read_sql_query("SELECT DISTINCT nursing_home FROM patients WHERE nursing_home != ''", conn)['nursing_home'].tolist()
    if not all_nh: st.error("请先添加病人")
    else:
        sel_nh = st.selectbox("1. 选择养老院", all_nh, index=all_nh.index(prefill['nursing_home']) if prefill and prefill['nursing_home'] in all_nh else 0)
        pts = pd.read_sql_query("SELECT id, name, ward, room FROM patients WHERE nursing_home = ?", conn, params=(sel_nh,))
        pt_display = [f"{r['name']} ({r['ward']} - {r['room']})" for _, r in pts.iterrows()]
        sel_pt_idx = 0
        if prefill:
            for i, name in enumerate(pts['name']):
                if name == prefill['patient_name']: sel_pt_idx = i; break
        
        sel_pt_str = st.selectbox("2. 选择病人", pt_display, index=sel_pt_idx)
        sel_pt_id = int(pts.iloc[pt_display.index(sel_pt_str)]['id'])
        
        st.divider()
        tasks_df = pd.read_sql_query("SELECT * FROM task_types", conn)
        sel_task = st.selectbox("3. 项目类型", tasks_df['name'].tolist(), index=tasks_df['name'].tolist().index(prefill['task_name']) if prefill and prefill['task_name'] in tasks_df['name'].tolist() else 0)
        
        ints = [x.strip() for x in tasks_df[tasks_df['name']==sel_task]['default_intervals'].values[0].split(',')] + ["Custom"]
        idx_int = 0
        if prefill and prefill['next_interval'] in ints: idx_int = ints.index(prefill['next_interval'])
        sel_int = st.selectbox("4. 周期", ints, index=idx_int)
        if sel_int == "Custom": sel_int = st.text_input("输入天数", "7 days")
        
        due = calculate_due_date(st.date_input("开始日期", datetime.now()), sel_int)
        st.write(f"### 🗓️ 截止日期: :red[{due}]")
        notes = st.text_area("备注")
        if st.button("💾 保存任务", type="primary"):
            conn.execute("INSERT INTO reminders (patient_id, task_name, start_date, interval, due_date, status, notes) VALUES (?,?,?,?,?,?,?)",
                         (sel_pt_id, sel_task, str(datetime.now().date()), sel_int, str(due), 'Pending', notes))
            conn.commit(); st.success("已保存"); st.session_state.prefill_task = None

# ================= PATIENTS =================
elif st.session_state.page == "Patients":
    st.title("👤 病人管理")
    with st.form("add_p"):
        c1, c2, c3, c4 = st.columns(4)
        name = c1.text_input("姓名*")
        nh = c2.text_input("养老院*")
        ward = c3.text_input("病区/楼层 (Ward/Wing)")
        room = c4.text_input("房间号 (Room)")
        dob = st.date_input("生日", value=datetime(1950,1,1), min_value=datetime(1900,1,1))
        if st.form_submit_button("添加病人"):
            if name and nh:
                conn.execute("INSERT INTO patients (name, dob, nursing_home, ward, room) VALUES (?,?,?,?,?)", (name, str(dob), nh, ward, room))
                conn.commit(); st.success("已添加"); st.rerun()
            else: st.error("姓名和养老院必填")
    st.dataframe(pd.read_sql_query("SELECT name, nursing_home, ward, room, dob FROM patients", conn), use_container_width=True)

# ================= EXCEL =================
elif st.session_state.page == "Excel":
    st.title("📂 Excel 数据管理")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("导出备份")
        if st.button("📥 下载全量数据"):
            df_p = pd.read_sql_query("SELECT * FROM patients", conn)
            df_r = pd.read_sql_query("SELECT * FROM reminders", conn)
            out = io.BytesIO()
            with pd.ExcelWriter(out) as w:
                df_p.to_excel(w, sheet_name='Patients', index=False)
                df_r.to_excel(w, sheet_name='Reminders', index=False)
            st.download_button("点击下载", out.getvalue(), "NP_Backup.xlsx")
    with c2:
        st.subheader("批量导入病人")
        if st.button("📄 下载最新导入模板"):
            tmp = pd.DataFrame(columns=["name", "nursing_home", "ward", "room", "dob"])
            out = io.BytesIO()
            with pd.ExcelWriter(out) as w: tmp.to_excel(w, index=False)
            st.download_button("下载模板", out.getvalue(), "template.xlsx")
        up = st.file_uploader("上传模板", type=['xlsx'])
        if up:
            df = pd.read_excel(up)
            df.columns = [c.lower().strip() for c in df.columns]
            for _, r in df.iterrows():
                if pd.notna(r['name']):
                    conn.execute("INSERT INTO patients (name, dob, nursing_home, ward, room) VALUES (?,?,?,?,?)", 
                                 (str(r['name']), str(r.get('dob','1950-01-01')), str(r.get('nursing_home','Unknown')), str(r.get('ward','')), str(r.get('room',''))))
            conn.commit(); st.success("导入成功")

# ================= SETTINGS =================
elif st.session_state.page == "Settings":
    st.title("⚙️ 系统设置")
    
    st.subheader("📋 管理复查项目类型")
    with st.form("add_type"):
        t_name = st.text_input("项目名称 (例如: Skin Check)")
        t_ints = st.text_input("预设周期 (逗号分隔，例如: 1 week, 1 month, 3 months)")
        if st.form_submit_button("添加新项目"):
            if t_name and t_ints:
                conn.execute("INSERT INTO task_types (name, default_intervals) VALUES (?,?)", (t_name, t_ints))
                conn.commit(); st.success("添加成功"); st.rerun()
    
    st.write("现有项目：")
    st.table(pd.read_sql_query("SELECT name, default_intervals FROM task_types", conn))
    
    st.divider()
    st.subheader("🚨 危险区域")
    if st.checkbox("确认清空数据"):
        if st.button("🔴 重置所有数据"):
            conn.close(); os.remove("np_reminder.db"); st.success("已重置，请刷新页面")