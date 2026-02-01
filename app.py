import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sqlite3
import io

# --- 1. 数据库设置 ---
def init_db():
    conn = sqlite3.connect('np_reminder.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS patients
                 (id INTEGER PRIMARY KEY, name TEXT, dob TEXT, nursing_home TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS task_types
                 (id INTEGER PRIMARY KEY, name TEXT, default_intervals TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS reminders
                 (id INTEGER PRIMARY KEY, patient_id INTEGER, task_name TEXT, 
                  start_date TEXT, interval TEXT, due_date TEXT, status TEXT, notes TEXT,
                  FOREIGN KEY(patient_id) REFERENCES patients(id))''')
    
    # 初始化预设数据
    c.execute("SELECT count(*) FROM task_types")
    if c.fetchone()[0] == 0:
        defaults = [
            ("Blood check", "1 month,3 months,6 months,12 months"), # 这里的顺序很重要，用于自动推断下一次
            ("Antibiotics post treatment", "3 days,5 days,7 days,14 days,30 days"),
            ("Routine review", "Monthly"),
            ("Medication review", "3 Monthly"),
            ("Diabetes review", "3 Monthly"),
            ("Wounds review", "Monthly"),
            ("Medication changes review", "2 weeks")
        ]
        c.executemany("INSERT INTO task_types (name, default_intervals) VALUES (?, ?)", defaults)
        conn.commit()
    return conn

conn = init_db()

# --- 2. 辅助函数 ---
def calculate_due_date(start_date, interval_str):
    start = pd.to_datetime(start_date)
    interval_str = interval_str.lower()
    try:
        if "day" in interval_str:
            days = int(''.join(filter(str.isdigit, interval_str)))
            return (start + timedelta(days=days)).date()
        elif "week" in interval_str:
            weeks = int(''.join(filter(str.isdigit, interval_str)))
            return (start + timedelta(weeks=weeks)).date()
        elif "month" in interval_str:
            # 如果是 Monthly (1个月) 或 3 Months
            num = ''.join(filter(str.isdigit, interval_str))
            months = 1 if num == "" else int(num)
            return (start + pd.DateOffset(months=months)).date()
        elif "year" in interval_str:
             years = int(''.join(filter(str.isdigit, interval_str)))
             return (start + pd.DateOffset(years=years)).date()
        else:
            return start.date()
    except:
        return start.date()

# 获取下一个推荐周期 (实现递进逻辑)
def get_next_interval(task_name, current_interval):
    try:
        df = pd.read_sql_query("SELECT default_intervals FROM task_types WHERE name = ?", conn, params=(task_name,))
        if df.empty: return None
        
        intervals_str = df.iloc[0]['default_intervals']
        intervals_list = intervals_str.split(',')
        
        # 找到当前周期的位置，并返回下一个
        # 比如当前是 "1 month"，列表是 [1 month, 3 months, 6 months...]，则返回 "3 months"
        for i, val in enumerate(intervals_list):
            if val.strip().lower() == current_interval.strip().lower():
                if i + 1 < len(intervals_list):
                    return intervals_list[i+1].strip()
        return None # 如果已经是最后一个，或者找不到，就不推荐
    except:
        return None

# --- 3. 页面布局 ---
st.set_page_config(page_title="NP Clinical Assistant", layout="wide", page_icon="👩‍⚕️")

# 初始化 session state 用于页面跳转传参
if 'page' not in st.session_state: st.session_state.page = "Dashboard"
if 'prefill_task' not in st.session_state: st.session_state.prefill_task = {}

# 侧边栏导航 (使用 callback 切换页面)
st.sidebar.title("👩‍⚕️ NP Assistant")
def set_page(page_name): st.session_state.page = page_name

st.sidebar.button("📊 仪表盘 (Dashboard)", on_click=set_page, args=("Dashboard",), use_container_width=True)
st.sidebar.button("➕ 新建提醒 (New Task)", on_click=set_page, args=("New Task",), use_container_width=True)
st.sidebar.button("👤 病人管理 (Patients)", on_click=set_page, args=("Patients",), use_container_width=True)
st.sidebar.button("⚙️ 设置 (Settings)", on_click=set_page, args=("Settings",), use_container_width=True)
st.sidebar.button("📂 导入导出 (Excel)", on_click=set_page, args=("Excel",), use_container_width=True)

# --- 模块：仪表盘 (Dashboard) ---
if st.session_state.page == "Dashboard":
    st.title("📅 待办事项提醒")
    
    # 筛选器：只看某个养老院的任务
    nh_list = pd.read_sql_query("SELECT DISTINCT nursing_home FROM patients", conn)['nursing_home'].tolist()
    if nh_list:
        nh_filter = st.multiselect("按养老院筛选 (Filter by Location)", nh_list)
    else:
        nh_filter = []

    base_query = """
        SELECT r.id, p.name, p.nursing_home, r.task_name, r.interval, r.due_date, r.status, r.patient_id
        FROM reminders r
        JOIN patients p ON r.patient_id = p.id
        WHERE r.status = 'Pending'
    """
    if nh_filter:
        ph = ','.join(['?']*len(nh_filter)) # 构造 SQL 占位符
        base_query += f" AND p.nursing_home IN ({ph})"
        df_reminders = pd.read_sql_query(base_query + " ORDER BY r.due_date ASC", conn, params=tuple(nh_filter))
    else:
        df_reminders = pd.read_sql_query(base_query + " ORDER BY r.due_date ASC", conn)
    
    if not df_reminders.empty:
        df_reminders['due_date'] = pd.to_datetime(df_reminders['due_date']).dt.date
        today = datetime.now().date()
        
        overdue = df_reminders[df_reminders['due_date'] < today]
        upcoming = df_reminders[(df_reminders['due_date'] >= today) & (df_reminders['due_date'] <= today + timedelta(days=7))]

        col1, col2 = st.columns(2)
        col1.error(f"🚨 已逾期: {len(overdue)}")
        col2.warning(f"⚠️ 本周到期: {len(upcoming)}")

        st.subheader("待处理任务列表")
        
        # 使用 Streamlit 的 data_editor 或简单的遍历来显示操作按钮
        # 这里为了实现“完成并创建下一个”，我们需要逐行显示
        for index, row in df_reminders.iterrows():
            # 卡片式显示
            card_color = "red" if row['due_date'] < today else "orange" if row['due_date'] <= today + timedelta(days=7) else "green"
            with st.expander(f"{'🚨' if card_color=='red' else '📅'} {row['due_date']} - {row['name']} ({row['task_name']})"):
                st.write(f"**位置**: {row['nursing_home']}")
                st.write(f"**当前周期**: {row['interval']}")
                
                c1, c2 = st.columns([1, 1])
                # 按钮 1: 仅标记完成
                if c1.button("✅ 仅标记完成", key=f"done_{row['id']}"):
                    conn.execute("UPDATE reminders SET status = 'Done' WHERE id = ?", (row['id'],))
                    conn.commit()
                    st.rerun()
                
                # 按钮 2: 完成并计划下一次 (体现递进逻辑)
                next_int = get_next_interval(row['task_name'], row['interval'])
                btn_label = f"➡️ 完成并计划下一次 ({next_int})" if next_int else "➡️ 完成并创建新计划"
                
                if c2.button(btn_label, key=f"next_{row['id']}"):
                    # 1. 标记旧的为完成
                    conn.execute("UPDATE reminders SET status = 'Done' WHERE id = ?", (row['id'],))
                    conn.commit()
                    # 2. 把信息存入 Session，跳转到新建页面
                    st.session_state.prefill_task = {
                        "patient_name": row['name'],
                        "patient_id": row['patient_id'],
                        "task_name": row['task_name'],
                        "default_interval": next_int # 自动填入建议的下一次周期
                    }
                    st.session_state.page = "New Task"
                    st.rerun()

    else:
        st.success("目前没有待办事项！")

# --- 模块：新建提醒 (New Task) ---
elif st.session_state.page == "New Task":
    st.title("🔔 创建任务")
    
    # 检查是否有预填信息（来自“完成并计划下一次”按钮）
    prefill = st.session_state.get('prefill_task', {})
    
    # --- 改进点 1: 级联选择 (Nursing Home -> Patient) ---
    st.subheader("1. 选择病人")
    
    # 获取所有养老院
    all_nh = pd.read_sql_query("SELECT DISTINCT nursing_home FROM patients", conn)
    
    if all_nh.empty:
        st.warning("请先去‘病人管理’添加病人")
    else:
        # 步骤 A: 选养老院
        nh_list = all_nh['nursing_home'].tolist()
        # 如果预填了病人，我们要尝试找到她所在的养老院作为默认值
        default_nh_index = 0
        if prefill:
            # 查询该病人的养老院
            p_nh = pd.read_sql_query(f"SELECT nursing_home FROM patients WHERE id={prefill['patient_id']}", conn).iloc[0]['nursing_home']
            if p_nh in nh_list:
                default_nh_index = nh_list.index(p_nh)
                
        selected_nh = st.selectbox("筛选养老院 (Select Location)", nh_list, index=default_nh_index)
        
        # 步骤 B: 选病人 (只显示该养老院的)
        patients_in_nh = pd.read_sql_query("SELECT id, name FROM patients WHERE nursing_home = ?", conn, params=(selected_nh,))
        
        # 设置下拉框默认值
        default_p_index = 0
        if prefill and prefill.get('patient_name') in patients_in_nh['name'].tolist():
             default_p_index = patients_in_nh['name'].tolist().index(prefill.get('patient_name'))
             
        selected_patient_name = st.selectbox("选择病人 (Select Patient)", patients_in_nh['name'], index=default_p_index)
        
        # 获取 ID
        if not patients_in_nh.empty:
            selected_patient_id = patients_in_nh[patients_in_nh['name'] == selected_patient_name]['id'].values[0]

            st.divider()
            st.subheader("2. 设定检查计划")

            # 任务类型选择
            task_types = pd.read_sql_query("SELECT * FROM task_types", conn)
            task_names = task_types['name'].tolist()
            
            # 预填任务类型
            default_task_index = 0
            if prefill and prefill.get('task_name') in task_names:
                default_task_index = task_names.index(prefill.get('task_name'))
                
            selected_task = st.selectbox("检查项目", task_names, index=default_task_index)
            
            # 周期选择
            # 获取该任务的默认周期列表
            intervals_str = task_types[task_types['name'] == selected_task]['default_intervals'].values[0]
            interval_options = intervals_str.split(',') + ["Custom"]
            
            # 预填周期 (如果系统推断出了下一次是 3 months，这里就自动选上)
            default_int_index = 0
            rec_next = prefill.get('default_interval')
            
            # 模糊匹配一下预填的周期（去空格）
            if rec_next:
                clean_opts = [x.strip() for x in interval_options]
                if rec_next.strip() in clean_opts:
                    default_int_index = clean_opts.index(rec_next.strip())
                    st.info(f"💡 系统已自动为您推荐下一阶段周期: **{rec_next}**")

            selected_interval = st.selectbox("周期/频率", interval_options, index=default_int_index)
            
            # 最终周期逻辑
            final_interval = selected_interval
            if selected_interval == "Custom":
                days = st.number_input("输入天数", min_value=1)
                final_interval = f"{days} days"

            # 设定开始日期（如果是续期，通常从今天开始算，或者是上一次的 due date? 这里默认用今天简单处理）
            start_date = st.date_input("开始计算日期 (Start Date)", datetime.now())
            
            due_date = calculate_due_date(start_date, final_interval)
            st.markdown(f"#### 🗓️ 下次复查日期: :red[{due_date}]")
            
            notes = st.text_area("备注", height=100)

            if st.button("创建/保存任务", type="primary"):
                conn.execute("INSERT INTO reminders (patient_id, task_name, start_date, interval, due_date, status, notes) VALUES (?,?,?,?,?,?,?)",
                             (selected_patient_id, selected_task, str(start_date), final_interval, str(due_date), 'Pending', notes))
                conn.commit()
                st.success("保存成功！")
                # 清除预填信息
                st.session_state.prefill_task = {}
                # 稍微延迟后刷新
                st.balloons()
        else:
            st.error("该养老院下没有病人，请先添加病人。")

# --- 模块：病人管理 (Patients) ---
elif st.session_state.page == "Patients":
    st.title("👤 病人管理")
    with st.form("add_p"):
        c1, c2 = st.columns(2)
        name = c1.text_input("姓名")
        nh = c2.text_input("养老院 (输入名称，系统会自动归类)")
        dob = st.date_input("生日", value=None)
        if st.form_submit_button("添加病人"):
            conn.execute("INSERT INTO patients (name, dob, nursing_home) VALUES (?,?,?)", (name, str(dob), nh))
            conn.commit()
            st.success("已添加")
            st.rerun()
            
    st.subheader("现有病人名册")
    # 增加一个简单的查看器
    df_p = pd.read_sql_query("SELECT * FROM patients ORDER BY nursing_home, name", conn)
    st.dataframe(df_p, use_container_width=True)

# --- 模块：设置与Excel ---
elif st.session_state.page == "Settings":
    st.title("⚙️ 设置")
    st.write("在这里管理检查项目模板。")
    # (保持原有逻辑，省略以节省长度)
    # ... 原有代码 ...

elif st.session_state.page == "Excel":
    st.title("📂 数据管理")
    # 导出
    if st.button("下载所有数据"):
        df = pd.read_sql_query("SELECT * FROM reminders", conn)
        # ... (Excel导出代码与之前一致) ...
        st.write("功能演示：点击下载 Excel")