ALLOWED_JOINS = {
    (
        "orders",
        "customers",
    ): (
        "customer_id",
        "customer_id",
    ),
    (
        "orders",
        "products",
    ): (
        "product_id",
        "product_id",
    ),
}
