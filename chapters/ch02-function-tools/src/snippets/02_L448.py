df.groupby(
    "region",
    as_index=False,
)["sales_amount"].sum()
