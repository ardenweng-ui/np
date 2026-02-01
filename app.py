import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sqlite3
import io
import os

# --- 0. 安全与配置 ---
st.set_page_config(page_title="NP Clinical Assistant", layout="wide", page_icon="👩‍⚕️")

# 密码登录功能 (默认密码 1234)
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False

    if st.session_state.password_correct:
        return True

    st.title("🔒 NP 系统登录")
    col1, col2 = st.columns([1, 2])
    pwd = col1.text_input("请输入密码", type="password")
    if col1.button("登录"):
        if pwd == "1234":  # <--- 在这里修改密码
            st.session_state.password_correct = True
            st.rerun()
        else:
            col1.error("密码错误")
    return False

if not check_password():
    st.stop()

# --- 1. 数据库连接 ---
def get_db_connection():
    conn = sqlite3.connect('np_reminder.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS patients
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, dob TEXT, nursing_home TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS task_types
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, default_intervals TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS reminders
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id INTEGER, task_name TEXT, 
                  start_date TEXT, interval TEXT, due_date TEXT, status TEXT, notes TEXT)''')
    
    # 初始化数据
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

# --- 2. 核心算法 ---
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

# --- 3. 页面导航逻辑 ---
if 'page' not in st.session_state: st.session_state.page = "Dashboard"
if 'prefill_task' not in st.session_state: st.session_state.prefill_task = None

st.sidebar.title("👩‍⚕️ NP Assistant")
st.sidebar.caption("v2.1 Stable")

def nav(p): st.session_state.page = p; st.session_state.prefill_task = None if p != "New Task" else st.session_state.prefill_task

st.sidebar.button("📊 仪表盘 (Dashboard)", on_click=nav, args=("Dashboard",), use_container_width=True)
st.sidebar.button("➕ 新建提醒 (New Task)", on_click=nav, args=("New Task",), use_container_width=True)
st.sidebar.button("👤 病人管理 (Patients)", on_click=nav, args=("Patients",), use_container_width=True)
st.sidebar.button("📂 Excel 导入/导出", on_click=nav, args=("Excel",), use_container_width=True)
st.sidebar.markdown("---")
st.sidebar.button("⚙️ 系统重置 (Settings)", on_click=nav, args=("Settings",), use_container_width=True)

# ================= DASHBOARD =================
if st.session_state.page == "Dashboard":
    st.title("📅 待办事项看板")
    
    # 读取数据
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
        
        # 筛选
        col1, col2 = st.columns([1, 4])
        show_all = col1.checkbox("显示所有任务", value=True)
        if not show_all:
            df = df[df['due_date'] <= today + timedelta(days=7)]
        
        df = df.sort_values(by=['nursing_home', 'due_date'])
        
        # 统计
        n_overdue = len(df[df['due_date'] < today])
        n_urgent = len(df[(df['due_date'] >= today) & (df['due_date'] <= today + timedelta(days=3))])
        col2.markdown(f"🔴 逾期: **{n_overdue}** | 🟠 紧急(3天内): **{n_urgent}**")
        
        # 分组显示
        df['nursing_home'] = df['nursing_home'].fillna("未分类")
        homes = df['nursing_home'].unique()
        
        for home in homes:
            st.markdown(f"### 🏥 {home}")
            home_tasks = df[df['nursing_home'] == home]
            
            for _, row in home_tasks.iterrows():
                days_left = (row['due_date'] - today).days
                if days_left < 0:
                    status_color = "🔴"
                    bg_msg = f"已逾期 {abs(days_left)} 天!"
                elif days_left <= 3:
                    status_color = "🟠"
                    bg_msg = f"剩 {days_left} 天"
                else:
                    status_color = "🟢"
                    bg_msg = "远期规划"
                
                with st.expander(f"{status_color} **{row['name']}** - {row['task_name']} ({row['interval']})"):
                    st.caption(f"截止: **{row['due_date']}** | {bg_msg}")
                    if row['notes']: st.info(f"备注: {row['notes']}")
                    
                    c1, c2, c3 = st.columns([1, 2, 2])
                    if c1.button("✅ 完成", key=f"d_{row['id']}"):
                        conn.execute("UPDATE reminders SET status='Done' WHERE id=?", (row['id'],))
                        conn.commit()
                        st.rerun()
                    if c2.button("🔄 循环", key=f"r_{row['id']}"):
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
            st.markdown(f"#### 截止: {due_date}")
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

# ================= EXCEL (强化版) =================
elif st.session_state.page == "Excel":
    st.title("📂 数据管理中心")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("1. 导出数据 (Export)")
        st.write("将系统内所有数据备份为 Excel 文件。")
        if st.button("📥 下载完整数据备份"):
            df_r = pd.read_sql_query("SELECT * FROM reminders", conn)
            df_p = pd.read_sql_query("SELECT * FROM patients", conn)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_r.to_excel(writer, sheet_name='Reminders', index=False)
                df_p.to_excel(writer, sheet_name='Patients', index=False)
            st.download_button("点击下载 .xlsx", output.getvalue(), "NP_System_Backup.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with col2:
        st.subheader("2. 导入病人 (Import)")
        st.write("批量添加病人。")
        
        # --- 新增：下载模板功能 ---
        if st.button("📄 下载导入模板 (Blank Template)"):
            # 创建一个只包含表头的空 DataFrame
            template_df = pd.DataFrame(columns=["name", "nursing_home", "dob"])
            template_output = io.BytesIO()
            with pd.ExcelWriter(template_output, engine='openpyxl') as writer:
                template_df.to_excel(writer, index=False)
            st.download_button("下载空白模板", template_output.getvalue(), "import_template.xlsx")
        
        st.info("请先下载模板，填好后在下方上传。")
        
        up = st.file_uploader("上传填好的模板", type=['xlsx'])
        if up:
            try:
                df = pd.read_excel(up)
                # 清洗列名 (去空格，转小写)
                df.columns = [c.lower().strip() for c in df.columns]
                
                if 'name' not in df.columns:
                    st.error("错误：表格中缺少 'name' 列。请使用上面的模板。")
                else:
                    count = 0
                    for _, r in df.iterrows():
                        # 跳过空行
                        if pd.isna(r['name']) or str(r['name']).strip() == "":
                            continue
                            
                        nh = r['nursing_home'] if 'nursing_home' in df.columns and not pd.isna(r['nursing_home']) else "Unknown"
                        dob = r['dob'] if 'dob' in df.columns and not pd.isna(r['dob']) else "1950-01-01"
                        
                        conn.execute("INSERT INTO patients (name, dob, nursing_home) VALUES (?,?,?)", (r['name'], str(dob), nh))
                        count += 1
                    conn.commit()
                    st.success(f"🎉 成功导入 {count} 名病人！")
            except Exception as e:
                st.error(f"导入失败: {e}")

# ================= SETTINGS =================
elif st.session_state.page == "Settings":
    st.title("⚙️ 系统设置")
    st.warning("⚠️ 危险区域")
    if st.checkbox("我确定要清空所有数据"):
        if st.button("🔴 重置数据库", type="primary"):
            conn.close()
            if os.path.exists("np_reminder.db"):
                os.remove("np_reminder.db")
            st.success("已重置，请刷新页面。")