import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sqlite3
import io

# --- 1. 数据库强化版 ---
def get_db_connection():
    # 使用 check_same_thread=False 防止 Streamlit 多线程报错
    conn = sqlite3.connect('np_reminder.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row # 允许像字典一样访问列
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
    
    # 初始化默认任务类型
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

# 初始化数据库
conn = init_db()

# --- 2. 逻辑函数 ---

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

# --- 3. 页面布局 ---
st.set_page_config(page_title="NP Clinical Assistant", layout="wide", page_icon="👩‍⚕️")

if 'page' not in st.session_state: st.session_state.page = "Dashboard"
if 'prefill_task' not in st.session_state: st.session_state.prefill_task = None

# 导航栏
st.sidebar.title("👩‍⚕️ NP Assistant")
def nav(p): st.session_state.page = p; st.session_state.prefill_task = None if p != "New Task" else st.session_state.prefill_task

st.sidebar.button("📊 仪表盘 (Dashboard)", on_click=nav, args=("Dashboard",), use_container_width=True)
st.sidebar.button("➕ 新建提醒 (New Task)", on_click=nav, args=("New Task",), use_container_width=True)
st.sidebar.button("👤 病人管理 (Patients)", on_click=nav, args=("Patients",), use_container_width=True)
st.sidebar.button("📂 Excel 备份", on_click=nav, args=("Excel",), use_container_width=True)
st.sidebar.markdown("---")
st.sidebar.button("🔧 调试/诊断 (Debug)", on_click=nav, args=("Debug",), use_container_width=True)

# ================= DASHBOARD =================
if st.session_state.page == "Dashboard":
    st.title("📅 待办事项看板")
    
    # 强制重新读取数据库，确保数据最新
    df = pd.read_sql_query("""
        SELECT r.id, p.name, p.nursing_home, r.task_name, r.interval, r.due_date, r.notes, r.patient_id, r.status
        FROM reminders r
        LEFT JOIN patients p ON r.patient_id = p.id
        WHERE r.status = 'Pending'
    """, conn)
    
    if df.empty:
        st.info("👋 目前没有 'Pending' 状态的任务。请去 '新建提醒' 试着加一个。")
    else:
        # 数据清洗：确保日期格式正确
        df['due_date'] = pd.to_datetime(df['due_date']).dt.date
        today = datetime.now().date()
        next_week = today + timedelta(days=7)
        
        # 顶部过滤器
        col_view1, col_view2 = st.columns([1, 4])
        # 默认改为 True (显示所有)，防止因为日期计算错误导致你看不到数据
        show_all = col_view1.checkbox("显示所有待办 (Show All)", value=True)
        
        # 筛选
        if show_all:
            df_display = df
        else:
            df_display = df[df['due_date'] <= next_week]
            
        # 排序
        df_display = df_display.sort_values(by=['nursing_home', 'due_date'])
        
        if df_display.empty:
            st.warning("本周内没有任务 (勾选 '显示所有' 查看远期任务)")
        else:
            # 分组显示逻辑
            # 处理 nursing_home 可能为 None 的情况
            df_display['nursing_home'] = df_display['nursing_home'].fillna("未分类 (Unknown Location)")
            unique_homes = df_display['nursing_home'].unique()
            
            st.write(f"共找到 {len(df_display)} 个待办任务：")
            
            for home in unique_homes:
                st.markdown(f"### 🏥 {home}")
                home_tasks = df_display[df_display['nursing_home'] == home]
                
                for idx, row in home_tasks.iterrows():
                    # 状态图标
                    is_overdue = row['due_date'] < today
                    icon = "🔴" if is_overdue else "📅"
                    
                    with st.expander(f"{icon} {row['due_date']} | {row['name']} - {row['task_name']}"):
                        st.write(f"**周期**: {row['interval']} | **备注**: {row['notes']}")
                        
                        c1, c2, c3 = st.columns([1, 2, 2])
                        
                        # 按钮逻辑
                        if c1.button("✅ 完成", key=f"d_{row['id']}"):
                            conn.execute("UPDATE reminders SET status='Done' WHERE id=?", (row['id'],))
                            conn.commit()
                            st.rerun()
                            
                        if c2.button(f"🔄 循环 ({row['interval']})", key=f"r_{row['id']}"):
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
    if prefill: st.info(f"正在为 {prefill['patient_name']} 创建新任务...")

    nh_list = pd.read_sql_query("SELECT DISTINCT nursing_home FROM patients WHERE nursing_home IS NOT NULL AND nursing_home != ''", conn)['nursing_home'].tolist()
    
    if not nh_list:
        st.error("请先在 '病人管理' 添加病人！")
    else:
        # 1. 选养老院
        idx_nh = 0
        if prefill and prefill.get('nursing_home') in nh_list: idx_nh = nh_list.index(prefill.get('nursing_home'))
        sel_nh = st.selectbox("养老院", nh_list, index=idx_nh)
        
        # 2. 选病人
        pts = pd.read_sql_query("SELECT id, name FROM patients WHERE nursing_home = ?", conn, params=(sel_nh,))
        if pts.empty:
            st.warning("该养老院下没有病人。")
        else:
            p_names = pts['name'].tolist()
            idx_pt = 0
            if prefill and prefill.get('patient_name') in p_names: idx_pt = p_names.index(prefill.get('patient_name'))
            sel_pt = st.selectbox("病人", p_names, index=idx_pt)
            # 强制转为 int，确保 ID 格式正确
            sel_pt_id = int(pts[pts['name']==sel_pt]['id'].values[0])
            
            st.divider()
            
            # 3. 任务细节
            tasks = pd.read_sql_query("SELECT * FROM task_types", conn)
            t_names = tasks['name'].tolist()
            idx_t = 0
            if prefill and prefill.get('task_name') in t_names: idx_t = t_names.index(prefill.get('task_name'))
            sel_task = st.selectbox("复查项目", t_names, index=idx_t)
            
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
            
            st.markdown(f"#### 截止日期: {due_date}")
            notes = st.text_area("备注")
            
            if st.button("💾 确认保存", type="primary"):
                try:
                    # 显式打印调试信息到后台 (如果是本地运行可以看到)
                    print(f"Saving: PID={sel_pt_id}, Task={sel_task}, Due={due_date}")
                    conn.execute("""
                        INSERT INTO reminders (patient_id, task_name, start_date, interval, due_date, status, notes) 
                        VALUES (?, ?, ?, ?, ?, 'Pending', ?)
                    """, (sel_pt_id, sel_task, str(start_date), final_int, str(due_date), notes))
                    conn.commit()
                    st.success("✅ 保存成功！请去 Dashboard 查看。")
                    st.session_state.prefill_task = None
                except Exception as e:
                    st.error(f"保存失败: {e}")

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
            else:
                st.error("姓名和养老院必填")
    
    st.dataframe(pd.read_sql_query("SELECT * FROM patients", conn), use_container_width=True)

# ================= EXCEL =================
elif st.session_state.page == "Excel":
    st.title("📂 Excel 备份")
    if st.button("下载数据"):
        df_r = pd.read_sql_query("SELECT * FROM reminders", conn)
        df_p = pd.read_sql_query("SELECT * FROM patients", conn)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_r.to_excel(writer, sheet_name='Reminders', index=False)
            df_p.to_excel(writer, sheet_name='Patients', index=False)
        st.download_button("下载 .xlsx", output.getvalue(), "backup.xlsx")
        
    st.markdown("---")
    st.subheader("导入病人")
    up = st.file_uploader("上传 Excel", type=['xlsx'])
    if up:
        df = pd.read_excel(up)
        # 简单处理列名
        df.columns = [c.lower().strip() for c in df.columns]
        if 'name' in df.columns:
            count = 0
            for _, r in df.iterrows():
                nh = r['nursing_home'] if 'nursing_home' in df.columns else "Unknown"
                conn.execute("INSERT INTO patients (name, dob, nursing_home) VALUES (?,?,?)", (r['name'], "1950-01-01", nh))
                count += 1
            conn.commit()
            st.success(f"导入 {count} 人")

# ================= DEBUG (新功能) =================
elif st.session_state.page == "Debug":
    st.title("🔧 数据库诊断面板")
    st.error("此页面用于检查数据是否真实存在。")
    
    st.subheader("1. 原始提醒表 (Reminders)")
    df_r = pd.read_sql_query("SELECT * FROM reminders", conn)
    st.dataframe(df_r)
    st.caption(f"共 {len(df_r)} 条记录。如果这里是空的，说明 '保存' 步骤失败了。")
    
    st.subheader("2. 原始病人表 (Patients)")
    df_p = pd.read_sql_query("SELECT * FROM patients", conn)
    st.dataframe(df_p)
    
    st.subheader("3. 联表查询测试")
    st.write("模拟 Dashboard 的查询逻辑：")
    query = """
        SELECT r.id, p.name, p.nursing_home, r.task_name, r.due_date, r.status
        FROM reminders r
        LEFT JOIN patients p ON r.patient_id = p.id
    """
    df_join = pd.read_sql_query(query, conn)
    st.dataframe(df_join)
    
    st.info("如果上面的 '联表查询' 里的 name 是 NaN (空的)，说明 patient_id 对不上。")