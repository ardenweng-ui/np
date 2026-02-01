import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sqlite3

# --- 1. 数据库初始化 ---
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
    
    # 初始化默认配置
    c.execute("SELECT count(*) FROM task_types")
    if c.fetchone()[0] == 0:
        defaults = [
            ("Blood check", "1 month,3 months,6 months,12 months"),
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

# --- 2. 核心逻辑函数 ---

def calculate_due_date(start_date, interval_str):
    """根据开始日期和周期计算截止日期"""
    start = pd.to_datetime(start_date)
    interval_str = str(interval_str).lower()
    try:
        if "day" in interval_str:
            days = int(''.join(filter(str.isdigit, interval_str)))
            return (start + timedelta(days=days)).date()
        elif "week" in interval_str:
            weeks = int(''.join(filter(str.isdigit, interval_str)))
            return (start + timedelta(weeks=weeks)).date()
        elif "month" in interval_str:
            # 处理 Monthly 和 3 Months
            if "monthly" in interval_str:
                return (start + pd.DateOffset(months=1)).date()
            else:
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

def get_next_interval(task_name, current_interval):
    """查找下一个推荐周期 (实现联动逻辑)"""
    try:
        df = pd.read_sql_query("SELECT default_intervals FROM task_types WHERE name = ?", conn, params=(task_name,))
        if df.empty: return None
        
        intervals_str = df.iloc[0]['default_intervals']
        # 清理空格并分割
        intervals_list = [x.strip() for x in intervals_str.split(',')]
        curr_clean = current_interval.strip()
        
        # 查找当前位置
        # 注意：这里做不区分大小写的匹配
        intervals_lower = [x.lower() for x in intervals_list]
        
        if curr_clean.lower() in intervals_lower:
            idx = intervals_lower.index(curr_clean.lower())
            if idx + 1 < len(intervals_list):
                return intervals_list[idx+1] # 返回下一个
        return None 
    except:
        return None

# --- 3. 页面设置 ---
st.set_page_config(page_title="NP Clinical Assistant", layout="wide", page_icon="👩‍⚕️")

# Session State 管理
if 'page' not in st.session_state: st.session_state.page = "Dashboard"
if 'prefill_task' not in st.session_state: st.session_state.prefill_task = None

# 侧边栏
st.sidebar.title("👩‍⚕️ NP Assistant")
def nav_to(page): 
    st.session_state.page = page
    # 如果手动切换页面，清空预填信息，避免混乱
    if page != "New Task": 
        st.session_state.prefill_task = None

st.sidebar.button("📊 仪表盘 (Dashboard)", on_click=nav_to, args=("Dashboard",), use_container_width=True)
st.sidebar.button("➕ 新建提醒 (New Task)", on_click=nav_to, args=("New Task",), use_container_width=True)
st.sidebar.button("👤 病人管理 (Patients)", on_click=nav_to, args=("Patients",), use_container_width=True)
st.sidebar.button("⚙️ 设置 (Settings)", on_click=nav_to, args=("Settings",), use_container_width=True)

# ==========================================
# 页面 1: 仪表盘 (Dashboard)
# ==========================================
if st.session_state.page == "Dashboard":
    st.title("📅 待办事项")
    
    # 养老院筛选
    all_p = pd.read_sql_query("SELECT DISTINCT nursing_home FROM patients", conn)
    nh_list = all_p['nursing_home'].tolist() if not all_p.empty else []
    
    selected_nh_filter = st.multiselect("按养老院筛选 (Location Filter)", nh_list)

    # 查询数据
    query = """
        SELECT r.id, p.name, p.nursing_home, r.task_name, r.interval, r.due_date, r.status, r.patient_id, r.notes
        FROM reminders r
        JOIN patients p ON r.patient_id = p.id
        WHERE r.status = 'Pending'
    """
    params = []
    if selected_nh_filter:
        placeholders = ','.join(['?'] * len(selected_nh_filter))
        query += f" AND p.nursing_home IN ({placeholders})"
        params = selected_nh_filter
        
    df = pd.read_sql_query(query + " ORDER BY r.due_date ASC", conn, params=params)
    
    if not df.empty:
        df['due_date'] = pd.to_datetime(df['due_date']).dt.date
        today = datetime.now().date()
        
        # 统计
        overdue = len(df[df['due_date'] < today])
        upcoming = len(df[(df['due_date'] >= today) & (df['due_date'] <= today + timedelta(days=7))])
        
        c1, c2, c3 = st.columns(3)
        c1.metric("🚨 逾期任务", overdue)
        c2.metric("⚠️ 本周到期", upcoming)
        c3.metric("📋 总待办", len(df))
        
        st.divider()

        # 任务列表卡片
        for idx, row in df.iterrows():
            # 颜色逻辑
            color = "red" if row['due_date'] < today else "orange" if row['due_date'] <= today + timedelta(days=7) else "green"
            icon = "🔥" if color == "red" else "⚠️" if color == "orange" else "📅"
            
            with st.expander(f"{icon} {row['due_date']} | {row['name']} - {row['task_name']} ({row['interval']})"):
                st.markdown(f"**位置**: {row['nursing_home']}  \n**备注**: {row['notes'] or '无'}")
                
                col_a, col_b = st.columns([1, 2])
                
                # 按钮 A: 仅完成
                if col_a.button("✅ 结束任务", key=f"done_{row['id']}"):
                    conn.execute("UPDATE reminders SET status = 'Done' WHERE id = ?", (row['id'],))
                    conn.commit()
                    st.rerun()
                
                # 按钮 B: 联动 - 计划下一次
                next_int = get_next_interval(row['task_name'], row['interval'])
                btn_text = f"➡️ 完成并创建下阶段 ({next_int})" if next_int else "➡️ 完成并继续复查"
                
                if col_b.button(btn_text, key=f"link_{row['id']}", type="primary"):
                    # 1. 标记当前为 Done
                    conn.execute("UPDATE reminders SET status = 'Done' WHERE id = ?", (row['id'],))
                    conn.commit()
                    
                    # 2. 准备传参给新建页面
                    st.session_state.prefill_task = {
                        "patient_id": row['patient_id'],
                        "patient_name": row['name'],
                        "nursing_home": row['nursing_home'],
                        "task_name": row['task_name'],
                        "prev_interval": row['interval'],
                        "next_interval": next_int,  # 可能是 None
                        "from_linkage": True
                    }
                    st.session_state.page = "New Task"
                    st.rerun()
    else:
        st.info("🎉 当前没有待办事项，喝杯咖啡吧！")

# ==========================================
# 页面 2: 新建任务 (New Task) - 包含联动逻辑
# ==========================================
elif st.session_state.page == "New Task":
    st.title("🔔 创建复查任务")
    
    # 读取预填信息
    prefill = st.session_state.prefill_task
    
    # 如果是从 Dashboard 跳转过来的，显示提示条
    if prefill and prefill.get('from_linkage'):
        next_txt = prefill.get('next_interval') if prefill.get('next_interval') else "新周期"
        st.success(f"🚀 正在为 **{prefill['patient_name']}** 创建后续复查。上阶段: {prefill['prev_interval']} → 推荐本阶段: **{next_txt}**")
    
    # 1. 养老院选择
    all_nh = pd.read_sql_query("SELECT DISTINCT nursing_home FROM patients", conn)['nursing_home'].tolist()
    
    if not all_nh:
        st.warning("请先添加病人数据")
    else:
        # 自动选中养老院
        idx_nh = 0
        if prefill and prefill.get('nursing_home') in all_nh:
            idx_nh = all_nh.index(prefill.get('nursing_home'))
            
        selected_nh = st.selectbox("1. 选择养老院", all_nh, index=idx_nh)
        
        # 2. 病人选择 (级联)
        pts_df = pd.read_sql_query("SELECT id, name FROM patients WHERE nursing_home = ?", conn, params=(selected_nh,))
        pts_names = pts_df['name'].tolist()
        
        # 自动选中病人
        idx_pt = 0
        if prefill and prefill.get('patient_name') in pts_names:
            idx_pt = pts_names.index(prefill.get('patient_name'))
            
        if pts_names:
            selected_pt_name = st.selectbox("2. 选择病人", pts_names, index=idx_pt)
            selected_pt_id = pts_df[pts_df['name'] == selected_pt_name]['id'].values[0]
            
            st.divider()
            
            # 3. 任务类型
            types_df = pd.read_sql_query("SELECT * FROM task_types", conn)
            type_names = types_df['name'].tolist()
            
            # 自动选中任务类型
            idx_task = 0
            if prefill and prefill.get('task_name') in type_names:
                idx_task = type_names.index(prefill.get('task_name'))
            
            selected_task = st.selectbox("3. 复查项目", type_names, index=idx_task)
            
            # 4. 周期选择
            # 获取该任务对应的选项
            intervals_raw = types_df[types_df['name'] == selected_task]['default_intervals'].values[0]
            interval_opts = [x.strip() for x in intervals_raw.split(',')] + ["Custom"]
            
            # 自动选中推荐的周期 (如果有 next_interval)
            idx_int = 0
            if prefill and prefill.get('next_interval'):
                # 尝试匹配推荐值
                target = prefill.get('next_interval').strip().lower()
                opts_lower = [x.lower() for x in interval_opts]
                if target in opts_lower:
                    idx_int = opts_lower.index(target)
            
            selected_interval = st.selectbox("4. 复查周期", interval_opts, index=idx_int)
            
            # 计算逻辑
            final_interval = selected_interval
            if selected_interval == "Custom":
                days = st.number_input("输入天数", min_value=1, value=7)
                final_interval = f"{days} days"
                
            start_date = st.date_input("开始日期 (默认今天)", datetime.now())
            due_date = calculate_due_date(start_date, final_interval)
            
            st.info(f"🗓️ 系统计算截止日: **{due_date}**")
            
            notes = st.text_area("备注 (可选)", value=f"Follow up from previous {prefill.get('prev_interval')}" if (prefill and prefill.get('prev_interval')) else "")
            
            if st.button("💾 保存任务", type="primary"):
                conn.execute("INSERT INTO reminders (patient_id, task_name, start_date, interval, due_date, status, notes) VALUES (?,?,?,?,?,?,?)",
                             (selected_pt_id, selected_task, str(start_date), final_interval, str(due_date), 'Pending', notes))
                conn.commit()
                st.success("任务已保存！")
                st.session_state.prefill_task = None # 清空缓存
                
        else:
            st.error("该养老院下暂无病人")

# ==========================================
# 页面 3: 病人管理 (修正了生日范围)
# ==========================================
elif st.session_state.page == "Patients":
    st.title("👤 添加新病人")
    
    with st.form("new_patient"):
        c1, c2 = st.columns(2)
        name = c1.text_input("病人姓名")
        nh = c2.text_input("所在养老院")
        
        # 修正点：设置 min_value 为 1900年，default 为 1950年
        dob = st.date_input(
            "出生日期 (DOB)", 
            min_value=datetime(1900, 1, 1), 
            max_value=datetime.now(),
            value=datetime(1950, 1, 1) # 默认显示 1950，方便向前向后翻
        )
        
        if st.form_submit_button("保存"):
            if name and nh:
                conn.execute("INSERT INTO patients (name, dob, nursing_home) VALUES (?,?,?)", (name, str(dob), nh))
                conn.commit()
                st.success(f"{name} 已添加")
            else:
                st.error("请填写姓名和养老院")
                
    st.subheader("📋 病人名册")
    df_p = pd.read_sql_query("SELECT name, nursing_home, dob FROM patients ORDER BY nursing_home", conn)
    st.dataframe(df_p, use_container_width=True)

# ==========================================
# 页面 4: 设置 (Settings)
# ==========================================
elif st.session_state.page == "Settings":
    st.title("⚙️ 系统设置")
    
    st.write("### 添加新的复查类型")
    with st.form("add_type"):
        tn = st.text_input("项目名称 (如: Flu Shot)")
        ti = st.text_input("预设周期 (逗号分隔, 如: 3 months, 6 months)")
        if st.form_submit_button("添加"):
            conn.execute("INSERT INTO task_types (name, default_intervals) VALUES (?,?)", (tn, ti))
            conn.commit()
            st.success("添加成功")

    st.write("### 现有类型")
    st.dataframe(pd.read_sql_query("SELECT * FROM task_types", conn), use_container_width=True)