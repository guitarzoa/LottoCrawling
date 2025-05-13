// page/read-db.js
const mysql = require('mysql2/promise');

async function main() {
  const {
    DB_HOST = '127.0.0.1',
    DB_PORT = '3800',
    DB_USER = 'test',
    DB_PASSWORD = 'pwtest',
    DB_NAME = 'test',
  } = process.env;

  let conn;
  try {
    conn = await mysql.createConnection({
      host: DB_HOST,
      port: +DB_PORT,
      user: DB_USER,
      password: DB_PASSWORD,
      database: DB_NAME,
    });

    const [rows] = await conn.query('SELECT * FROM sample');
    console.log('🗒️ Sample 테이블 내용:');
    rows.forEach(({ id, name }) => {
      console.log(`  • [${id}] ${name}`);
    });
  } catch (err) {
    console.error('❌ DB 조회 중 에러 발생:', err);
    process.exit(1);
  } finally {
    if (conn) await conn.end();
  }
}

main();
