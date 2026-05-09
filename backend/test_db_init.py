
import asyncio
import os
import sys

# Add the current directory to sys.path to import modules correctly
sys.path.append(os.getcwd())

from backend.postgres_store import init_postgres, create_tables, is_initialized

async def test_db():
    print("Testing PostgreSQL connection and table creation...")
    try:
        init_postgres()
        if not is_initialized():
            print("Failed to initialize postgres store.")
            return
        
        await create_tables()
        print("Successfully created/verified tables in Neon Postgres.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_db())
