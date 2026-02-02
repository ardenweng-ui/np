import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, timedelta
import io

# --- 0. 配置与安全 ---
st.set_page_config(page_title="NP Assistant (Permanent)", layout="wide", page_icon="👩‍⚕️")

def check_password():
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False
    if st.session_state.password_correct: return True
    st.title("🔒 NP 系统登录 (永久存储版)")
    pwd = st.text_input("请输入密码", type="password")
    if st.button("登录"):
        if pwd == "1234": # 这里修改你的密码
            st.session_state.password_correct = True
            st.rerun()
        else: st.error("密码错误")
    return False

if not check_password(): st.stop()

# --- 1. Google Sheets 连接与初始化 ---
conn = st.connection("gsheets", type=GSheetsConnection)

def get_data(worksheet_name):
    # ttl=0 确保每次都从云端读取最新，不使用本地缓存
    try:
        df = conn.read(worksheet=worksheet_name, ttl="0")
        return df.dropna(how="all")
    except:
        return pd.DataFrame()

def save_data(df, worksheet_name):
    conn.update(worksheet=worksheet_name, data=df)
    st.cache_data.clear()

# 初始化三张核心表
patients_df = get_data("Patients")
reminders_df = get_data("Reminders")
task_types_df = get_data("TaskTypes")

# 如果表是空的，初始化表头
if patients_df.empty:
    patients_df = pd.DataFrame(columns=["id", "name", "dob", "nursing_home", "ward", "room"])
if reminders_df.empty:
    reminders_df = pd.DataFrame(columns=["id", "patient_id", "task_name", "start_date", "interval", "due_date", "status", "notes"])
if task_types_df.empty:
    task_types_df = pd.DataFrame([
        {"id": 1, "name": "Blood check", "default_intervals": "1 month,3 months,6 months,12 months"},
        {"name": "Routine review", "default_intervals": "Monthly"},
        {"name": "Diabetes review", "default_intervals": "3 Monthly"},
        {"name": "Wounds review", "default_intervals": "Weekly,Monthly"}
    ])
    save_data(task_types_df, "TaskTypes")

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
    row = task_types_df[task_types_df['name'] == task_name]
    if row.empty: return None
    ints = [x.strip() for x in str(row.iloc[0]['default_intervals']).split(',')]
    curr = str(current_interval).strip()
    if curr in ints:
        idx = ints.index(curr)
        if idx + 1 < len(ints): return ints[idx+1]
    return None

# --- 3. 导航控制 ---
if 'page' not in st.session_state: st.session_state.page = "Dashboard"
if 'prefill' not in st.session_state: st.session_state.prefill = None

def nav(p): 
    st.session_state.page = p
    if p != "New Task": st.session_state.prefill = None

st.sidebar.title("👩‍⚕️ NP Assistant")
st.sidebar.button("📊 仪表盘", on_click=nav, args=("Dashboard",), use_container_width=True)
st.sidebar.button("➕ 新建提醒", on_click=nav, args=("New Task",), use_container_width=True)
st.sidebar.button("👤 病人管理", on_click=nav, args=("Patients",), use_container_width=True)
st.sidebar.button("⚙️ 系统设置", on_click=nav, args=("Settings",), use_container_width=True)

# ================= DASHBOARD =================
if st.session_state.page == "Dashboard":
    st.title("📅 实时待办看板")
    st.caption("数据已与 Google Sheets 同步")
    
    if reminders_df.empty or patients_df.empty:
        st.info("👋 暂无任务或病人，请先添加数据。")
    else:
        # 联表：Reminders + Patients
        merged = pd.merge(reminders_df, patients_df, left_on="patient_id", right_on="id", how="left", suffixes=('', '_p'))
        pending = merged[merged["status"] == "Pending"].copy()
        
        if pending.empty:
            st.success("🎉 目前没有待办任务！")
        else:
            pending['due_date'] = pd.to_datetime(pending['due_date']).dt.date
            today = datetime.now().date()
            
            # 排序逻辑
            pending = pending.sort_values(by=['nursing_home', 'ward', 'room', 'due_date'])
            homes = pending['nursing_home'].unique()
            
            for home in homes:
                st.markdown(f"### 🏥 {home}")
                home_tasks = pending[pending['nursing_home'] == home]
                for idx, row in home_tasks.iterrows():
                    days_left = (row['due_date'] - today).days
                    icon = "🔴" if days_left < 0 else "🟠" if days_left <= 3 else "🟢"
                    loc = f"[{row['ward'] or '无'} - {row['room'] or '无'}]"
                    
                    with st.expander(f"{icon} {row['due_date']} | {row['name']} {loc} - {row['task_name']}"):
                        st.write(f"**周期**: {row['interval']} | **备注**: {row['notes'] or ''}")
                        c1, c2, c3 = st.columns(3)
                        
                        # 完成按钮逻辑
                        if c1.button("✅ 完成", key=f"done_{row['id']}"):
                            reminders_df.loc[reminders_df['id'] == row['id'], 'status'] = 'Done'
                            save_data(reminders_df, "Reminders")
                            st.rerun()
                        
                        # 联动按钮逻辑
                        if c2.button("🔄 循环", key=f"rep_{row['id']}"):
                            reminders_df.loc[reminders_df['id'] == row['id'], 'status'] = 'Done'
                            save_data(reminders_df, "Reminders")
                            st.session_state.prefill = {"p_id": row['patient_id'], "t_name": row['task_name'], "int": row['interval'], "mode": "repeat"}
                            st.session_state.page = "New Task"; st.rerun()
                            
                        nxt = get_next_stage(row['task_name'], row['interval'])
                        if nxt and c3.button(f"➡️ 进阶({nxt})", key=f"nxt_{row['id']}"):
                            reminders_df.loc[reminders_df['id'] == row['id'], 'status'] = 'Done'
                            save_data(reminders_df, "Reminders")
                            st.session_state.prefill = {"p_id": row['patient_id'], "t_name": row['task_name'], "int": nxt, "mode": "stage"}
                            st.session_state.page = "New Task"; st.rerun()

# ================= NEW TASK =================
elif st.session_state.page == "New Task":
    st.title("➕ 创建新提醒")
    pre = st.session_state.prefill
    
    if patients_df.empty: st.error("请先添加病人")
    else:
        # 病人选择
        pt_list = patients_df.apply(lambda r: f"{r['name']} ({r['nursing_home']} - {r['ward']})", axis=1).tolist()
        idx_pt = 0
        if pre:
            match = patients_df[patients_df['id'] == pre['p_id']]
            if not match.empty: idx_pt = patients_df.index[patients_df['id'] == pre['p_id']][0]
            
        sel_pt_str = st.selectbox("1. 选择病人", pt_list, index=idx_pt)
        sel_pt_id = patients_df.iloc[pt_list.index(sel_pt_str)]['id']
        
        st.divider()
        # 任务选择
        task_names = task_types_df['name'].tolist()
        idx_t = 0
        if pre and pre['t_name'] in task_names: idx_t = task_names.index(pre['t_name'])
        sel_task = st.selectbox("2. 项目类型", task_names, index=idx_t)
        
        # 周期选择
        ints_raw = task_types_df[task_types_df['name']==sel_task]['default_intervals'].values[0]
        ints = [x.strip() for x in str(ints_raw).split(',')] + ["Custom"]
        idx_int = 0
        if pre and pre['int'] in ints: idx_int = ints.index(pre['int'])
        sel_int = st.selectbox("3. 周期", ints, index=idx_int)
        if sel_int == "Custom": sel_int = st.text_input("手动输入 (如 2 weeks)")
        
        due = calculate_due_date(st.date_input("开始日期", datetime.now()), sel_int)
        st.write(f"### 🗓️ 下次截止: :red[{due}]")
        notes = st.text_area("备注")
        
        if st.button("💾 保存到云端", type="primary"):
            new_id = int(reminders_df['id'].max() + 1) if not reminders_df.empty else 1
            new_row = pd.DataFrame([{
                "id": new_id, "patient_id": sel_pt_id, "task_name": sel_task,
                "start_date": str(datetime.now().date()), "interval": sel_int,
                "due_date": str(due), "status": "Pending", "notes": notes
            }])
            updated = pd.concat([reminders_df, new_row], ignore_index=True)
            save_data(updated, "Reminders")
            st.success("同步成功！"); st.session_state.prefill = None; st.balloons()

# ================= PATIENTS =================
elif st.session_state.page == "Patients":
    st.title("👤 病人管理")
    with st.form("add_p"):
        c1, c2, c3, c4 = st.columns(4)
        name = c1.text_input("姓名*")
        nh = c2.text_input("养老院*")
        ward = c3.text_input("病区 (Ward)")
        room = c4.text_input("房号 (Room)")
        if st.form_submit_button("添加并同步"):
            if name and nh:
                new_id = int(patients_df['id'].max() + 1) if not patients_df.empty else 1
                new_row = pd.DataFrame([{"id": new_id, "name": name, "nursing_home": nh, "ward": ward, "room": room, "dob": "1950-01-01"}])
                updated = pd.concat([patients_df, new_row], ignore_index=True)
                save_data(updated, "Patients")
                st.success("病人已存入 Google Sheets"); st.rerun()
    st.dataframe(patients_df[["name", "nursing_home", "ward", "room"]], use_container_width=True)

# ================= SETTINGS =================
elif st.session_state.page == "Settings":
    st.title("⚙️ 系统设置")
    st.subheader("📋 项目模板")
    with st.form("add_t"):
        t_name = st.text_input("新项目名称")
        t_ints = st.text_input("预设周期 (逗号隔开)")
        if st.form_submit_button("保存项目"):
            new_row = pd.DataFrame([{"id": len(task_types_df)+1, "name": t_name, "default_intervals": t_ints}])
            updated = pd.concat([task_types_df, new_row], ignore_index=True)
            save_data(updated, "TaskTypes"); st.rerun()
    st.table(task_types_df[["name", "default_intervals"]])
    
    if st.button("🔄 强制刷新数据 (Clear Cache)"):
        st.cache_data.clear(); st.rerun()