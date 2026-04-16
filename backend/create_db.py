import asyncio
import asyncpg

async def create_staging_db():
    # ↓ ここにRenderでコピーした「External Database URL」を貼り付けます
    # 例: "postgres://user:password@host/coco-db"
    render_db_url = "postgresql://coco_db_az91_user:1LKKhcUmTAB7NHRbDy5uFnqg2j1LipqS@dpg-d7akjtruibrs73e32990-a.oregon-postgres.render.com/coco_db_az91"
    
    print("データベースに接続中...")
    conn = await asyncpg.connect(render_db_url)
    
    try:
        print("coco_staging を作成しています...")
        await conn.execute('CREATE DATABASE coco_staging')
        print("✅ テスト用データベース (coco_staging) の作成に成功しました！")
    except asyncpg.exceptions.DuplicateDatabaseError:
        print("⚠️ すでに coco_staging は存在しています！")
    except Exception as e:
        print(f"❌ エラーが発生しました: {e}")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(create_staging_db())
