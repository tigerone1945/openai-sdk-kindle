except Exception as e:
    st.error(
        "分析中にエラーが発生しました。"
    )
    st.exception(e)
