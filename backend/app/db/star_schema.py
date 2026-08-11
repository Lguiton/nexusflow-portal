from sqlalchemy import text
from app.db.session import engine

async def init_star_schema():
    async with engine.begin() as conn:
        # 1. Dimension Tables
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS dim_clients (
                client_id SERIAL PRIMARY KEY,
                client_name VARCHAR(255) UNIQUE NOT NULL,
                tier VARCHAR(50) DEFAULT 'CORE_PORTAL',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))

        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS dim_date (
                date_key INT PRIMARY KEY,
                full_date DATE NOT NULL,
                year INT NOT NULL,
                quarter INT NOT NULL,
                month INT NOT NULL,
                month_name VARCHAR(20) NOT NULL
            );
        """))

        # 2. Fact Table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS fact_revenue (
                fact_id SERIAL PRIMARY KEY,
                client_id INT REFERENCES dim_clients(client_id),
                date_key INT REFERENCES dim_date(date_key),
                monthly_recurring_revenue NUMERIC(10, 2) NOT NULL,
                one_time_spend NUMERIC(10, 2) DEFAULT 0.00,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))

        # 3. Seed Sample Metrics for Dashboard Initialization
        await conn.execute(text("""
            INSERT INTO dim_clients (client_name, tier) 
            VALUES ('Acme Corp', 'GROWTH_OPTIMIZATION'), ('Global Logistics', 'ENTERPRISE_OPS')
            ON CONFLICT (client_name) DO NOTHING;
        """))

        await conn.execute(text("""
            INSERT INTO dim_date (date_key, full_date, year, quarter, month, month_name)
            VALUES (20260810, '2026-08-10', 2026, 3, 8, 'August')
            ON CONFLICT (date_key) DO NOTHING;
        """))

        await conn.execute(text("""
            INSERT INTO fact_revenue (client_id, date_key, monthly_recurring_revenue, one_time_spend)
            VALUES (1, 20260810, 5000.00, 1500.00), (2, 20260810, 12000.00, 3500.00)
            ON CONFLICT DO NOTHING;
        """))
