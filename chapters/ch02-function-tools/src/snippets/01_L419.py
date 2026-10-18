df.groupby(
    "category",
    as_index=False,
)["sales_amount"].sum()
