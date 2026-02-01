import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sqlite3
import io

# --- 1. 数据库设置 & 初始化 ---
def init_db():
    conn = sqlite3.connect('np_reminder.db')
    c = conn.cursor()
    # 病人表
    c.execute('''CREATE TABLE IF NOT EXISTS patients
                 (id INTEGER PRIMARY KEY, name TEXT, dob TEXT, nursing_home TEXT)''')
    # 提醒项目配置表 (用于未来扩展)
    c.execute('''CREATE TABLE IF NOT EXISTS task_types
                 (id INTEGER PRIMARY KEY, name TEXT, default_intervals TEXT)''')
    # 提醒记录表
    c.execute('''CREATE TABLE IF NOT EXISTS reminders
                 (id INTEGER PRIMARY KEY, patient_id INTEGER, task_name TEXT, 
                  start_date TEXT, interval TEXT, due_date TEXT, status TEXT, notes TEXT,
                  FOREIGN KEY(patient_id) REFERENCES patients(id))''')
    
    # 预设来自截图的数据 (如果表中为空则初始化)
    c.execute("SELECT count(*) FROM task_types")
    if c.fetchone()[0] == 0:
        defaults = [
            ("Blood check", "1 month,3 months,6 months,12 months"),
            ("Antibiotics post treatment", "3 days,5 days,7 days,14 days,30 days"),
            ("Routine review", "Monthly"),
            ("Medication review", "3 Monthly"), # 修正了截图拼写 medizathion
            ("Diabetes review", "3 Monthly"),   # 修正了截图拼写 Diobetes
            ("Wounds review", "Monthly"),
            ("Medication changes review", "2 weeks")
        ]
        c.executemany("INSERT INTO task_types (name, default_intervals) VALUES (?, ?)", defaults)
        conn.commit()
    return conn

conn = init_db()

# --- 2. 辅助函数：日期计算 ---
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
            # 简单的月份计算逻辑
            months = 1 if interval_str == "monthly" else int(''.join(filter(str.isdigit, interval_str)))
            return (start + pd.DateOffset(months=months)).date()
        else:
            return start.date() # 无法解析则返回原日期
    except:
        return start.date()

# --- 3. 页面布局 ---
st.set_page_config(page_title="NP Clinical Assistant", layout="wide", page_icon="👩‍⚕️")

# 侧边栏导航
st.sidebar.title("👩‍⚕️ NP Assistant")
menu = st.sidebar.radio("导航", ["仪表盘 (Dashboard)", "添加病人 (Patients)", "新建提醒 (New Task)", "设置 (Settings)", "Excel 导入/导出"])

# --- 模块：仪表盘 (Dashboard) ---
if menu == "仪表盘 (Dashboard)":
    st.title("📅 待办事项提醒")
    
    # 获取数据
    df_reminders = pd.read_sql_query("""
        SELECT r.id, p.name as Patient, p.nursing_home as Location, 
               r.task_name as Task, r.due_date, r.status
        FROM reminders r
        JOIN patients p ON r.patient_id = p.id
        WHERE r.status = 'Pending'
        ORDER BY r.due_date ASC
    """, conn)
    
    if not df_reminders.empty:
        df_reminders['due_date'] = pd.to_datetime(df_reminders['due_date']).dt.date
        today = datetime.now().date()
        
        # 分类
        overdue = df_reminders[df_reminders['due_date'] < today]
        upcoming = df_reminders[(df_reminders['due_date'] >= today) & (df_reminders['due_date'] <= today + timedelta(days=7))]
        future = df_reminders[df_reminders['due_date'] > today + timedelta(days=7)]

        # 统计卡片
        col1, col2, col3 = st.columns(3)
        col1.metric("🚨 已逾期 (Overdue)", f"{len(overdue)}", delta_color="inverse")
        col2.metric("⚠️ 7天内到期 (Upcoming)", f"{len(upcoming)}")
        col3.metric("✅ 远期规划", f"{len(future)}")

        st.divider()

        if not overdue.empty:
            st.error("🚨以下任务已逾期，请优先处理！")
            st.dataframe(overdue, use_container_width=True)
        
        if not upcoming.empty:
            st.warning("⚠️ 本周内需要处理的任务")
            st.dataframe(upcoming, use_container_width=True)
            
        # 快速完成功能
        st.subheader("标记完成")
        task_to_close = st.selectbox("选择要关闭的任务 ID", df_reminders['id'].tolist())
        if st.button("标记为已完成 (Done)"):
            c = conn.cursor()
            c.execute("UPDATE reminders SET status = 'Done' WHERE id = ?", (task_to_close,))
            conn.commit()
            st.rerun()
            
    else:
        st.success("🎉 目前没有待办事项！")

# --- 模块：添加病人 (Patients) ---
elif menu == "添加病人 (Patients)":
    st.title("👤 病人管理")
    
    with st.form("add_patient"):
        col1, col2 = st.columns(2)
        name = col1.text_input("姓名 (Name)")
        dob = col2.date_input("生日 (DOB)", min_value=datetime(1920, 1, 1))
        nh = st.text_input("养老院名称 (Nursing Home)")
        submitted = st.form_submit_button("保存病人信息")
        
        if submitted and name:
            c = conn.cursor()
            c.execute("INSERT INTO patients (name, dob, nursing_home) VALUES (?, ?, ?)", 
                      (name, str(dob), nh))
            conn.commit()
            st.success(f"病人 {name} 已添加！")

    # 显示现有病人列表
    st.subheader("病人名册")
    patients_df = pd.read_sql_query("SELECT * FROM patients", conn)
    st.dataframe(patients_df, use_container_width=True)

# --- 模块：新建提醒 (New Task) ---
elif menu == "新建提醒 (New Task)":
    st.title("🔔 创建新的复查任务")
    
    # 1. 选择病人
    patients = pd.read_sql_query("SELECT id, name FROM patients", conn)
    if patients.empty:
        st.warning("请先在‘添加病人’页面添加数据")
    else:
        patient_dict = dict(zip(patients['name'], patients['id']))
        selected_patient_name = st.selectbox("选择病人", patients['name'])
        selected_patient_id = patient_dict[selected_patient_name]

        # 2. 选择项目类型 (动态从数据库读取，满足未来扩展需求)
        task_types = pd.read_sql_query("SELECT * FROM task_types", conn)
        task_dict = dict(zip(task_types['name'], task_types['default_intervals']))
        selected_task = st.selectbox("选择复查项目", task_types['name'])

        # 3. 选择或输入周期
        default_intervals = task_dict[selected_task].split(',')
        interval_options = default_intervals + ["Custom (Other)"]
        selected_interval = st.selectbox("选择周期/频率", interval_options)
        
        if selected_interval == "Custom (Other)":
            custom_days = st.number_input("手动输入天数 (Days)", min_value=1, value=7)
            final_interval = f"{custom_days} days"
        else:
            final_interval = selected_interval

        # 4. 计算日期
        start_date = st.date_input("开始日期/上次检查日期", datetime.now())
        calculated_due = calculate_due_date(start_date, final_interval)
        
        st.info(f"📅 预计复查日期: **{calculated_due}**")
        notes = st.text_area("备注 (Notes)")

        if st.button("创建提醒"):
            c = conn.cursor()
            c.execute("""INSERT INTO reminders 
                         (patient_id, task_name, start_date, interval, due_date, status, notes) 
                         VALUES (?, ?, ?, ?, ?, 'Pending', ?)""",
                      (selected_patient_id, selected_task, str(start_date), final_interval, str(calculated_due), notes))
            conn.commit()
            st.success("提醒已创建！")

# --- 模块：设置 (Settings) ---
elif menu == "设置 (Settings)":
    st.title("⚙️ 系统设置")
    st.markdown("在这里添加新的检查项目类型，以适应未来的需求。")
    
    with st.form("new_category"):
        new_cat = st.text_input("新项目名称 (例如: Flu Shot)")
        new_intervals = st.text_input("预设周期 (逗号分隔，例如: 6 months,1 year)")
        if st.form_submit_button("添加新项目"):
            c = conn.cursor()
            c.execute("INSERT INTO task_types (name, default_intervals) VALUES (?, ?)", (new_cat, new_intervals))
            conn.commit()
            st.success(f"项目 {new_cat} 已添加！")
            
    st.subheader("当前支持的项目类型")
    types_df = pd.read_sql_query("SELECT name, default_intervals FROM task_types", conn)
    st.table(types_df)

# --- 模块：Excel 导入/导出 ---
elif menu == "Excel 导入/导出":
    st.title("📂 数据备份与迁移")
    
    # 导出
    st.subheader("1. 导出数据")
    if st.button("生成 Excel 报表"):
        df_export = pd.read_sql_query("""
            SELECT p.name, p.nursing_home, r.task_name, r.due_date, r.status, r.notes
            FROM reminders r
            JOIN patients p ON r.patient_id = p.id
        """, conn)
        
        # 转换为 Excel 字节流
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_export.to_excel(writer, index=False, sheet_name='Reminders')
        
        st.download_button(
            label="下载 Excel 文件",
            data=output.getvalue(),
            file_name="NP_Reminders_Backup.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
    st.divider()
    
    # 导入 (简化版：仅演示逻辑，实际需根据模板严格匹配)
    st.subheader("2. 导入病人数据")
    uploaded_file = st.file_uploader("上传 Excel 文件 (需包含 name, dob, nursing_home 列)", type=['xlsx'])
    if uploaded_file:
        try:
            df_new = pd.read_excel(uploaded_file)
            # 简单检查列名
            if 'name' in df_new.columns:
                c = conn.cursor()
                for _, row in df_new.iterrows():
                    # 只有当包含必要信息时才插入
                    nh = row['nursing_home'] if 'nursing_home' in df_new.columns else 'Unknown'
                    dob = row['dob'] if 'dob' in df_new.columns else str(datetime.now().date())
                    c.execute("INSERT INTO patients (name, dob, nursing_home) VALUES (?, ?, ?)", 
                              (row['name'], str(dob), nh))
                conn.commit()
                st.success("导入成功！请到‘添加病人’页面查看。")
            else:
                st.error("Excel 格式不正确，缺少 'name' 列。")
        except Exception as e:
            st.error(f"导入失败: {e}")