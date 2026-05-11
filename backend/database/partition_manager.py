import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
import asyncpg
from config import config
import os

logger = logging.getLogger("tradeclaw.partition_manager")

TABLES_TO_PARTITION = [
    "equity_history",
    "telemetry",
    "market_bars",
    "agent_signals",
    "bot_logs",
    "system_metrics"
]

async def create_monthly_partitions(conn: asyncpg.Connection, year: int, month: int):
    """Create partitions for a specific month if they don't exist."""
    start_date = f"{year}-{month:02d}-01"
    
    # Calculate next month
    if month == 12:
        next_year = year + 1
        next_month = 1
    else:
        next_year = year
        next_month = month + 1
    
    end_date = f"{next_year}-{next_month:02d}-01"
    suffix = f"y{year}m{month:02d}"

    for table in TABLES_TO_PARTITION:
        partition_name = f"{table}_{suffix}"
        logger.info(f"Ensuring partition {partition_name} exists for table {table}")
        
        # PostgreSQL doesn't have a simple 'CREATE PARTITION IF NOT EXISTS' syntax 
        # that works perfectly for range partitions without checking first
        try:
            await conn.execute(f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.relname = '{partition_name}') THEN
                        EXECUTE 'CREATE TABLE {partition_name} PARTITION OF {table} FOR VALUES FROM (''{start_date}'') TO (''{end_date}'')';
                    END IF;
                END
                $$;
            """)
        except Exception as e:
            logger.error(f"Failed to create partition {partition_name}: {e}")

async def maintenance_loop():
    """Periodically check and create partitions for the current and next month."""
    while True:
        try:
            db_url = config.database_url
            if not db_url:
                logger.error("Partition maintenance error: DATABASE_URL not set")
                await asyncio.sleep(60)
                continue
            conn = await asyncpg.connect(db_url)
            try:
                now = datetime.now(timezone.utc)
                # Ensure current month
                await create_monthly_partitions(conn, now.year, now.month)
                
                # Ensure next month (proactive)
                next_month_date = (now.replace(day=28) + timedelta(days=5)).replace(day=1)
                await create_monthly_partitions(conn, next_month_date.year, next_month_date.month)
                
                # Prune old high-frequency data (User request: 48 hours)
                # Running this hourly ensures we don't have massive bursts of deletions
                cutoff = now - timedelta(hours=48)
                
                res_tel = await conn.execute("DELETE FROM telemetry WHERE timestamp < $1", cutoff)
                logger.info(f"Telemetry pruning: {res_tel}")
                
                res_logs = await conn.execute("DELETE FROM bot_logs WHERE timestamp < $1", cutoff)
                logger.info(f"Bot logs pruning: {res_logs}")
                
                res_metrics = await conn.execute("DELETE FROM system_metrics WHERE timestamp < $1", cutoff)
                logger.info(f"System metrics pruning: {res_metrics}")
                
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"Partition maintenance error: {e}")
        
        # Run once an hour (to keep telemetry pruning tight)
        await asyncio.sleep(3600)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(maintenance_loop())
