# ================= EXCEL (修复与加固版) =================
elif st.session_state.page == "Excel":
    st.title("📂 数据备份与迁移")
    
    # --- 1. 导出功能 ---
    st.subheader("1. 导出 (Export)")
    st.info("将系统内所有数据下载为 Excel 文件，建议定期备份。")
    if st.button("📥 下载数据备份"):
        # 查询所有相关数据
        reminders_df = pd.read_sql_query("SELECT * FROM reminders", conn)
        patients_df = pd.read_sql_query("SELECT * FROM patients", conn)
        
        # 创建一个内存中的 Excel 文件
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            reminders_df.to_excel(writer, sheet_name='Reminders', index=False)
            patients_df.to_excel(writer, sheet_name='Patients', index=False)
        
        # 提供下载按钮
        st.download_button(
            label="✅ 点击下载 (.xlsx)",
            data=output.getvalue(),
            file_name=f"NP_Backup_{datetime.now().strftime('%Y-%m-%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    
    st.divider()
    
    # --- 2. 导入功能 (强化) ---
    st.subheader("2. 导入病人名单 (Import Patients)")
    
    # 提供模板下载，确保用户知道格式
    st.markdown("为了确保成功导入，请 **下载模板** 并按格式填写。")
    template_df = pd.DataFrame({
        'name': ['John Doe', 'Jane Smith'],
        'nursing_home': ['Sunshine Care', 'Hilltop View'],
        'dob': ['1950-01-15', '1948-03-22']
    })
    template_output = io.BytesIO()
    with pd.ExcelWriter(template_output, engine='openpyxl') as writer:
        template_df.to_excel(writer, index=False, sheet_name='Template')
    
    st.download_button(
        "📄 下载病人导入模板",
        data=template_output.getvalue(),
        file_name="patient_import_template.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    uploaded_file = st.file_uploader("上传填写好的 Excel 文件", type=['xlsx'])
    
    if uploaded_file is not None:
        try:
            # 读取上传的文件
            df_to_import = pd.read_excel(uploaded_file)
            
            # --- 智能容错处理 ---
            # 1. 清理列名：转小写，去前后空格
            df_to_import.columns = [str(c).lower().strip() for c in df_to_import.columns]
            
            # 2. 检查必需列是否存在
            required_cols = ['name', 'nursing_home']
            if not all(col in df_to_import.columns for col in required_cols):
                st.error(f"导入失败！Excel 文件中必须包含以下列: {', '.join(required_cols)}")
            else:
                # 3. 清理数据：去掉全为空的行
                df_to_import.dropna(how='all', inplace=True)
                
                # 获取数据库中现有病人，用于查重
                existing_patients = pd.read_sql_query("SELECT name, nursing_home FROM patients", conn)
                existing_set = set(zip(existing_patients['name'], existing_patients['nursing_home']))
                
                new_patients_data = []
                skipped_count = 0
                
                # 遍历 Excel 中的每一行
                for index, row in df_to_import.iterrows():
                    name = str(row['name']).strip()
                    nh = str(row['nursing_home']).strip()
                    
                    # 跳过名字或养老院为空的行
                    if not name or not nh:
                        continue
                    
                    # 查重：如果“名字+养老院”组合已存在，则跳过
                    if (name, nh) in existing_set:
                        skipped_count += 1
                        continue
                        
                    # dob 是可选的，如果不存在或为空，给个默认值
                    dob = str(row.get('dob', '1950-01-01')).split(' ')[0] # 只取日期部分，兼容 "YYYY-MM-DD HH:MM:SS"
                    
                    new_patients_data.append((name, dob, nh))

                # 批量插入数据库，效率更高
                if new_patients_data:
                    c = conn.cursor()
                    c.executemany("INSERT INTO patients (name, dob, nursing_home) VALUES (?, ?, ?)", new_patients_data)
                    conn.commit()
                    st.success(f"🎉 导入成功！新增 {len(new_patients_data)} 名病人。")
                    if skipped_count > 0:
                        st.warning(f"💡 跳过了 {skipped_count} 条重复或无效的记录。")
                else:
                    st.warning("Excel 中没有发现可导入的新病人记录。")

        except Exception as e:
            st.error(f"处理文件时发生错误: {e}")
            st.info("请确保上传的是有效的 Excel (.xlsx) 文件，并且格式与模板一致。")