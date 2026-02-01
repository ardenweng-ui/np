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
    
    # 初始化数据
    c.execute("SELECT count(*) FROM task_types")
    if c.fetchone()[0] == 0:
        defaults = [
            ("Blood check", "1 month,3 months,6 months,12 months"), # 阶段性
            ("Antibiotics post treatment", "3 days,5 days,7 days,14 days,30 days"), # 阶段性
            ("Routine review", "Monthly"),    # 循环性
            ("Medication review", "3 Monthly"), # 循环性
            ("Diabetes review", "3 Monthly"),   # 循环性
            ("Wounds review", "Weekly,Monthly"),
            ("Medication changes review", "2 weeks")
        ]
        c.executemany("INSERT INTO task_types (name, default_intervals) VALUES (?, ?)", defaults)
        conn.commit()
    return conn

conn = init_db()

# --- 2. 逻辑处理函数 ---

def calculate_due_date(start_date, interval_str):
    """计算到期日，修正了 3 Monthly 的理解"""
    start = pd.to_datetime(start_date)
    i_str = str(interval_str).lower().strip()
    
    try:
        # 处理 "3 Monthly" 或 "Monthly" 这种表达
        if "monthly" in i_str:
            # 提取数字，如果没有数字默认为 1
            nums = [int(s) for s in i_str.split() if s.isdigit()]
            months = nums[0] if nums else 1
            return (start + pd.DateOffset(months=months)).date()
            
        elif "month" in i_str: # 处理 "1 month", "3 months"
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
    """获取列表中的下一个（用于阶段性任务，如 Blood Check 1m -> 3m）"""
    try:
        df = pd.read_sql_query("SELECT default_intervals FROM task_types WHERE name = ?", conn, params=(task_name,))
        if df.empty: return None
        intervals = [x.strip().lower() for x in df.iloc[0]['default_intervals'].split(',')]
        curr = current_interval.strip().lower()
        
        if curr in intervals:
            idx = intervals.index(curr)
            if idx + 1 < len(intervals):
                return df.iloc[0]['default_intervals'].split(',')[idx+1].strip() # 返回原始格式
        return None
    except:
        return None

# --- 3. 页面配置 ---
st.set_page_config(page_title="NP Clinical Assistant", layout="wide", page_icon="👩‍⚕️")

if 'page' not in st.session_state: st.session_state.page = "Dashboard"
if 'prefill_task' not in st.session_state: st.session_state.prefill_task = None

# 导航
st.sidebar.title("👩‍⚕️ NP Assistant")
def nav(p): st.session_state.page = p; st.session_state.prefill_task = None if p != "New Task" else st.session_state.prefill_task

st.sidebar.button("📊 仪表盘 (Dashboard)", on_click=nav, args=("Dashboard",), use_container_width=True)
st.sidebar.button("➕ 新建提醒 (New Task)", on_click=nav, args=("New Task",), use_container_width=True)
st.sidebar.button("👤 病人管理 (Patients)", on_click=nav, args=("Patients",), use_container_width=True)
st.sidebar.button("📂 Excel 导入导出", on_click=nav, args=("Excel",), use_container_width=True)

# ================= DASHBOARD =================
if st.session_state.page == "Dashboard":
    st.title("📅 本周待办 (按养老院分组)")
    
    # 获取未来7天内的任务
    today = datetime.now().date()
    next_week = today + timedelta(days=7)
    
    # 1. 获取所有待办
    df = pd.read_sql_query("""
        SELECT r.id, p.name, p.nursing_home, r.task_name, r.interval, r.due_date, r.notes, r.patient_id
        FROM reminders r
        JOIN patients p ON r.patient_id = p.id
        WHERE r.status = 'Pending'
        ORDER BY p.nursing_home, r.due_date
    """, conn)
    
    if df.empty:
        st.success("🎉 目前没有任何待办事项！")
    else:
        df['due_date'] = pd.to_datetime(df['due_date']).dt.date
        
        # 筛选：逾期 + 未来7天
        mask_urgent = df['due_date'] <= next_week
        df_display = df[mask_urgent]
        
        # 按养老院分组展示
        unique_homes = df_display['nursing_home'].unique()
        
        if len(unique_homes) == 0:
            st.info("本周内没有即将到期的任务。")
            
        for home in unique_homes:
            # 这是一个养老院的区块
            st.markdown(f"### 🏥 {home}")
            home_tasks = df_display[df_display['nursing_home'] == home]
            
            for idx, row in home_tasks.iterrows():
                # 计算样式
                is_overdue = row['due_date'] < today
                color = "red" if is_overdue else "orange"
                icon = "🔥 逾期!" if is_overdue else "⚠️"
                
                with st.expander(f"{icon} {row['due_date']} | **{row['name']}** - {row['task_name']}"):
                    st.write(f"**周期**: {row['interval']} | **备注**: {row['notes']}")
                    
                    c1, c2, c3 = st.columns([1, 2, 2])
                    
                    # 选项 A: 仅完成
                    if c1.button("✅ 结束", key=f"end_{row['id']}"):
                        conn.execute("UPDATE reminders SET status='Done' WHERE id=?", (row['id'],))
                        conn.commit()
                        st.rerun()
                        
                    # 选项 B: 循环 (Repeat)
                    if c2.button(f"🔄 循环 ({row['interval']})", key=f"rep_{row['id']}"):
                        conn.execute("UPDATE reminders SET status='Done' WHERE id=?", (row['id'],))
                        conn.commit()
                        st.session_state.prefill_task = {
                            "patient_id": row['patient_id'],
                            "patient_name": row['name'],
                            "nursing_home": row['nursing_home'],
                            "task_name": row['task_name'],
                            "next_interval": row['interval'], # 保持一样
                            "mode": "repeat"
                        }
                        st.session_state.page = "New Task"
                        st.rerun()

                    # 选项 C: 下一阶段 (Next Stage)
                    next_stage = get_next_stage_interval(row['task_name'], row['interval'])
                    if next_stage:
                        if c3.button(f"➡️ 进阶 ({next_stage})", key=f"nxt_{row['id']}"):
                            conn.execute("UPDATE reminders SET status='Done' WHERE id=?", (row['id'],))
                            conn.commit()
                            st.session_state.prefill_task = {
                                "patient_id": row['patient_id'],
                                "patient_name": row['name'],
                                "nursing_home": row['nursing_home'],
                                "task_name": row['task_name'],
                                "next_interval": next_stage,
                                "mode": "stage"
                            }
                            st.session_state.page = "New Task"
                            st.rerun()
            st.divider() # 分隔线

# ================= NEW TASK =================
elif st.session_state.page == "New Task":
    st.title("🔔 创建任务")
    prefill = st.session_state.prefill_task
    
    if prefill:
        msg = f"🔄 正在为 **{prefill['patient_name']}** 建立循环复查" if prefill.get('mode') == 'repeat' else f"➡️ 正在为 **{prefill['patient_name']}** 建立下一阶段复查"
        st.info(msg)

    # 1. 选养老院
    nh_list = pd.read_sql_query("SELECT DISTINCT nursing_home FROM patients", conn)['nursing_home'].tolist()
    idx_nh = 0
    if prefill and prefill.get('nursing_home') in nh_list: idx_nh = nh_list.index(prefill.get('nursing_home'))
    sel_nh = st.selectbox("养老院", nh_list, index=idx_nh) if nh_list else None
    
    if sel_nh:
        # 2. 选病人
        pts = pd.read_sql_query("SELECT id, name FROM patients WHERE nursing_home = ?", conn, params=(sel_nh,))
        idx_pt = 0
        p_names = pts['name'].tolist()
        if prefill and prefill.get('patient_name') in p_names: idx_pt = p_names.index(prefill.get('patient_name'))
        sel_pt = st.selectbox("病人", p_names, index=idx_pt)
        sel_pt_id = pts[pts['name']==sel_pt]['id'].values[0]
        
        st.divider()
        
        # 3. 选任务
        tasks = pd.read_sql_query("SELECT * FROM task_types", conn)
        t_names = tasks['name'].tolist()
        idx_t = 0
        if prefill and prefill.get('task_name') in t_names: idx_t = t_names.index(prefill.get('task_name'))
        sel_task = st.selectbox("复查项目", t_names, index=idx_t)
        
        # 4. 选周期
        raw_int = tasks[tasks['name']==sel_task]['default_intervals'].values[0]
        opts = [x.strip() for x in raw_int.split(',')] + ["Custom"]
        
        idx_int = 0
        # 智能匹配预设周期
        if prefill and prefill.get('next_interval'):
            target = prefill.get('next_interval').strip().lower()
            lower_opts = [x.lower() for x in opts]
            if target in lower_opts: idx_int = lower_opts.index(target)
            
        sel_int = st.selectbox("周期", opts, index=idx_int)
        
        final_int = sel_int
        if sel_int == "Custom":
            final_int = st.text_input("输入周期 (如 2 weeks, 45 days)")
            
        start_date = st.date_input("开始日期", datetime.now())
        due_date = calculate_due_date(start_date, final_int)
        
        st.success(f"🗓️ 截止日期: **{due_date}**")
        notes = st.text_area("备注")
        
        if st.button("💾 保存", type="primary"):
            conn.execute("INSERT INTO reminders (patient_id, task_name, start_date, interval, due_date, status, notes) VALUES (?,?,?,?,?,?,?)",
                         (sel_pt_id, sel_task, str(start_date), final_int, str(due_date), 'Pending', notes))
            conn.commit()
            st.balloons()
            st.session_state.prefill_task = None

# ================= PATIENTS =================
elif st.session_state.page == "Patients":
    st.title("👤 病人管理")
    with st.form("p"):
        c1, c2 = st.columns(2)
        n = c1.text_input("姓名")
        nh = c2.text_input("养老院")
        d = st.date_input("生日", min_value=datetime(1900,1,1), value=datetime(1950,1,1))
        if st.form_submit_button("添加"):
            conn.execute("INSERT INTO patients (name, dob, nursing_home) VALUES (?,?,?)", (n, str(d), nh))
            conn.commit()
            st.success("已添加")
            st.rerun()
    
    st.dataframe(pd.read_sql_query("SELECT name, nursing_home, dob FROM patients", conn), use_container_width=True)

# ================= EXCEL 导入/导出 =================
elif st.session_state.page == "Excel":
    st.title("📂 数据备份")
    
    st.subheader("1. 导出数据 (Export)")
    if st.button("📥 下载 Excel 报表"):
        # 导出两张表：任务表和病人表
        df_r = pd.read_sql_query("""
            SELECT p.name, p.nursing_home, r.task_name, r.interval, r.due_date, r.status, r.notes 
            FROM reminders r JOIN patients p ON r.patient_id = p.id
        """, conn)
        df_p = pd.read_sql_query("SELECT * FROM patients", conn)
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_r.to_excel(writer, sheet_name='Reminders', index=False)
            df_p.to_excel(writer, sheet_name='Patients', index=False)
            
        st.download_button("点击下载 .xlsx", output.getvalue(), "NP_Backup.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        
    st.divider()
    
    st.subheader("2. 导入病人 (Import Patients)")
    st.info("请上传 Excel 文件，需包含 'name' 和 'nursing_home' 列。")
    up_file = st.file_uploader("上传 Excel", type=['xlsx'])
    
    if up_file:
        try:
            df_new = pd.read_excel(up_file)
            # 兼容性处理：把列名转小写去除空格，防止 excel 表头大小写不一致
            df_new.columns = [c.lower().strip() for c in df_new.columns]
            
            if 'name' in df_new.columns:
                count = 0
                for _, row in df_new.iterrows():
                    nm = row['name']
                    nh = row['nursing_home'] if 'nursing_home' in df_new.columns else "Unknown"
                    dob = str(row['dob']) if 'dob' in df_new.columns else "1950-01-01"
                    
                    # 简单查重：名字和养老院一样就不存了
                    exist = pd.read_sql_query("SELECT id FROM patients WHERE name=? AND nursing_home=?", conn, params=(nm, nh))
                    if exist.empty:
                        conn.execute("INSERT INTO patients (name, dob, nursing_home) VALUES (?,?,?)", (nm, dob, nh))
                        count += 1
                conn.commit()
                st.success(f"成功导入 {count} 名新病人！")
            else:
                st.error("错误：Excel 中找不到 'name' 列。")
        except Exception as e:
            st.error(f"读取失败: {e}")