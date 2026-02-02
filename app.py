import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, timedelta
import io
import os

# --- 0. 页面配置与安全 ---
st.set_page_config(page_title="NP Clinical Assistant Pro", layout="wide", page_icon="👩‍⚕️")

def check_password():
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False
    if st.session_state.password_correct: return True
    st.title("🔒 NP 系统登录")
    pwd = st.text_input("请输入密码", type="password")
    if st.button("登录"):
        if pwd == "1234": # 默认密码
            st.session_state.password_correct = True
            st.rerun()
        else: st.error("密码错误")
    return False

if not check_password(): st.stop()

# --- 1. Google Sheets 连接与初始化 ---
conn = st.connection("gsheets", type=GSheetsConnection)

def get_data(worksheet_name):
    try:
        df = conn.read(worksheet=worksheet_name, ttl="0")
        df = df.dropna(how="all")
        return df.fillna("")
    except:
        return pd.DataFrame()

def save_data(df, worksheet_name):
    # 强制转换格式，确保写入云端不报错
    df = df.astype(str).replace(['nan', 'None', 'NaT', '<NA>', 'NAT'], '')
    conn.update(worksheet=worksheet_name, data=df)
    st.cache_data.clear()

# 初始化读取三张核心表
patients_df = get_data("Patients")
reminders_df = get_data("Reminders")
task_types_df = get_data("TaskTypes")

# 容错：如果表结构为空，初始化标准表头
if patients_df.empty:
    patients_df = pd.DataFrame(columns=["id", "name", "dob", "nursing_home", "ward", "room", "notes"])
if reminders_df.empty:
    reminders_df = pd.DataFrame(columns=["id", "patient_id", "task_name", "start_date", "interval", "due_date", "status", "notes"])
if task_types_df.empty:
    task_types_df = pd.DataFrame([
        {"id": "1", "name": "Blood check", "default_intervals": "1 month,3 months,6 months,12 months"},
        {"id": "2", "name": "Routine review", "default_intervals": "Monthly"},
        {"id": "3", "name": "Diabetes review", "default_intervals": "3 Monthly"}
    ])
    save_data(task_types_df, "TaskTypes")

# --- 2. 核心计算工具 ---
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

# --- 3. 页面控制逻辑 ---
if 'page' not in st.session_state: st.session_state.page = "Dashboard"
if 'prefill' not in st.session_state: st.session_state.prefill = None

def nav(p): 
    st.session_state.page = p
    if p != "New Task": st.session_state.prefill = None

st.sidebar.title("👩‍⚕️ NP Assistant")
st.sidebar.button("📊 仪表盘 (Dashboard)", on_click=nav, args=("Dashboard",), use_container_width=True)
st.sidebar.button("➕ 新建提醒 (New Task)", on_click=nav, args=("New Task",), use_container_width=True)
st.sidebar.button("👤 病人管理 (Patients)", on_click=nav, args=("Patients",), use_container_width=True)
st.sidebar.button("📂 Excel 导入/导出", on_click=nav, args=("Excel",), use_container_width=True)
st.sidebar.button("⚙️ 系统设置 (Settings)", on_click=nav, args=("Settings",), use_container_width=True)

# ================= DASHBOARD (红绿灯 + 分组) =================
if st.session_state.page == "Dashboard":
    st.title("📅 实时待办看板")
    if reminders_df.empty or patients_df.empty:
        st.info("👋 云端暂无任务。请先添加病人或创建提醒。")
    else:
        # 统一 ID 格式用于合并
        reminders_df['patient_id'] = reminders_df['patient_id'].astype(str)
        patients_df['id'] = patients_df['id'].astype(str)
        merged = pd.merge(reminders_df, patients_df, left_on="patient_id", right_on="id", how="left")
        pending = merged[merged["status"] == "Pending"].copy()
        
        if pending.empty:
            st.success("🎉 目前没有待办任务！")
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
                        c1, c2, c3 = st.columns(3)
                        if c1.button("✅ 完成", key=f"d_{row['id_x']}"):
                            reminders_df.loc[reminders_df['id'] == row['id_x'], 'status'] = 'Done'
                            save_data(reminders_df, "Reminders"); st.rerun()
                        if c2.button("🔄 循环", key=f"r_{row['id_x']}"):
                            reminders_df.loc[reminders_df['id'] == row['id_x'], 'status'] = 'Done'
                            save_data(reminders_df, "Reminders")
                            st.session_state.prefill = {"p_id": row['patient_id'], "t_name": row['task_name'], "int": row['interval'], "mode": "repeat"}
                            st.session_state.page = "New Task"; st.rerun()
                        nxt = get_next_stage(row['task_name'], row['interval'])
                        if nxt and c3.button(f"➡️ 进阶({nxt})", key=f"n_{row['id_x']}"):
                            reminders_df.loc[reminders_df['id'] == row['id_x'], 'status'] = 'Done'
                            save_data(reminders_df, "Reminders")
                            st.session_state.prefill = {"p_id": row['patient_id'], "t_name": row['task_name'], "int": nxt, "mode": "stage"}
                            st.session_state.page = "New Task"; st.rerun()

# ================= NEW TASK (智能联动) =================
elif st.session_state.page == "New Task":
    st.title("➕ 创建新提醒")
    pre = st.session_state.prefill
    if patients_df.empty: st.error("请先添加病人")
    else:
        patients_df['id'] = patients_df['id'].astype(str)
        pt_list = patients_df.apply(lambda r: f"{r['name']} ({r['nursing_home']} - {r['ward']})", axis=1).tolist()
        idx_pt = 0
        if pre:
            match = patients_df[patients_df['id'] == str(pre['p_id'])]
            if not match.empty: idx_pt = patients_df.index[patients_df['id'] == str(pre['p_id'])][0]
            
        sel_pt_str = st.selectbox("1. 选择病人", pt_list, index=idx_pt)
        sel_pt_id = patients_df.iloc[pt_list.index(sel_pt_str)]['id']
        
        st.divider()
        task_names = task_types_df['name'].tolist()
        idx_t = 0
        if pre and pre['t_name'] in task_names: idx_t = task_names.index(pre['t_name'])
        sel_task = st.selectbox("2. 项目类型", task_names, index=idx_t)
        
        ints_raw = task_types_df[task_types_df['name']==sel_task]['default_intervals'].values[0]
        ints = [x.strip() for x in str(ints_raw).split(',')] + ["Custom"]
        idx_int = 0
        if pre and pre['int'] in ints: idx_int = ints.index(pre['int'])
        sel_int = st.selectbox("3. 周期", ints, index=idx_int)
        if sel_int == "Custom": sel_int = st.text_input("手动输入 (如 2 weeks)")
        
        due = calculate_due_date(st.date_input("开始日期", datetime.now()), sel_int)
        st.write(f"### 🗓️ 下次截止: :red[{due}]")
        notes = st.text_area("备注")
        
        if st.button("💾 保存并同步到云端", type="primary"):
            new_id = str(int(reminders_df['id'].astype(float).max() + 1)) if not reminders_df.empty else "1"
            new_row = pd.DataFrame([{
                "id": new_id, "patient_id": sel_pt_id, "task_name": sel_task,
                "start_date": str(datetime.now().date()), "interval": sel_int,
                "due_date": str(due), "status": "Pending", "notes": notes
            }])
            save_data(pd.concat([reminders_df, new_row], ignore_index=True), "Reminders")
            st.success("同步成功！"); st.session_state.prefill = None; st.balloons()

# ================= PATIENTS (在线编辑/新增/删除) =================
elif st.session_state.page == "Patients":
    st.title("👤 病人管理")
    with st.expander("➕ 添加单名新病人"):
        with st.form("add_p"):
            c1, c2, c3, c4 = st.columns(4)
            n = c1.text_input("姓名*")
            nh = c2.text_input("养老院*")
            w = c3.text_input("病区 (Ward)")
            r = c4.text_input("房号 (Room)")
            dob = st.date_input("生日", value=datetime(1950,1,1), min_value=datetime(1900,1,1))
            nts = st.text_area("备注")
            if st.form_submit_button("保存"):
                if n and nh:
                    new_id = str(int(patients_df['id'].astype(float).max() + 1)) if not patients_df.empty else "1"
                    new_row = pd.DataFrame([{"id": new_id, "name": n, "nursing_home": nh, "ward": w, "room": r, "dob": str(dob), "notes": nts}])
                    save_data(pd.concat([patients_df, new_row], ignore_index=True), "Patients")
                    st.success("已添加！"); st.rerun()

    st.subheader("📝 在线编辑名册")
    edited_df = st.data_editor(patients_df, use_container_width=True, num_rows="dynamic", key="pt_ed")
    if st.button("💾 同步表格修改", type="primary"):
        save_data(edited_df, "Patients"); st.success("同步成功！")

    st.divider()
    st.subheader("🗑️ 快速删除")
    target_p = st.selectbox("选择要删除的病人", patients_df['name'].tolist() if not patients_df.empty else [])
    if st.button("❌ 确认永久删除该病人"):
        p_id = patients_df[patients_df['name'] == target_p]['id'].values[0]
        save_data(patients_df[patients_df['id'] != p_id], "Patients")
        st.warning(f"{target_p} 已被移除"); st.rerun()

# ================= EXCEL 工具 (导入导出/备份恢复) =================
elif st.session_state.page == "Excel":
    st.title("📂 Excel 数据中心")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("1. 导出备份 (Export)")
        if st.button("📥 下载全量云端备份"):
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine='openpyxl') as writer:
                patients_df.to_excel(writer, sheet_name='Patients', index=False)
                reminders_df.to_excel(writer, sheet_name='Reminders', index=False)
                task_types_df.to_excel(writer, sheet_name='TaskTypes', index=False)
            st.download_button("点击保存 .xlsx", out.getvalue(), "NP_Cloud_Backup.xlsx")

    with col2:
        st.subheader("2. 批量导入病人 (Import)")
        if st.button("📄 下载标准导入模板"):
            tmp = pd.DataFrame(columns=["name", "nursing_home", "ward", "room", "dob", "notes"])
            out = io.BytesIO()
            with pd.ExcelWriter(out) as writer: tmp.to_excel(writer, index=False)
            st.download_button("下载空白模板", out.getvalue(), "import_template.xlsx")
            
        up = st.file_uploader("上传填好的表格", type=['xlsx'])
        if up:
            try:
                df_up = pd.read_excel(up)
                df_up.columns = [str(c).strip().lower() for c in df_up.columns]
                if 'name' not in df_up.columns: st.error("缺少 'name' 列")
                else:
                    df_up = df_up[df_up['name'].notna()]
                    start_id = int(patients_df['id'].astype(float).max() + 1) if not patients_df.empty else 1
                    df_up['id'] = range(start_id, start_id + len(df_up))
                    # 补全缺失列
                    for col in ["ward", "room", "dob", "notes"]:
                        if col not in df_up.columns: df_up[col] = ""
                    save_data(pd.concat([patients_df.astype(str), df_up.astype(str)], ignore_index=True), "Patients")
                    st.success(f"成功导入 {len(df_up)} 名病人！")
            except Exception as e: st.error(f"导入失败: {e}")

# ================= SETTINGS (项目管理/清空功能) =================
elif st.session_state.page == "Settings":
    st.title("⚙️ 系统设置")
    
    st.subheader("📋 自定义检查项目 (Task Types)")
    with st.form("add_task_type"):
        tn = st.text_input("新项目名称 (如: Flu Shot)")
        ti = st.text_input("默认周期 (用英文逗号隔开，如: 1 week, 6 months)")
        if st.form_submit_button("确认增加项目"):
            if tn and ti:
                new_id = str(int(task_types_df['id'].astype(float).max() + 1))
                new_row = pd.DataFrame([{"id": new_id, "name": tn, "default_intervals": ti}])
                save_data(pd.concat([task_types_df, new_row], ignore_index=True), "TaskTypes")
                st.success("项目已添加"); st.rerun()
    st.table(task_types_df[["name", "default_intervals"]])

    st.divider()
    st.subheader("🚨 危险区域")
    confirm = st.checkbox("我已了解数据清空后无法找回")
    col_a, col_b = st.columns(2)
    if col_a.button("🗑️ 仅清空‘提醒记录’", disabled=not confirm):
        save_data(pd.DataFrame(columns=["id", "patient_id", "task_name", "start_date", "interval", "due_date", "status", "notes"]), "Reminders")
        st.success("记录已清空")
    if col_b.button("🔴 完全重置系统", type="primary", disabled=not confirm):
        save_data(pd.DataFrame(columns=["id", "name", "dob", "nursing_home", "ward", "room", "notes"]), "Patients")
        save_data(pd.DataFrame(columns=["id", "patient_id", "task_name", "start_date", "interval", "due_date", "status", "notes"]), "Reminders")
        st.success("系统已重置")