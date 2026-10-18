-- 業務データのスキーマ。型・制約は、第9章のSQLite版より厳しい(日付はDATE、割引率はNUMERIC)。
CREATE TABLE customers (
    customer_id    TEXT PRIMARY KEY,
    customer_name  TEXT NOT NULL,
    customer_type  TEXT NOT NULL
);

CREATE TABLE products (
    product_id    TEXT PRIMARY KEY,
    product_name  TEXT NOT NULL,
    category      TEXT NOT NULL
);

CREATE TABLE orders (
    order_id       TEXT PRIMARY KEY,
    order_date     DATE NOT NULL,
    customer_id    TEXT NOT NULL REFERENCES customers (customer_id),
    product_id     TEXT NOT NULL REFERENCES products (product_id),
    unit_price     INTEGER NOT NULL CHECK (unit_price >= 0),
    quantity       INTEGER NOT NULL CHECK (quantity > 0),
    discount_rate  NUMERIC(4, 2) NOT NULL CHECK (discount_rate BETWEEN 0 AND 1),
    subtotal       INTEGER NOT NULL,
    total_amount   INTEGER NOT NULL,
    sales_amount   INTEGER NOT NULL,
    region         TEXT NOT NULL,
    salesperson    TEXT NOT NULL,
    status         TEXT NOT NULL,
    review_flag    TEXT NOT NULL
);

CREATE INDEX idx_orders_customer_id ON orders (customer_id);
CREATE INDEX idx_orders_product_id ON orders (product_id);
CREATE INDEX idx_orders_review_flag ON orders (review_flag);

CREATE TABLE review_requests (
    order_id    TEXT PRIMARY KEY REFERENCES orders (order_id),
    reason      TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
