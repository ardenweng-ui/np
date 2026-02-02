import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, timedelta
import io

# --- 0. 配置与安全 ---
st.set_page_config(page_title="NP Clinical Assistant (Pro)", layout="wide", page_icon="👩‍⚕️")

def check_password():
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False
    if st.session_state.password_correct: return True
    st.title("🔒 NP 系统登录")
    pwd = st.text_input("请输入密码", type="password")
    if st.button("登录"):
        if pwd == "1234": 
            st.session_state.password_correct = True
            st.rerun()
        else: st.error("密码错误")
    return False

if not check_password(): st.stop()

# --- 1. Google Sheets 连接 ---
conn = st.connection("gsheets", type=GSheetsConnection)

def get_data(worksheet_name):
    try:
        df = conn.read(worksheet=worksheet_name, ttl="0")
        df = df.dropna(how="all")
        return df.fillna("")
    except:
        return pd.DataFrame()

def save_data(df, worksheet_name):
    # 强制转换格式，处理各种异常值
    df = df.astype(str).replace(['nan', 'None', 'NaT', '<NA>'], '')
    conn.update(worksheet=worksheet_name, data=df)
    st.cache_data.clear()

# 初始化读取
patients_df = get_data("Patients")
reminders_df = get_data("Reminders")
task_types_df = get_data("TaskTypes")

# 初始化表结构 (如果为空)
if patients_df.empty:
    patients_df = pd.DataFrame(columns=["id", "name", "dob", "nursing_home", "ward", "room", "notes"])
if reminders_df.empty:
    reminders_df = pd.DataFrame(columns=["id", "patient_id", "task_name", "start_date", "interval", "due_date", "status", "notes"])

# --- 2. 导航 ---
if 'page' not in st.session_state: st.session_state.page = "Dashboard"
if 'prefill' not in st.session_state: st.session_state.prefill = None

def nav(p): 
    st.session_state.page = p
    if p != "New Task": st.session_state.prefill = None

st.sidebar.title("👩‍⚕️ NP Assistant")
st.sidebar.button("📊 仪表盘 (Dashboard)", on_click=nav, args=("Dashboard",), use_container_width=True)
st.sidebar.button("➕ 新建提醒 (New Task)", on_click=nav, args=("New Task",), use_container_width=True)
st.sidebar.button("👤 病人管理 (Patients)", on_click=nav, args=("Patients",), use_container_width=True)
st.sidebar.button("📂 Excel 导入导出", on_click=nav, args=("Excel",), use_container_width=True)
st.sidebar.button("⚙️ 系统设置 (Settings)", on_click=nav, args=("Settings",), use_container_width=True)

# ================= DASHBOARD =================
if st.session_state.page == "Dashboard":
    st.title("📅 实时待办看板")
    if reminders_df.empty or patients_df.empty:
        st.info("👋 云端没有找到待办任务。请先去添加病人或创建提醒。")
    else:
        reminders_df['patient_id'] = reminders_df['patient_id'].astype(str)
        patients_df['id'] = patients_df['id'].astype(str)
        merged = pd.merge(reminders_df, patients_df, left_on="patient_id", right_on="id", how="left")
        pending = merged[merged["status"] == "Pending"].copy()
        
        if pending.empty: st.success("🎉 目前没有待办任务！")
        else:
            pending['due_date'] = pd.to_datetime(pending['due_date']).dt.date
            today = datetime.now().date()
            pending = pending.sort_values(by=['nursing_home', 'ward', 'room', 'due_date'])
            for home in pending['nursing_home'].unique():
                st.markdown(f"### 🏥 {home}")
                home_tasks = pending[pending['nursing_home'] == home]
                for idx, row in home_tasks.iterrows():
                    days_left = (row['due_date'] - today).days
                    icon = "🔴" if days_left < 0 else "🟠" if days_left <= 3 else "🟢"
                    loc = f"[{row['ward']}-{row['room']}]"
                    with st.expander(f"{icon} {row['due_date']} | {row['name']} {loc} - {row['task_name']}"):
                        st.write(f"**任务备注**: {row['notes_x']}")
                        if st.button("✅ 标记完成", key=f"d_{row['id_x']}"):
                            reminders_df.loc[reminders_df['id'] == row['id_x'], 'status'] = 'Done'
                            save_data(reminders_df, "Reminders"); st.rerun()

# ================= PATIENTS =================
elif st.session_state.page == "Patients":
    st.title("👤 病人信息管理")
    
    with st.expander("➕ 添加新病人"):
        with st.form("add_p"):
            c1, c2, c3, c4 = st.columns(4)
            n = c1.text_input("姓名*")
            nh = c2.text_input("养老院*")
            w = c3.text_input("病区 (Ward)")
            r = c4.text_input("房号 (Room)")
            dob = st.date_input("生日", value=datetime(1950,1,1), min_value=datetime(1900,1,1))
            nts = st.text_area("病人备注")
            if st.form_submit_button("确认添加"):
                if n and nh:
                    new_id = str(int(patients_df['id'].astype(float).max() + 1)) if not patients_df.empty else "1"
                    new_row = pd.DataFrame([{"id": new_id, "name": n, "nursing_home": nh, "ward": w, "room": r, "dob": str(dob), "notes": nts}])
                    save_data(pd.concat([patients_df, new_row], ignore_index=True), "Patients")
                    st.success("病人已同步至云端！"); st.rerun()

    st.subheader("📝 快速编辑名册")
    edited_df = st.data_editor(patients_df, use_container_width=True, num_rows="dynamic", key="pt_ed")
    if st.button("💾 同步修改到云端", type="primary"):
        save_data(edited_df, "Patients"); st.success("同步成功！")

# ================= NEW TASK =================
elif st.session_state.page == "New Task":
    st.title("➕ 创建新提醒")
    if patients_df.empty: st.error("请先添加病人")
    else:
        pt_list = patients_df.apply(lambda r: f"{r['name']} ({r['nursing_home']} - {r['ward']})", axis=1).tolist()
        sel_pt_str = st.selectbox("1. 选择病人", pt_list)
        sel_pt_id = patients_df.iloc[pt_list.index(sel_pt_str)]['id']
        
        st.divider()
        task_names = task_types_df['name'].tolist() if not task_types_df.empty else ["Blood check"]
        sel_task = st.selectbox("2. 项目类型", task_names)
        sel_int = st.selectbox("3. 周期", ["1 week", "2 weeks", "1 month", "3 months", "6 months", "12 months", "Custom"])
        if sel_int == "Custom": sel_int = st.text_input("手动输入")
        
        start_date = st.date_input("开始日期", datetime.now())
        # 简单的周期计算辅助
        def calc_due(sd, i):
            try:
                num = int(''.join(filter(str.isdigit, i))) if any(c.isdigit() for c in i) else 1
                if "week" in i.lower(): return sd + timedelta(weeks=num)
                if "month" in i.lower(): return sd + pd.DateOffset(months=num)
                return sd + timedelta(days=num)
            except: return sd
        
        due = calc_due(start_date, sel_int)
        st.write(f"### 🗓️ 下次截止: :red[{due.date() if hasattr(due, 'date') else due}]")
        
        if st.button("💾 保存提醒"):
            new_id = str(int(reminders_df['id'].astype(float).max() + 1)) if not reminders_df.empty else "1"
            new_row = pd.DataFrame([{"id": new_id, "patient_id": sel_pt_id, "task_name": sel_task, "start_date": str(start_date), "interval": sel_int, "due_date": str(due.date() if hasattr(due, 'date') else due), "status": "Pending", "notes": ""}])
            save_data(pd.concat([reminders_df, new_row], ignore_index=True), "Reminders")
            st.success("已保存到云端"); st.balloons()

# ================= SETTINGS (含清空功能) =================
elif st.session_state.page == "Settings":
    st.title("⚙️ 系统设置")
    
    # 刷新按钮
    st.button("🔄 强制从 Google Sheets 刷新数据", on_click=lambda: st.cache_data.clear())
    
    st.divider()
    
    st.subheader("🚨 危险区域 (Danger Zone)")
    st.write("以下操作不可撤销，请谨慎操作。")
    
    # 确认钩选
    confirm = st.checkbox("我已了解数据清空后无法找回")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.info("💡 场景：结束了一年的工作，想清空所有任务记录，但保留病人名单。")
        if st.button("🗑️ 仅清空‘提醒记录’", disabled=not confirm):
            # 创建一个只有表头的空 Reminders 表
            empty_reminders = pd.DataFrame(columns=["id", "patient_id", "task_name", "start_date", "interval", "due_date", "status", "notes"])
            save_data(empty_reminders, "Reminders")
            st.success("所有提醒记录已清空！")
            st.rerun()

    with col2:
        st.info("💡 场景：想彻底重新开始，删除所有病人和所有记录。")
        if st.button("🔴 完全重置系统 (清空所有)", type="primary", disabled=not confirm):
            # 创建所有表的空表头
            empty_pts = pd.DataFrame(columns=["id", "name", "dob", "nursing_home", "ward", "room", "notes"])
            empty_reminders = pd.DataFrame(columns=["id", "patient_id", "task_name", "start_date", "interval", "due_date", "status", "notes"])
            
            save_data(empty_pts, "Patients")
            save_data(empty_reminders, "Reminders")
            
            st.warning("系统已完全重置。")
            st.rerun()

# ================= EXCEL =================
elif st.session_state.page == "Excel":
    st.title("📂 Excel 数据导出")
    if st.button("📥 导出当前病人名册"):
        output = io.BytesIO()
        patients_df.to_excel(output, index=False)
        st.download_button("下载 .xlsx", output.getvalue(), "Current_Patients.xlsx")