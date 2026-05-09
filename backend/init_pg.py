import asyncio
import os
import asyncpg
from dotenv import load_dotenv

async def main():
    load_dotenv()
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("No DATABASE_URL in environment.")
        return
    
    with open("database/schema.sql", "r") as f:
        schema = f.read()

    print("Connecting to DB...")
    conn = await asyncpg.connect(dsn)
    print("Executing schema...")
    await conn.execute(schema)
    print("Schema executed successfully.")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
